"""独立插件的 JSON 配置项与加载逻辑。"""

from pathlib import Path

from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Config(BaseModel):
    """校验改群名参数；使用独立文件，避免依赖宿主 Bot 的配置格式。"""

    model_config = ConfigDict(extra="forbid")

    # 至少容纳完整五位车牌，防止长度配置把有效车牌截断成无效群名前缀。
    group_rename_max_length: int = Field(default=30, ge=5)
    group_rename_enable_notify: bool = True
    group_rename_admin_only: bool = False
    group_rename_ignore_patterns: list[str] = Field(default_factory=list)
    group_rename_cooldown_seconds: float = Field(default=1, ge=0)


# ================================ JSON 配置加载 ================================ #


def load_config(path: Path) -> Config:
    """从 localstore 配置文件加载参数；无文件时使用默认值，有错时阻止插件加载。"""
    if not path.exists():
        logger.info(f"改群名使用默认配置；可在 {path} 创建 JSON 文件自定义参数")
        return Config()

    try:
        config = Config.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise RuntimeError(f"读取改群名配置文件 {path} 失败: {exc}") from exc

    logger.info(f"改群名已读取配置文件: {path}")
    return config
