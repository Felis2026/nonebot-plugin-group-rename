"""配置来源合并、严格 JSON 校验与实际响应器注册的回归。"""

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nonebot
from pydantic import ValidationError

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init(driver="~none")

config_module = importlib.import_module("nonebot_plugin_group_rename.config")
Config = config_module.Config


# ================================ 配置来源与校验 ================================ #


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        """每项测试使用独立配置文件，不读取或写入宿主 Bot 的真实参数。"""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "config.json"
        config_path = patch.object(config_module, "CONFIG_FILE", self.path)
        config_path.start()
        self.addCleanup(config_path.stop)

    def test_max_length_must_fit_full_plate(self) -> None:
        with self.assertRaises(ValidationError):
            Config(group_rename_max_length=4)
        self.assertEqual(Config(group_rename_max_length=5).group_rename_max_length, 5)

    def test_standard_loader_uses_defaults_without_json(self) -> None:
        """NoneBot 全局参数不应误报成插件的未知字段。"""
        config = nonebot.get_plugin_config(Config)
        self.assertEqual(config.group_rename_max_length, 30)
        self.assertEqual(config.group_rename_priority, 1)
        self.assertFalse(config.group_rename_admin_only)

    def test_json_overrides_defaults_but_host_overrides_json(self) -> None:
        """宿主显式值（包括 False、0、空列表）覆盖 JSON，其他项继续继承 JSON。"""
        self.path.write_text(json.dumps({
            "group_rename_admin_only": True,
            "group_rename_ignore_patterns": ["12345"],
            "group_rename_cooldown_seconds": 30,
            "group_rename_max_length": 20,
        }), encoding="utf-8")
        config = nonebot.get_plugin_config(Config)
        self.assertTrue(config.group_rename_admin_only)
        self.assertEqual(config.group_rename_cooldown_seconds, 30)
        # 通过属性写入，让 Pydantic v1/v2 都能把宿主的扩展字段导出给加载器。
        driver_config = nonebot.get_driver().config
        with (
            patch.object(driver_config, "group_rename_admin_only", False, create=True),
            patch.object(driver_config, "group_rename_ignore_patterns", [], create=True),
            patch.object(driver_config, "group_rename_cooldown_seconds", 0, create=True),
        ):
            config = nonebot.get_plugin_config(Config)
        self.assertFalse(config.group_rename_admin_only)
        self.assertEqual(config.group_rename_ignore_patterns, [])
        self.assertEqual(config.group_rename_cooldown_seconds, 0)
        self.assertEqual(config.group_rename_max_length, 20)

    def test_invalid_json_is_not_hidden_by_host_overrides(self) -> None:
        """文件损坏、未知字段和非法参数均应报错，宿主覆盖也不能掩盖它们。"""
        for contents in (
            "broken", "[]", "null", '{"unknown_key": true}',
            '{"group_rename_max_length": 4}',
            '{"group_rename_cooldown_seconds": -1}',
            '{"group_rename_priority": -1}',
            '{"group_rename_admin_only": null}',
        ):
            with self.subTest(contents=contents):
                self.path.write_text(contents, encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    Config(group_rename_max_length=30, group_rename_priority=1)

    def test_invalid_file_encoding_reports_configuration_error(self) -> None:
        self.path.write_bytes(b"\xff\xfe")
        with self.assertRaises(RuntimeError):
            nonebot.get_plugin_config(Config)

    def test_priority_rejects_negative_values_and_accepts_zero(self) -> None:
        with self.assertRaises(ValidationError):
            Config(group_rename_priority=-1)
        self.assertEqual(Config(group_rename_priority=0).group_rename_priority, 0)


# ================================ 启动时响应器注册 ================================ #


class MatcherConfigTests(unittest.TestCase):
    def _check_startup(self, host: dict, file_data: dict, expected_priority: int) -> None:
        """用新进程加载真实插件，避免重载时残留响应器干扰优先级验证。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {
                **os.environ,
                "PYTHONUTF8": "1",
                "LOCALSTORE_CONFIG_DIR": str(root / "config"),
                "LOCALSTORE_DATA_DIR": str(root / "data"),
                "LOCALSTORE_CACHE_DIR": str(root / "cache"),
            }
            code = f"""
import json
import nonebot
nonebot.init(driver="~none", **{host!r})
nonebot.require("nonebot_plugin_localstore")
import nonebot_plugin_localstore as localstore
path = localstore.get_config_file("nonebot_plugin_group_rename", "config.json")
path.write_text(json.dumps({file_data!r}), encoding="utf-8")
loaded = nonebot.load_plugin("nonebot_plugin_group_rename")
assert loaded is not None
plugin = loaded.module
assert plugin.group_rename_command.priority == {expected_priority}
assert plugin.rename_matcher.priority == {expected_priority}
assert plugin.group_rename_command.block is False
assert plugin.rename_matcher.block is False
assert plugin.config.group_rename_admin_only is False
assert plugin.cooldown.seconds == 3
"""
            result = subprocess.run(
                [sys.executable, "-c", code], env=env,
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_both_matchers_use_host_priority(self) -> None:
        self._check_startup(
            {"group_rename_priority": 9, "group_rename_admin_only": False},
            {"group_rename_priority": 4, "group_rename_admin_only": True,
             "group_rename_cooldown_seconds": 3},
            9,
        )

    def test_both_matchers_use_json_priority(self) -> None:
        self._check_startup(
            {}, {"group_rename_priority": 6, "group_rename_cooldown_seconds": 3}, 6,
        )


if __name__ == "__main__":
    unittest.main()
