"""YAML 测试数据读取工具"""
from pathlib import Path
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent


def load_yaml(relative_path: str):
    file_path = BASE_DIR / relative_path
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
