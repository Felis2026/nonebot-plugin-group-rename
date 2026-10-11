"""通过 NoneBot 标准入口合并宿主配置与独立 JSON 参数。"""

import json
from pathlib import Path
from typing import Any

from nonebot import logger
from nonebot.compat import model_dump, model_fields, type_validate_python
import nonebot_plugin_localstore as localstore
from pydantic import BaseModel, Field


class _ConfigValues(BaseModel):
    """共用参数定义，校验 JSON 时不触发宿主配置合并。"""

    # 至少容纳完整五位车牌，防止长度配置把有效车牌截断成无效群名前缀。
    group_rename_max_length: int = Field(default=30, ge=5)
    group_rename_enable_notify: bool = True
    group_rename_admin_only: bool = False
    group_rename_ignore_patterns: list[str] = Field(default_factory=list)
    group_rename_cooldown_seconds: float = Field(default=1, ge=0)
    group_rename_priority: int = Field(default=1, ge=0)


# 由 localstore 识别当前插件，遵守宿主为本插件指定的配置目录；只获取一次。
CONFIG_FILE = localstore.get_plugin_config_dir() / "config.json"
_CONFIG_KEYS = {field.name for field in model_fields(_ConfigValues)}


# ================================ JSON 配置加载 ================================ #


def _load_json_config(path: Path) -> dict[str, Any]:
    """校验独立 JSON 并返回显式填写项；文件错误时阻止插件加载。"""
    if not path.exists():
        logger.info(f"改群名未配置 JSON；可在 {path} 创建文件自定义参数")
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON 配置必须是对象")
        unknown_keys = data.keys() - _CONFIG_KEYS
        if unknown_keys:
            raise ValueError(f"未知配置项: {', '.join(sorted(unknown_keys))}")
        # 宿主配置允许携带其他插件参数，只有独立 JSON 严格检查未知字段。
        # 合并前校验，避免错误的 JSON 值被宿主覆盖后悄悄隐藏。
        values = type_validate_python(_ConfigValues, data)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"读取改群名配置文件 {path} 失败: {exc}") from exc

    logger.info(f"改群名已读取配置文件: {path}")
    # 默认值留到最终模型填充，避免 JSON 未填写项覆盖宿主配置。
    return model_dump(values, exclude_unset=True)


# ================================ 标准配置合并 ================================ #


class Config(_ConfigValues):
    """供 get_plugin_config 使用；宿主显式配置优先于 JSON，其次为默认值。"""

    def __init__(self, **data: Any) -> None:
        """在模型初始化时合并 JSON，兼容 Pydantic v1 与 v2 的标准加载入口。"""
        json_data = _load_json_config(CONFIG_FILE)
        host_data = {key: value for key, value in data.items() if key in _CONFIG_KEYS}
        super().__init__(**{**json_data, **host_data})
