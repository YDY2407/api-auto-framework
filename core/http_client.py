"""
核心 HTTP 客户端封装（企业级 V2）
核心能力：
1. 复用 requests.Session()（连接池复用 + 公共 Header 管理）
2. 网关抖动（502/503/504）底层自动重试
3. HMAC-SHA256 接口签名自动计算与注入（sign=True）
4. Token 过期（401 + code=40102）自动回调刷新 Token 并无感重试 1 次（防死循环）
5. 结构化日志 + Allure 请求/响应附件自动挂载
"""
import hashlib
import hmac
import json
import logging
import time
from typing import Callable
import allure
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class HttpClient:
    def __init__(
        self,
        base_url: str,
        timeout: int = 5,
        sign_secret: str = "shop-hmac-secret-2026",
        token_refresher: Callable[[], str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.sign_secret = sign_secret
        self.token_refresher = token_refresher

        self.session = requests.Session()
        self.session.trust_env = False

        retry = Retry(total=2, backoff_factor=0.3, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def set_token(self, token: str):
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def clear_token(self):
        self.session.headers.pop("Authorization", None)

    def _build_sign_headers(self, method: str, path: str, body: dict | None) -> dict[str, str]:
        """计算 HMAC-SHA256 接口签名请求头"""
        ts = str(int(time.time()))
        canonical_body = json.dumps(body or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        raw_str = f"{method.upper()}:{path}:{ts}:{canonical_body}"
        sign = hmac.new(
            self.sign_secret.encode("utf-8"),
            raw_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {"X-Timestamp": ts, "X-Sign": sign}

    def request(
        self,
        method: str,
        path: str,
        sign: bool = False,
        _retried_auth: bool = False,
        **kwargs,
    ) -> requests.Response:
        norm_path = "/" + path.lstrip("/")
        url = f"{self.base_url}{norm_path}"
        kwargs.setdefault("timeout", self.timeout)

        # 按需自动注入 HMAC-SHA256 签名请求头
        if sign:
            headers = dict(kwargs.get("headers") or {})
            headers.update(self._build_sign_headers(method, norm_path, kwargs.get("json")))
            kwargs["headers"] = headers

        logger.info(f"➡️  [{method.upper()}] {url} | sign={sign} | kwargs={kwargs}")
        resp = self.session.request(method=method, url=url, **kwargs)
        elapsed = resp.elapsed.total_seconds()
        logger.info(f"⬅️  [{resp.status_code}] ({elapsed:.3f}s) | body={resp.text[:300]}")

        # Token 过期自动刷新并重试 1 次（防止死循环）
        if resp.status_code == 401 and not _retried_auth and self.token_refresher:
            try:
                biz_code = resp.json().get("code")
            except ValueError:
                biz_code = None
            if biz_code == 40102:
                logger.warning("🔄 检测到 Token 已过期 (40102)，正在自动刷新 Token 并重试...")
                new_token = self.token_refresher()
                self.set_token(new_token)
                return self.request(method, path, sign=sign, _retried_auth=True, **kwargs)

        allure.attach(
            json.dumps({"method": method.upper(), "url": url, "kwargs": kwargs}, ensure_ascii=False, indent=2, default=str),
            name="请求详情",
            attachment_type=allure.attachment_type.JSON,
        )
        allure.attach(
            resp.text,
            name=f"响应报文 ({resp.status_code})",
            attachment_type=allure.attachment_type.JSON,
        )
        return resp

    def close(self):
        self.session.close()
