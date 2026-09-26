"""通过 OneBot V11 群消息中的车牌改群名。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from nonebot import get_driver, logger, on_command, on_message, require
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import ActionFailed, Bot, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.permission import Permission
from nonebot.plugin import PluginMetadata

# 持久化目录由 localstore 决定，避免依赖 Bot 的启动工作目录。
require("nonebot_plugin_localstore")
import nonebot_plugin_localstore as localstore

from .config import Config, load_config
from .logic import GroupCooldown, build_group_name, message_trigger
from .state import GroupState


__plugin_meta__ = PluginMetadata(
    name="改群名",
    description="适用于 PJSK、BanG Dream! 等使用五位房间号固车、冲榜群的改群名插件。按群启用后，发送独立的连续五位数字可更新群名开头的车牌，发送“清空”可移除旧车牌。",
    usage="群管理员、群主或 SUPERUSER 在目标群发送 /group_rename on 或 /改群名 on 开启；使用 off 关闭、status 查看状态。开启后，在群内发送五位房间号或“清空”即可操作群名。",
    type="application",
    homepage="https://github.com/Felis2026/nonebot-plugin-group-rename",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

config = load_config(localstore.get_config_file("nonebot_plugin_group_rename", "config.json"))
# 显式指定插件名，使数据目录不依赖当前模块的调用上下文。
state = GroupState(localstore.get_data_file("nonebot_plugin_group_rename", "groups.json"))
cooldown = GroupCooldown(config.group_rename_cooldown_seconds)
group_locks: dict[str, asyncio.Lock] = {}


def _group_lock(group_id: str) -> asyncio.Lock:
    """按群复用锁，让改名和群开关操作按到达顺序执行。"""
    # 同一事件循环内创建锁的过程不含 await，不会为同群创建两把锁。
    if group_id not in group_locks:
        group_locks[group_id] = asyncio.Lock()
    return group_locks[group_id]


def _is_group_admin_or_superuser(event: Event) -> bool:
    """允许当前群管理员、群主及 NoneBot 超级用户管理本群。"""
    if not isinstance(event, GroupMessageEvent):
        return False
    # OneBot V11 的群内角色只有 owner/admin/member；缺失角色时不放行。
    return (
        event.sender.role in {"admin", "owner"}
        or event.get_user_id() in get_driver().config.superusers
    )


def _message_trigger(event: GroupMessageEvent) -> str | None:
    """从 OneBot 消息段读取车牌，不跨 @、图片或回复拼接数字。"""
    segments = (
        (segment.type, str(segment.data.get("text", "")))
        for segment in event.get_message()
    )
    return message_trigger(segments, config.group_rename_ignore_patterns)


def _is_rename_message(event: Event) -> bool:
    """只让已启用群的有效车牌消息进入改名处理。"""
    if not isinstance(event, GroupMessageEvent):
        return False
    if not state.is_enabled(str(event.group_id)):
        return False
    if config.group_rename_admin_only and not _is_group_admin_or_superuser(event):
        return False
    return _message_trigger(event) is not None


def _is_permission_failure(exc: ActionFailed) -> bool:
    """只根据 OneBot 返回的权限字样识别权限失败，不猜测 retcode 的平台含义。"""
    # 不同 OneBot 实现的错误码并不统一，文字字段更适合做保守识别。
    details = " ".join(str(exc.info.get(key, "")) for key in ("wording", "message", "msg"))
    details = details.casefold()
    return any(
        marker in details
        for marker in ("权限", "管理员", "无权", "permission", "not admin", "forbidden")
    )


# ================================ 群开关命令 ================================ #

group_rename_command = on_command(
    "group_rename",
    aliases={"改群名"},
    permission=Permission(_is_group_admin_or_superuser),
    priority=1,
    block=False,
)


@group_rename_command.handle()
async def handle_group_rename_command(event: GroupMessageEvent, args=CommandArg()) -> None:
    """群管理员、群主或超级用户管理当前群的插件开关。"""
    action = args.extract_plain_text().strip().lower()
    group_id = str(event.group_id)
    if action == "status":
        enabled = state.is_enabled(group_id)
        await group_rename_command.send("改群名：已开启" if enabled else "改群名：已关闭")
        return
    if action not in {"on", "off"}:
        await group_rename_command.send("用法：/group_rename 或 /改群名，后接 on|off|status")
        return

    # 关闭须等待当前群已开始的改名完成；排队中的改名随后会重新检查开关。
    async with _group_lock(group_id):
        try:
            changed = await state.set_enabled(group_id, action == "on")
        except OSError as exc:
            logger.error(f"保存群 {group_id} 的改群名开关失败: {exc}")
            await group_rename_command.send("改群名开关保存失败")
            return
    status = "已开启" if action == "on" else "已关闭"
    await group_rename_command.send(f"改群名：{status}" if changed else f"改群名：已经{status[1:]}")


# ================================ 群名修改 ================================ #

rename_matcher = on_message(rule=_is_rename_message, priority=1, block=False)


@rename_matcher.handle()
async def handle_rename(bot: Bot, event: GroupMessageEvent) -> None:
    """按群串行读取当前群名，在冷却许可时提交改名。"""
    trigger = _message_trigger(event)
    if trigger is None:
        return

    group_id = str(event.group_id)
    async with _group_lock(group_id):
        # 匹配到执行之间可能关闭群开关或改动权限，必须再次检查。
        if not state.is_enabled(group_id):
            return
        if config.group_rename_admin_only and not _is_group_admin_or_superuser(event):
            return
        if not cooldown.allow(group_id):
            if config.group_rename_enable_notify:
                await rename_matcher.send("⏳改名太频繁，请稍后再试")
            return

        # ================================ 读取当前群名 ================================ #
        # 禁用适配器缓存，连续改名以服务端当前群名为准。
        try:
            info = await bot.get_group_info(group_id=event.group_id, no_cache=True)
        except ActionFailed as exc:
            logger.error(f"读取群 {group_id} 名称被 OneBot 拒绝: {exc!r}")
            if config.group_rename_enable_notify:
                await rename_matcher.send("❌读取群名失败：OneBot 接口返回错误")
            return
        except Exception as exc:
            logger.error(f"读取群 {group_id} 名称异常: {exc!r}")
            if config.group_rename_enable_notify:
                await rename_matcher.send("❌读取群名失败：请求异常，请稍后重试")
            return

        if not isinstance(info, Mapping) or not isinstance(info.get("group_name"), str):
            logger.error(f"群 {group_id} 的信息缺少可用群名")
            if config.group_rename_enable_notify:
                await rename_matcher.send("❌读取群名失败：接口未返回有效群名")
            return

        # ================================ 构造并提交群名 ================================ #
        current_name = info["group_name"]
        try:
            target_name = build_group_name(
                current_name,
                None if trigger == "clear" else trigger,
                config.group_rename_max_length,
            )
            # OneBot 的 set_group_name 不能提交空群名；仅有车牌时保留原名并提示。
            if not target_name:
                cooldown.cancel_noop(group_id)
                if config.group_rename_enable_notify:
                    await rename_matcher.send("群名只剩车牌，无法清空；请先手动设置群名")
                return
            if target_name == current_name:
                cooldown.cancel_noop(group_id)
                return
            await bot.set_group_name(group_id=event.group_id, group_name=target_name)
        except ActionFailed as exc:
            logger.error(f"修改群 {group_id} 名称被 OneBot 拒绝: {exc!r}")
            if config.group_rename_enable_notify:
                message = (
                    "❌改群名失败：Bot 缺少修改群名的权限"
                    if _is_permission_failure(exc)
                    else "❌改群名失败：OneBot 拒绝了改名请求，请检查 Bot 权限或服务端日志"
                )
                await rename_matcher.send(message)
        except Exception as exc:
            logger.error(f"修改群 {group_id} 名称异常: {exc!r}")
            if config.group_rename_enable_notify:
                await rename_matcher.send("❌改群名失败：请求异常，请稍后重试")
