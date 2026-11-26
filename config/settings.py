"""
全局配置加载模块
支持通过环境变量 TEST_ENV 切换多环境（例如：TEST_ENV=test pytest）
"""
import os
from pathlib import Path
import yaml

# 项目根目录：e:\工作记录\AI大人\AI老师教我\api-auto-framework
BASE_DIR = Path(__file__).resolve().parent.parent


def load_settings() -> dict:
    env = os.getenv("TEST_ENV", "test")
    config_file = BASE_DIR / "config" / f"env_{env}.yaml"
    if not config_file.exists():
        raise FileNotFoundError(f"找不到环境配置文件: {config_file}")

    with open(config_file, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # 把相对路径转成绝对路径，避免在不同目录运行 pytest 时找不到数据库
    cfg["db_full_path"] = str(BASE_DIR / cfg["db_path"])
    return cfg


SETTINGS = load_settings()
