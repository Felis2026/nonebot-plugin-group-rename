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

# 通过框架注册插件，localstore 才能识别调用方及其专属目录。
nonebot.require("nonebot_plugin_group_rename")
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
        """宿主包含全局参数时，插件仍正常加载默认配置。"""
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
        """JSON 格式或参数错误时加载失败，即使宿主提供了覆盖值。"""
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


# ================================ 启动时响应器与存储路径 ================================ #


class MatcherConfigTests(unittest.TestCase):
    def _check_startup(
        self, host: dict, file_data: dict, expected_priority: int,
        plugin_directories: bool = False,
        dotenv_priority: int | None = None,
        environment_priority: int | None = None,
    ) -> None:
        """在新进程验证插件配置、响应器及默认或专属目录中的状态读写。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            default_config_dir = root / "config" / "nonebot_plugin_group_rename"
            default_data_dir = root / "data" / "nonebot_plugin_group_rename"
            config_dir = root / "custom-config" if plugin_directories else default_config_dir
            data_dir = root / "custom-data" if plugin_directories else default_data_dir
            config_dir.mkdir(parents=True)
            data_dir.mkdir(parents=True)
            # 准备插件启动前已有的配置和群开关记录。
            (config_dir / "config.json").write_text(json.dumps(file_data), encoding="utf-8")
            (data_dir / "groups.json").write_text(
                json.dumps({"enabled_groups": ["100"]}), encoding="utf-8"
            )
            if plugin_directories:
                default_config_dir.mkdir(parents=True)
                default_data_dir.mkdir(parents=True)
                (default_config_dir / "config.json").write_text(
                    '{"group_rename_priority": 0}', encoding="utf-8"
                )
                (default_data_dir / "groups.json").write_text(
                    '{"enabled_groups": ["999"]}', encoding="utf-8"
                )
            env = {
                **os.environ,
                "PYTHONUTF8": "1",
                "LOCALSTORE_CONFIG_DIR": str(root / "config"),
                "LOCALSTORE_DATA_DIR": str(root / "data"),
                "LOCALSTORE_CACHE_DIR": str(root / "cache"),
                "LOCALSTORE_PLUGIN_CONFIG_DIR": json.dumps(
                    {"nonebot_plugin_group_rename": str(config_dir)} if plugin_directories else {}
                ),
                "LOCALSTORE_PLUGIN_DATA_DIR": json.dumps(
                    {"nonebot_plugin_group_rename": str(data_dir)} if plugin_directories else {}
                ),
            }
            # 在新进程中读取 .env 和环境变量，验证宿主加载器的配置优先级。
            host = dict(host)
            env.pop("GROUP_RENAME_PRIORITY", None)
            if dotenv_priority is not None:
                dotenv_file = root / "bot.env"
                dotenv_file.write_text(
                    f"GROUP_RENAME_PRIORITY={dotenv_priority}\n", encoding="utf-8"
                )
                host["_env_file"] = str(dotenv_file)
            else:
                host["_env_file"] = None
            if environment_priority is not None:
                env["GROUP_RENAME_PRIORITY"] = str(environment_priority)
            code = f"""
import asyncio
import json
from pathlib import Path
import nonebot
nonebot.init(driver="~none", **{host!r})
loaded = nonebot.load_plugin("nonebot_plugin_group_rename")
assert loaded is not None
plugin = loaded.module
assert plugin.group_rename_command.priority == {expected_priority}
assert plugin.rename_matcher.priority == {expected_priority}
assert plugin.group_rename_command.block is False
assert plugin.rename_matcher.block is False
assert plugin.config.group_rename_admin_only is False
assert plugin.cooldown.seconds == 3
from nonebot_plugin_group_rename.config import CONFIG_FILE
assert CONFIG_FILE == Path({str(config_dir / 'config.json')!r})
assert plugin.state.path == Path({str(data_dir / 'groups.json')!r})
assert plugin.state.is_enabled("100")
assert not plugin.state.is_enabled("999")
asyncio.run(plugin.state.set_enabled("200", True))
"""
            result = subprocess.run(
                [sys.executable, "-c", code], env=env,
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads((config_dir / "config.json").read_text(encoding="utf-8")),
                file_data,
            )
            self.assertEqual(
                json.loads((data_dir / "groups.json").read_text(encoding="utf-8")),
                {"enabled_groups": ["100", "200"]},
            )
            if plugin_directories:
                self.assertEqual(
                    json.loads((default_data_dir / "groups.json").read_text(encoding="utf-8")),
                    {"enabled_groups": ["999"]},
                )

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

    def test_plugin_specific_directories_control_config_and_state(self) -> None:
        """配置和状态从专属目录读取，状态修改写回同一目录。"""
        self._check_startup(
            {}, {"group_rename_priority": 6, "group_rename_cooldown_seconds": 3}, 6,
            plugin_directories=True,
        )

    def test_real_host_sources_override_json_in_standard_order(self) -> None:
        """实际 .env、环境变量、初始化参数依次覆盖，插件不改写用户配置。"""
        for host, environment_priority, expected_priority in (
            ({}, None, 6),
            ({}, 8, 8),
            ({"group_rename_priority": 9}, 8, 9),
        ):
            with self.subTest(expected_priority=expected_priority):
                self._check_startup(
                    host,
                    {"group_rename_priority": 4, "group_rename_cooldown_seconds": 3},
                    expected_priority,
                    dotenv_priority=6,
                    environment_priority=environment_priority,
                )


if __name__ == "__main__":
    unittest.main()
