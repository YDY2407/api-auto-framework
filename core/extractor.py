"""
动态变量提取与 ${var} 占位符替换引擎（解决上下游接口参数依赖的核心组件）
示例：
  extractor.extract(resp.json(), "order_id", "data.order_id")
  path = extractor.render("/api/v1/orders/${order_id}")  -> "/api/v1/orders/ORD123456"
"""
import re
from typing import Any


class VariablePool:
    def __init__(self):
        self._vars: dict[str, Any] = {}

    def set(self, key: str, value: Any):
        self._vars[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._vars.get(key, default)

    def extract(self, data: dict, var_name: str, dot_path: str) -> Any:
        """按点路径（如 'data.order_id' 或 'data.items.0.id'）提取响应字段并存入变量池"""
        current: Any = data
        for part in dot_path.split("."):
            if isinstance(current, list):
                current = current[int(part)]
            elif isinstance(current, dict):
                current = current[part]
            else:
                raise KeyError(f"无法从 {dot_path} 提取字段，卡在: {part}")
        self._vars[var_name] = current
        return current

    def render(self, text: str) -> str:
        """把字符串里的 ${var_name} 替换为变量池中的真实值"""
        def _replace(match: re.Match) -> str:
            key = match.group(1)
            if key not in self._vars:
                raise KeyError(f"变量池中未找到占位符变量: ${{{key}}}")
            return str(self._vars[key])

        return re.sub(r"\$\{(\w+)\}", _replace, text)
