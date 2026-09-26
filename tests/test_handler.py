"""同群改名的串行行为验证。"""

import asyncio
import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import nonebot
from nonebot.adapters.onebot.v11 import ActionFailed

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from nonebot_plugin_group_rename.logic import GroupCooldown


plugin = importlib.import_module("nonebot_plugin_group_rename")


class FakeBot:
    def __init__(self) -> None:
        self.name = "讨论群"
        self.read_names: list[str] = []
        self.no_cache_values: list[bool] = []
        self.set_names: list[str] = []

    async def get_group_info(self, *, group_id: int, no_cache: bool) -> dict[str, str]:
        self.no_cache_values.append(no_cache)
        self.read_names.append(self.name)
        await asyncio.sleep(0.01)
        return {"group_name": self.name}

    async def set_group_name(self, *, group_id: int, group_name: str) -> None:
        self.set_names.append(group_name)
        self.name = group_name


class RenameHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_group_reads_latest_name_serially(self) -> None:
        bot = FakeBot()
        state = SimpleNamespace(is_enabled=lambda group_id: group_id == "1")
        events = [
            SimpleNamespace(group_id=1, trigger="12345"),
            SimpleNamespace(group_id=1, trigger="67890"),
        ]

        with (
            patch.object(plugin, "state", state),
            patch.object(plugin, "cooldown", GroupCooldown(0)),
            patch.object(plugin, "_message_trigger", lambda event: event.trigger),
        ):
            await asyncio.gather(*(plugin.handle_rename(bot, event) for event in events))

        self.assertEqual(bot.read_names, ["讨论群", "12345 讨论群"])
        self.assertEqual(bot.name, "67890 讨论群")
        self.assertEqual(bot.no_cache_values, [True, True])

    async def test_clear_only_plate_keeps_name_and_explains(self) -> None:
        """旧群名仅含车牌时，不向 OneBot 提交空群名。"""
        bot = FakeBot()
        bot.name = "12345"
        event = SimpleNamespace(group_id=1, trigger="clear")
        state = SimpleNamespace(is_enabled=lambda group_id: group_id == "1")
        send = AsyncMock()

        with (
            patch.object(plugin, "state", state),
            patch.object(plugin, "cooldown", GroupCooldown(0)),
            patch.object(plugin, "_message_trigger", lambda event: event.trigger),
            patch.object(plugin.rename_matcher, "send", send),
        ):
            await plugin.handle_rename(bot, event)

        self.assertEqual(bot.name, "12345")
        self.assertEqual(bot.set_names, [])
        send.assert_awaited_once_with("群名只剩车牌，无法清空；请先手动设置群名")

    async def test_unchanged_name_does_not_consume_cooldown(self) -> None:
        """相同车牌和无法清空的群名都不能挡住随后的有效改名。"""
        cases = (
            ("12345 讨论群", "12345", "67890 讨论群"),
            ("12345", "clear", "67890"),
        )
        state = SimpleNamespace(is_enabled=lambda group_id: group_id == "1")
        for initial_name, first_trigger, expected_name in cases:
            with self.subTest(initial_name=initial_name):
                bot = FakeBot()
                bot.name = initial_name
                send = AsyncMock()
                with (
                    patch.object(plugin, "state", state),
                    patch.object(plugin, "cooldown", GroupCooldown(60)),
                    patch.object(plugin, "_message_trigger", lambda event: event.trigger),
                    patch.object(plugin.rename_matcher, "send", send),
                ):
                    await plugin.handle_rename(bot, SimpleNamespace(group_id=1, trigger=first_trigger))
                    await plugin.handle_rename(bot, SimpleNamespace(group_id=1, trigger="67890"))
                self.assertEqual(bot.set_names, [expected_name])

    # ================================ 异常提示 ================================ #

    async def test_read_failures_report_the_failed_step(self) -> None:
        """读取 API 失败或缺少群名时，不将问题误报成改名权限失败。"""
        cases = (
            (ActionFailed(wording="接口错误"), "❌读取群名失败：OneBot 接口返回错误"),
            (RuntimeError("连接中断"), "❌读取群名失败：请求异常，请稍后重试"),
            ({}, "❌读取群名失败：接口未返回有效群名"),
            ("异常响应", "❌读取群名失败：接口未返回有效群名"),
        )
        state = SimpleNamespace(is_enabled=lambda group_id: group_id == "1")
        event = SimpleNamespace(group_id=1, trigger="12345")

        for result, expected in cases:
            with self.subTest(result=result):
                bot = FakeBot()
                send = AsyncMock()
                read = (
                    AsyncMock(side_effect=result)
                    if isinstance(result, Exception)
                    else AsyncMock(return_value=result)
                )
                with (
                    patch.object(plugin, "state", state),
                    patch.object(plugin, "cooldown", GroupCooldown(0)),
                    patch.object(plugin, "_message_trigger", lambda event: event.trigger),
                    patch.object(bot, "get_group_info", read),
                    patch.object(plugin.rename_matcher, "send", send),
                ):
                    await plugin.handle_rename(bot, event)
                self.assertEqual(bot.set_names, [])
                send.assert_awaited_once_with(expected)

    async def test_set_failures_distinguish_permission_and_other_errors(self) -> None:
        """只在 OneBot 错误文字明确指向权限时给出权限提示。"""
        cases = (
            (ActionFailed(wording="权限不足"), "❌改群名失败：Bot 缺少修改群名的权限"),
            (
                ActionFailed(wording="群名包含敏感词"),
                "❌改群名失败：OneBot 拒绝了改名请求，请检查 Bot 权限或服务端日志",
            ),
            (RuntimeError("连接中断"), "❌改群名失败：请求异常，请稍后重试"),
        )
        state = SimpleNamespace(is_enabled=lambda group_id: group_id == "1")
        event = SimpleNamespace(group_id=1, trigger="12345")

        for error, expected in cases:
            with self.subTest(error=error):
                bot = FakeBot()
                send = AsyncMock()
                with (
                    patch.object(plugin, "state", state),
                    patch.object(plugin, "cooldown", GroupCooldown(0)),
                    patch.object(plugin, "_message_trigger", lambda event: event.trigger),
                    patch.object(bot, "set_group_name", AsyncMock(side_effect=error)),
                    patch.object(plugin.rename_matcher, "send", send),
                ):
                    await plugin.handle_rename(bot, event)
                send.assert_awaited_once_with(expected)


if __name__ == "__main__":
    unittest.main()
