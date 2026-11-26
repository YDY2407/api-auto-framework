"""
用户认证模块接口测试
演示知识点：
1. YAML 数据驱动 + @pytest.mark.parametrize
2. 多层断言：HTTP状态码 + 业务码 + JSONSchema 契约校验 + 响应时间断言
"""
import allure
import pytest
from jsonschema import validate
from utils.yaml_loader import load_yaml

LOGIN_CASES = load_yaml("data/login_cases.yaml")

# 登录成功响应的 JSONSchema 契约（确保开发没把字段类型或必填项改坏）
LOGIN_SUCCESS_SCHEMA = {
    "type": "object",
    "required": ["code", "message", "data"],
    "properties": {
        "code": {"type": "integer"},
        "message": {"type": "string"},
        "data": {
            "type": "object",
            "required": ["token", "username"],
            "properties": {
                "token": {"type": "string", "minLength": 10},
                "username": {"type": "string"},
            },
        },
    },
}


@allure.feature("用户认证模块")
class TestLogin:
    @pytest.mark.smoke
    @pytest.mark.parametrize("case", LOGIN_CASES, ids=[c["title"] for c in LOGIN_CASES])
    def test_login(self, raw_client, case):
        allure.dynamic.title(f"{case['case_id']} - {case['title']}")

        with allure.step("1. 发送登录请求"):
            resp = raw_client.request("POST", "/api/v1/login", json=case["payload"])

        with allure.step("2. 校验状态码、响应耗时与业务码"):
            assert resp.status_code == case["expected"]["status_code"]
            assert resp.elapsed.total_seconds() < 1.0, "接口响应超过 1 秒 SLA"
            body = resp.json()
            assert body["code"] == case["expected"]["biz_code"]

        if case["expected"]["has_token"]:
            with allure.step("3. 校验登录成功响应 JSONSchema 契约"):
                validate(instance=body, schema=LOGIN_SUCCESS_SCHEMA)
