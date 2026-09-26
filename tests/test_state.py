"""群开关文件在重启和并发修改后的持久化验证。"""

import json
import tempfile
import unittest
from pathlib import Path

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from nonebot_plugin_group_rename.state import GroupState


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


if __name__ == "__main__":
    unittest.main()
