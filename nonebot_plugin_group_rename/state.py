"""独立保存已启用群的状态。"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from nonebot import logger


class StateLoadError(RuntimeError):
    """状态读取失败时拒绝写入，保留原文件供维护者修复。"""


class GroupState:
    """管理已启用群，并把变更原子写入 JSON 文件。"""

    def __init__(self, path: Path):
        self.path = path
        self.load_failed = False
        self.enabled_groups = self._load()
        self._write_lock = asyncio.Lock()

    def _load(self) -> set[str]:
        """文件缺失时默认关闭；读取失败时关闭所有群并锁住后续写入。"""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            groups = data["enabled_groups"]
            if not isinstance(groups, list) or not all(isinstance(x, str) for x in groups):
                raise ValueError("enabled_groups 必须为字符串数组")
            return set(groups)
        except FileNotFoundError:
            return set()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # 空集合仅用于停止自动改名，不能拿它覆盖尚可人工修复的原文件。
            self.load_failed = True
            logger.error(f"读取改群名群开关文件 {self.path} 失败，已禁止写入；修复后请重启 Bot: {exc}")
            return set()

    def is_enabled(self, group_id: str) -> bool:
        """返回当前群开关状态。"""
        return group_id in self.enabled_groups

    def _write(self, groups: set[str]) -> None:
        """在工作线程内写临时文件并替换，防止进程中断留下半份 JSON。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            temporary.write_text(
                json.dumps({"enabled_groups": sorted(groups)}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    async def set_enabled(self, group_id: str, enabled: bool) -> bool:
        """持久化群开关；失败时保留原内存状态并交给调用方反馈。"""
        async with self._write_lock:
            if self.load_failed:
                raise StateLoadError(f"群开关文件 {self.path} 未正确加载，修复后请重启 Bot")
            if (group_id in self.enabled_groups) == enabled:
                return False
            updated = set(self.enabled_groups)
            if enabled:
                updated.add(group_id)
            else:
                updated.remove(group_id)
            await asyncio.to_thread(self._write, updated)
            self.enabled_groups = updated
            return True
