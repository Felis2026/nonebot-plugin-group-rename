"""群开关与管理员限制使用同一套群角色权限。"""

import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import nonebot
from nonebot.rule import CommandRule

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init(driver="~none")

from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot_plugin_group_rename.logic import GroupCooldown


plugin = importlib.import_module("nonebot_plugin_group_rename")


def group_event(role: str, user_id: int = 2) -> GroupMessageEvent:
    """构造包含 OneBot 群角色和有效车牌消息的真实事件模型。"""
    return GroupMessageEvent.model_validate(
        {
            "time": 1,
            "self_id": 9,
            "post_type": "message",
            "sub_type": "normal",
            "user_id": user_id,
            "message_type": "group",
            "message_id": 3,
            "message": "12345",
            "original_message": "12345",
            "raw_message": "12345",
            "font": 0,
            "sender": {"user_id": user_id, "role": role},
            "group_id": 1,
        }
    )


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        """使用真实 OneBot 对象，让官方权限检查走完整的依赖注入流程。"""
        self.driver = nonebot.get_driver()
        self.bot = Bot(Adapter(self.driver), "9")

    async def test_chinese_command_alias_shares_matcher(self) -> None:
        """中英文命令应注册在同一个响应器上，共用权限与处理逻辑。"""
        commands = {
            command
            for checker in plugin.group_rename_command.rule.checkers
            if isinstance(checker.call, CommandRule)
            for command in checker.call.cmds
        }
        self.assertEqual(commands, {("group_rename",), ("改群名",)})

    async def test_command_allows_admin_owner_and_superuser(self) -> None:
        with patch.object(self.driver.config, "superusers", {"99"}):
            for event in (
                group_event("admin"),
                group_event("owner"),
                group_event("member", user_id=99),
            ):
                self.assertTrue(await plugin.group_rename_command.permission(self.bot, event))
            self.assertFalse(
                await plugin.group_rename_command.permission(self.bot, group_event("member"))
            )

    async def test_admin_only_uses_same_permission(self) -> None:
        config = SimpleNamespace(group_rename_admin_only=True, group_rename_ignore_patterns=[])
        state = SimpleNamespace(is_enabled=lambda group_id: group_id == "1")
        with (
            patch.object(self.driver.config, "superusers", {"onebot:99"}),
            patch.object(plugin, "config", config),
            patch.object(plugin, "state", state),
        ):
            self.assertTrue(await plugin._is_rename_message(self.bot, group_event("admin")))
            self.assertTrue(await plugin._is_rename_message(self.bot, group_event("owner")))
            self.assertTrue(await plugin._is_rename_message(self.bot, group_event("member", user_id=99)))
            self.assertFalse(await plugin._is_rename_message(self.bot, group_event("member")))

    # ================================ 官方权限兼容与群内限制 ================================ #

    async def test_superuser_accepts_both_formats_and_rejects_other_adapter(self) -> None:
        """纯 ID 与 onebot:ID 均有效，其他适配器的同 ID 不获得 OneBot 权限。"""
        event = group_event("member", user_id=99)
        for configured, expected in (({"99"}, True), ({"onebot:99"}, True), ({"telegram:99"}, False)):
            with self.subTest(configured=configured), patch.object(self.driver.config, "superusers", configured):
                self.assertEqual(await plugin.group_rename_command.permission(self.bot, event), expected)

    async def test_superuser_cannot_manage_group_switch_in_private_chat(self) -> None:
        """复用 SUPERUSER 后仍须拒绝私聊，避免把群开关命令的范围扩大。"""
        data = group_event("member", user_id=99).model_dump()
        data.pop("group_id")
        data.update(message_type="private", sub_type="friend")
        event = PrivateMessageEvent.model_validate(data)
        with patch.object(self.driver.config, "superusers", {"onebot:99"}):
            self.assertFalse(await plugin.group_rename_command.permission(self.bot, event))
            self.assertFalse(await plugin._is_rename_message(self.bot, event))

    async def test_handler_rechecks_admin_only_with_official_superuser_permission(self) -> None:
        """直接进入处理器也必须再次校验身份，不能只依赖匹配阶段。"""
        config = SimpleNamespace(
            group_rename_admin_only=True, group_rename_ignore_patterns=[],
            group_rename_max_length=30, group_rename_enable_notify=False,
        )
        read = AsyncMock(return_value={"group_name": "讨论群"})
        rename = AsyncMock()
        with (
            patch.object(self.driver.config, "superusers", {"onebot:99"}),
            patch.object(plugin, "config", config),
            patch.object(plugin, "state", SimpleNamespace(is_enabled=lambda group_id: True)),
            patch.object(plugin, "cooldown", GroupCooldown(0)),
            patch.object(self.bot, "get_group_info", read, create=True),
            patch.object(self.bot, "set_group_name", rename, create=True),
        ):
            await plugin.handle_rename(self.bot, group_event("member", user_id=99))
            await plugin.handle_rename(self.bot, group_event("member"))
        read.assert_awaited_once_with(group_id=1, no_cache=True)
        rename.assert_awaited_once_with(group_id=1, group_name="12345 讨论群")


if __name__ == "__main__":
    unittest.main()
