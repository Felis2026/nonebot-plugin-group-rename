"""群开关文件在重启和并发修改后的持久化验证。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init(driver="~none")

from nonebot_plugin_group_rename.state import GroupState, StateLoadError


class GroupStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_persists_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "groups.json"
            state = GroupState(path)
            self.assertFalse(state.is_enabled("100"))
            self.assertTrue(await state.set_enabled("100", True))
            self.assertFalse(await state.set_enabled("100", True))
            self.assertTrue(GroupState(path).is_enabled("100"))
            self.assertTrue(await state.set_enabled("100", False))
            self.assertFalse(GroupState(path).is_enabled("100"))

    async def test_concurrent_groups_do_not_overwrite(self) -> None:
        import asyncio

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "groups.json"
            state = GroupState(path)
            await asyncio.gather(*(state.set_enabled(str(i), True) for i in range(20)))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(saved["enabled_groups"]), {str(i) for i in range(20)})

    # ================================ 损坏文件保护与恢复 ================================ #

    async def test_corrupt_state_is_kept_and_all_toggle_writes_are_rejected(self) -> None:
        """语法、结构或编码错误都不能被下一次开关操作覆盖。"""
        for content in (b'{"enabled_groups": ["100",', b'{"enabled_groups": [100]}', b'[]', b'\xff'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "groups.json"
                path.write_bytes(content)
                state = GroupState(path)
                self.assertTrue(state.load_failed)
                self.assertFalse(state.is_enabled("100"))
                for enabled in (True, False):
                    with self.assertRaises(StateLoadError):
                        await state.set_enabled("200", enabled)
                self.assertEqual(path.read_bytes(), content)
                self.assertFalse(path.with_name("groups.json.tmp").exists())

    async def test_unreadable_state_does_not_turn_into_an_empty_writable_state(self) -> None:
        """权限或 I/O 故障也需要保护原文件，而非只处理 JSON 解析失败。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "groups.json"
            original = '{"enabled_groups": ["100"]}'
            path.write_text(original, encoding="utf-8")
            with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
                state = GroupState(path)
            with self.assertRaises(StateLoadError):
                await state.set_enabled("200", True)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    async def test_reloading_repaired_state_preserves_existing_groups(self) -> None:
        """人工修复并重新加载后，可在原有群记录基础上正常修改。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "groups.json"
            path.write_text("broken", encoding="utf-8")
            self.assertTrue(GroupState(path).load_failed)
            path.write_text('{"enabled_groups": ["100"]}', encoding="utf-8")
            state = GroupState(path)
            self.assertFalse(state.load_failed)
            await state.set_enabled("200", True)
            self.assertEqual(set(json.loads(path.read_text(encoding="utf-8"))["enabled_groups"]), {"100", "200"})


if __name__ == "__main__":
    unittest.main()
