"""群开关与管理员限制使用同一套群角色权限。"""

import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import nonebot
from nonebot.rule import CommandRule

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from nonebot.adapters.onebot.v11 import GroupMessageEvent


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
        driver = SimpleNamespace(config=SimpleNamespace(superusers={"99"}))
        with patch.object(plugin, "get_driver", return_value=driver):
            for event in (
                group_event("admin"),
                group_event("owner"),
                group_event("member", user_id=99),
            ):
                self.assertTrue(await plugin.group_rename_command.permission(None, event))
            self.assertFalse(
                await plugin.group_rename_command.permission(None, group_event("member"))
            )

    async def test_admin_only_uses_same_permission(self) -> None:
        driver = SimpleNamespace(config=SimpleNamespace(superusers={"99"}))
        config = SimpleNamespace(group_rename_admin_only=True, group_rename_ignore_patterns=[])
        state = SimpleNamespace(is_enabled=lambda group_id: group_id == "1")
        with (
            patch.object(plugin, "get_driver", return_value=driver),
            patch.object(plugin, "config", config),
            patch.object(plugin, "state", state),
        ):
            self.assertTrue(plugin._is_rename_message(group_event("admin")))
            self.assertTrue(plugin._is_rename_message(group_event("owner")))
            self.assertTrue(plugin._is_rename_message(group_event("member", user_id=99)))
            self.assertFalse(plugin._is_rename_message(group_event("member")))


if __name__ == "__main__":
    unittest.main()
