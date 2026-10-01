"""消息识别、群名构造和按群冷却。"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable


# 游戏房间号只接受 ASCII 数字，避免 Unicode 数字绕过精确匹配的忽略列表。
DIGIT_PATTERN = re.compile(r"^[0-9]{5}$")
# 旧群名继续清理所有连续五位及以上数字，包括旧版可能写入的全角数字。
OLD_NUMBER_PATTERN = re.compile(r"\d{5,}")


# ================================ 消息识别 ================================ #


def classify_message(message: str, ignored: list[str]) -> str | None:
    """返回五位车牌或清空标记；其他文本不触发改名。"""
    message = message.strip()
    if message == "清空":
        return "clear"
    if DIGIT_PATTERN.fullmatch(message) and message not in ignored:
        return message
    return None


def message_trigger(segments: Iterable[tuple[str, str]], ignored: list[str]) -> str | None:
    """仅识别单段连续文本，允许前后存在 @、图片或回复。"""
    runs: list[str] = []
    current: list[str] = []
    for segment_type, content in segments:
        if segment_type == "text":
            current.append(content)
        elif current:
            runs.append("".join(current).strip())
            current.clear()
    if current:
        runs.append("".join(current).strip())

    # 非文本段夹在两段数字中间时，不能跨段拼成车牌。
    nonempty_runs = [run for run in runs if run]
    return classify_message(nonempty_runs[0], ignored) if len(nonempty_runs) == 1 else None


# ================================ 群名构造 ================================ #


def build_group_name(current_name: str, prefix: str | None, max_length: int) -> str:
    """清理旧数字，新增车牌时与原群名之间留一个空格。"""
    pure_name = OLD_NUMBER_PATTERN.sub("", current_name).strip()
    target = pure_name if prefix is None else f"{prefix} {pure_name}" if pure_name else prefix
    return target[:max_length].rstrip() if len(target) > max_length else target


class GroupCooldown:
    """按群记录操作尝试；失败请求也进入冷却。"""

    def __init__(self, seconds: float = 1):
        self.seconds = seconds
        self.last_by_group: dict[str, float] = {}

    def allow(self, group_id: str) -> bool:
        """检查冷却并登记本次操作；由调用者在同群锁内调用。"""
        now = time.monotonic()
        if now - self.last_by_group.get(group_id, float("-inf")) < self.seconds:
            return False
        self.last_by_group[group_id] = now
        return True

    def cancel_noop(self, group_id: str) -> None:
        """当前群无需提交改名时撤销本次登记；调用者须持有同群锁。"""
        self.last_by_group.pop(group_id, None)
