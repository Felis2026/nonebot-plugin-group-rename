"""群开关文件在重启和并发修改后的持久化验证。"""

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init(driver="~none")

nonebot.require("nonebot_plugin_group_rename")
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
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "groups.json"
            state = GroupState(path)
            await asyncio.gather(*(state.set_enabled(str(i), True) for i in range(20)))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(saved["enabled_groups"]), {str(i) for i in range(20)})

    # ================================ 保存任务取消 ================================ #

    async def test_cancelled_save_finishes_before_next_toggle(self) -> None:
        """保存被重复取消时，等待写入完成，再允许关闭同群或修改其他群。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "groups.json"
            state = GroupState(path)
            await state.set_enabled("99", True)
            started, release = threading.Event(), threading.Event()
            original_write = state._write

            def delayed_write(groups: set[str]) -> None:
                """暂停首次写入，在实际工作线程运行期间触发取消。"""
                if "100" in groups:
                    started.set()
                    if not release.wait(5):
                        raise TimeoutError("测试写入未释放")
                original_write(groups)

            with patch.object(state, "_write", delayed_write):
                saving = asyncio.create_task(state.set_enabled("100", True))
                pending = []
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    for _ in range(2):
                        saving.cancel()
                        await asyncio.sleep(0)
                    self.assertFalse(saving.done())
                    pending = [
                        asyncio.create_task(state.set_enabled("100", False)),
                        asyncio.create_task(state.set_enabled("200", True)),
                    ]
                    await asyncio.sleep(0)
                    self.assertTrue(all(not task.done() for task in pending))
                finally:
                    release.set()
                    # 测试断言失败时也收尾线程，避免临时目录被后台写入占用。
                    results = await asyncio.gather(saving, *pending, return_exceptions=True)
                self.assertIsInstance(results[0], asyncio.CancelledError)
                self.assertEqual(results[1:], [True, True])
            self.assertEqual(state.enabled_groups, {"99", "200"})
            self.assertEqual(GroupState(path).enabled_groups, {"99", "200"})

    async def test_cancelled_failed_save_keeps_original_state(self) -> None:
        """被取消的保存最终失败时，保留原状态并允许下一次保存。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "groups.json"
            state = GroupState(path)
            await state.set_enabled("99", True)
            started, release = threading.Event(), threading.Event()

            def failed_write(groups: set[str]) -> None:
                """在线程写入期间暂停，随后模拟文件访问失败。"""
                started.set()
                if not release.wait(5):
                    raise TimeoutError("测试写入未释放")
                raise PermissionError("denied")

            with patch.object(state, "_write", failed_write):
                saving = asyncio.create_task(state.set_enabled("100", True))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    saving.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(saving.done())
                finally:
                    release.set()
                    result, = await asyncio.gather(saving, return_exceptions=True)
                self.assertIsInstance(result, PermissionError)
            self.assertEqual(state.enabled_groups, {"99"})
            self.assertEqual(GroupState(path).enabled_groups, {"99"})
            self.assertTrue(await state.set_enabled("200", True))
            self.assertEqual(GroupState(path).enabled_groups, {"99", "200"})

    # ================================ 损坏文件保护与恢复 ================================ #

    async def test_corrupt_state_is_kept_and_all_toggle_writes_are_rejected(self) -> None:
        """状态文件存在语法、结构或编码错误时，开关操作拒绝写入并保留原文件。"""
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
        """状态文件读取失败时，开关操作拒绝写入并保留原文件。"""
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
