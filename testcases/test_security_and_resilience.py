"""
企业级深水区场景测试：
1. 接口加密签名（HMAC-SHA256 自动签名 & 篡改签名拦截）
2. Token 过期（40102）无感自动刷新与请求重试
"""
import allure
import pytest
from config.settings import SETTINGS
from core.http_client import HttpClient


@allure.feature("安全验签与高可用机制")
class TestSecurityAndResilience:
    @pytest.mark.smoke
    def test_secure_order_with_valid_hmac_sign(self, authed_client):
        allure.dynamic.title("SEC_001 - 开启 HMAC-SHA256 自动签名请求验签通过")
        resp = authed_client.request(
            "POST",
            "/api/v1/orders/secure",
            sign=True,
            json={"product_id": 1, "quantity": 1},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["verified"] is True

    @pytest.mark.negative
    def test_secure_order_with_tampered_sign_rejected(self, authed_client):
        allure.dynamic.title("SEC_002 - 篡改签名请求被服务端 403 拦截")
        resp = authed_client.request(
            "POST",
            "/api/v1/orders/secure",
            sign=False,
            headers={"X-Timestamp": "1700000000", "X-Sign": "fake_tampered_sign"},
            json={"product_id": 1, "quantity": 1},
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == 40302

    @pytest.mark.smoke
    def test_token_expired_auto_refresh(self, mock_backend_server):
        allure.dynamic.title("AUTH_002 - Token 过期后框架自动刷新并无感重试成功")
        refresh_count = {"n": 0}

        def _refresh() -> str:
            refresh_count["n"] += 1
            temp = HttpClient(SETTINGS["base_url"], timeout=SETTINGS["timeout"])
            try:
                r = temp.request("POST", "/api/v1/login", json=SETTINGS["test_account"])
                return r.json()["data"]["token"]
            finally:
                temp.close()

        client = HttpClient(SETTINGS["base_url"], timeout=SETTINGS["timeout"], token_refresher=_refresh)
        try:
            old_token = _refresh()
            client.set_token(old_token)

            # 1. 主动把当前 Token 置为过期
            exp_resp = client.request("POST", "/api/v1/auth/expire")
            assert exp_resp.status_code == 200

            # 2. 直接访问受保护接口 -> 框架应捕获 40102、自动重新登录并重试成功返回 200
            prod_resp = client.request("GET", "/api/v1/products")
            assert prod_resp.status_code == 200
            assert refresh_count["n"] == 2, "应触发一次自动刷新 Token"
        finally:
            client.close()
