"""群消息识别和群名构造的行为回归。"""

import unittest
import tempfile
from pathlib import Path

import nonebot
from pydantic import ValidationError

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from nonebot_plugin_group_rename.logic import (
    GroupCooldown,
    build_group_name,
    message_trigger,
)
from nonebot_plugin_group_rename.config import Config, load_config


class MessageTriggerTests(unittest.TestCase):
    def test_plain_and_mixed_segments(self) -> None:
        self.assertEqual(message_trigger([("text", " 12345 ")], []), "12345")
        self.assertEqual(
            message_trigger(
                [("reply", ""), ("at", ""), ("text", "12345"), ("image", "")],
                [],
            ),
            "12345",
        )
        self.assertEqual(message_trigger([("text", "清空"), ("image", "")], []), "clear")

    def test_rejects_split_numbers_and_extra_text(self) -> None:
        self.assertIsNone(
            message_trigger([("text", "12"), ("image", ""), ("text", "345")], [])
        )
        self.assertIsNone(message_trigger([("text", "前缀 12345")], []))
        self.assertIsNone(message_trigger([("text", "123456")], []))
        self.assertIsNone(message_trigger([("text", "12345")], ["12345"]))


class GroupNameTests(unittest.TestCase):
    def test_replace_and_clear(self) -> None:
        self.assertEqual(build_group_name("讨论群", "12345", 30), "12345 讨论群")
        self.assertEqual(build_group_name("67890 讨论群", "12345", 30), "12345 讨论群")
        self.assertEqual(build_group_name("67890 讨论群", None, 30), "讨论群")

    def test_long_old_numbers_and_empty_remainder(self) -> None:
        self.assertEqual(build_group_name("1234567讨论群", "12345", 30), "12345 讨论群")
        self.assertEqual(build_group_name("1234567", "12345", 30), "12345")
        self.assertEqual(build_group_name("12345 群", "67890", 5), "67890")


class CooldownTests(unittest.TestCase):
    def test_default_is_one_second(self) -> None:
        self.assertEqual(GroupCooldown().seconds, 1)

    def test_cooldown_is_per_group(self) -> None:
        cooldown = GroupCooldown(3)
        self.assertTrue(cooldown.allow("1"))
        self.assertFalse(cooldown.allow("1"))
        self.assertTrue(cooldown.allow("2"))


class ConfigTests(unittest.TestCase):
    def test_max_length_must_fit_full_plate(self) -> None:
        with self.assertRaises(ValidationError):
            Config(group_rename_max_length=4)
        self.assertEqual(Config(group_rename_max_length=5).group_rename_max_length, 5)

    def test_json_config_defaults_overrides_and_invalid_values(self) -> None:
        """独立文件可覆盖默认参数；错误配置不能静默退回默认值。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            self.assertEqual(load_config(path), Config())

            path.write_text('{"group_rename_admin_only": true}', encoding="utf-8")
            self.assertTrue(load_config(path).group_rename_admin_only)

            path.write_text('{"group_rename_max_length": 4}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_config(path)

            path.write_text('{"unknown_key": true}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
