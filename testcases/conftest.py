"""
全局 Fixture 与 Hook 仓库（已彻底解决 pytest-xdist 多进程并发生命周期问题！）
"""
import logging
import sys
import threading
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import SETTINGS
from core.db_client import DBClient
from core.extractor import VariablePool
from core.http_client import HttpClient
from mock_server.app import start_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

_SERVER = None


def pytest_configure(config):
    """
    企业级 pytest-xdist 并发避坑实践：
    只有主控进程(controller)不存在 workerinput 属性。
    在主控进程统一启动一次测试靶场，避免 worker 各自抢端口或某个 worker 跑完提前关闭服务导致其他 worker 断连！
    """
    global _SERVER
    if not hasattr(config, "workerinput"):
        _SERVER = start_server("127.0.0.1", 8899)
        thread = threading.Thread(target=_SERVER.serve_forever, daemon=True)
        thread.start()


def pytest_unconfigure(config):
    """等所有 worker 全部结束后，再由主控进程统一优雅关闭靶场"""
    global _SERVER
    if not hasattr(config, "workerinput") and _SERVER is not None:
        _SERVER.shutdown()
        _SERVER.server_close()
        _SERVER = None


@pytest.fixture(scope="session")
def mock_backend_server():
    """占位夹具，保持与用例签名兼容（服务生命周期已由主控进程 Hook 统一托管）"""
    return SETTINGS["base_url"]


@pytest.fixture(scope="function")
def raw_client():
    """未登录的干净 HTTP 客户端"""
    client = HttpClient(SETTINGS["base_url"], timeout=SETTINGS["timeout"])
    yield client
    client.close()


@pytest.fixture(scope="session")
def authed_client(mock_backend_server):
    """
    全局已登录客户端（带 Token 过期自动刷新回调）：
    即使测试过程中 Token 过期（40102），也能无感重新登录并重试请求。
    """
    def _fetch_token() -> str:
        temp = HttpClient(SETTINGS["base_url"], timeout=SETTINGS["timeout"])
        try:
            resp = temp.request("POST", "/api/v1/login", json=SETTINGS["test_account"])
            assert resp.status_code == 200, f"登录获取 Token 失败: {resp.text}"
            return resp.json()["data"]["token"]
        finally:
            temp.close()

    client = HttpClient(
        SETTINGS["base_url"],
        timeout=SETTINGS["timeout"],
        token_refresher=_fetch_token,
    )
    client.set_token(_fetch_token())
    yield client
    client.close()


@pytest.fixture(scope="session")
def db():
    return DBClient(SETTINGS["db_full_path"])


@pytest.fixture(scope="function")
def var_pool():
    return VariablePool()
