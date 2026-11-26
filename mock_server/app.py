"""
本地迷你电商后端靶场（零第三方依赖，仅用 Python 标准库 + SQLite）
提供接口：
  - GET    /api/v1/health            健康检查
  - POST   /api/v1/login             用户登录（返回 Bearer Token）
  - GET    /api/v1/products          查询商品列表（需鉴权）
  - POST   /api/v1/orders            创建订单（需鉴权，扣减库存并写入 SQLite）
  - GET    /api/v1/orders/{order_id} 查询订单详情（需鉴权）
  - DELETE /api/v1/orders/{order_id} 取消/删除订单（需鉴权，恢复库存）

单独运行方式：python mock_server/app.py
"""
import hashlib
import hmac
import json
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DB_PATH = Path(__file__).resolve().parent / "shop.db"
SIGN_SECRET = "shop-hmac-secret-2026"

# 内存 Token 存储：{token: {"username": ..., "expire_at": ...}}
TOKENS: dict[str, dict] = {}
DB_LOCK = threading.Lock()


def init_db():
    """初始化 SQLite 数据库与默认测试数据"""
    with DB_LOCK:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                stock INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                total_amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'CREATED',
                created_at INTEGER NOT NULL
            )
            """
        )

        # 初始化默认用户（tester / Password123，以及一个被冻结账号 locked_user）
        default_users = [
            ("tester", _hash_pwd("Password123"), "active"),
            ("locked_user", _hash_pwd("Password123"), "locked"),
        ]
        for u, p, st in default_users:
            cur.execute(
                "INSERT OR IGNORE INTO users (username, password_hash, status) VALUES (?, ?, ?)",
                (u, p, st),
            )

        # 初始化默认商品
        cur.execute("SELECT COUNT(*) FROM products")
        if cur.fetchone()[0] == 0:
            cur.executemany(
                "INSERT INTO products (name, price, stock) VALUES (?, ?, ?)",
                [
                    ("机械键盘 Pro", 399.0, 50),
                    ("人体工学鼠标", 199.5, 100),
                    ("限量版显示器", 2999.0, 2),
                ],
            )
        conn.commit()
        conn.close()


def _hash_pwd(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ShopHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 关闭标准库自带的刷屏访问日志，让 pytest 输出更干净
        return

    def _send_json(self, status_code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _authenticate(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._send_json(401, {"code": 40101, "message": "未提供有效 Token", "data": None})
            return None
        token = auth.removeprefix("Bearer ").strip()
        info = TOKENS.get(token)
        if not info or info["expire_at"] < time.time():
            self._send_json(401, {"code": 40102, "message": "Token 已失效或过期", "data": None})
            return None
        return info["username"]

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/v1/health":
            return self._send_json(200, {"code": 0, "message": "ok", "data": {"status": "healthy"}})

        if path == "/api/v1/products":
            if not self._authenticate():
                return
            with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT id, name, price, stock FROM products ORDER BY id").fetchall()
                products = [dict(r) for r in rows]
            return self._send_json(200, {"code": 0, "message": "success", "data": {"items": products}})

        if path.startswith("/api/v1/orders/"):
            username = self._authenticate()
            if not username:
                return
            order_id = path.split("/")[-1]
            with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM orders WHERE order_id = ? AND username = ?",
                    (order_id, username),
                ).fetchone()
            if not row:
                return self._send_json(404, {"code": 40401, "message": "订单不存在", "data": None})
            return self._send_json(200, {"code": 0, "message": "success", "data": dict(row)})

        return self._send_json(404, {"code": 40400, "message": f"路由不存在: {path}", "data": None})

    def do_POST(self):
        path = urlparse(self.path).path
        data = self._read_json()

        if path == "/api/v1/login":
            username = str(data.get("username", "")).strip()
            password = str(data.get("password", ""))
            if not username or not password:
                return self._send_json(400, {"code": 40001, "message": "用户名和密码不能为空", "data": None})

            with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                user = conn.execute(
                    "SELECT username, password_hash, status FROM users WHERE username = ?",
                    (username,),
                ).fetchone()

            if not user or user["password_hash"] != _hash_pwd(password):
                return self._send_json(401, {"code": 40100, "message": "用户名或密码错误", "data": None})
            if user["status"] != "active":
                return self._send_json(403, {"code": 40301, "message": "账号已被冻结", "data": None})

            token = f"tok_{uuid.uuid4().hex}"
            TOKENS[token] = {"username": username, "expire_at": time.time() + 3600}
            return self._send_json(
                200,
                {"code": 0, "message": "登录成功", "data": {"token": token, "username": username}},
            )

        if path == "/api/v1/auth/expire":
            auth = self.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip()
            if token in TOKENS:
                TOKENS[token]["expire_at"] = time.time() - 10
            return self._send_json(200, {"code": 0, "message": "Token已置为过期", "data": None})

        if path == "/api/v1/orders/secure":
            username = self._authenticate()
            if not username:
                return
            ts = self.headers.get("X-Timestamp", "")
            sign = self.headers.get("X-Sign", "")
            canonical_body = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            raw_str = f"POST:{path}:{ts}:{canonical_body}"
            expected_sign = hmac.new(
                SIGN_SECRET.encode("utf-8"),
                raw_str.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not ts or not sign or not hmac.compare_digest(sign, expected_sign):
                return self._send_json(403, {"code": 40302, "message": "接口签名校验失败", "data": None})
            return self._send_json(
                200,
                {"code": 0, "message": "安全验签通过", "data": {"username": username, "verified": True}},
            )

        if path == "/api/v1/orders":
            username = self._authenticate()
            if not username:
                return
            product_id = data.get("product_id")
            quantity = data.get("quantity")
            if not isinstance(product_id, int) or not isinstance(quantity, int) or quantity <= 0:
                return self._send_json(400, {"code": 40002, "message": "商品ID或购买数量不合法", "data": None})

            with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                product = conn.execute(
                    "SELECT id, name, price, stock FROM products WHERE id = ?",
                    (product_id,),
                ).fetchone()
                if not product:
                    return self._send_json(404, {"code": 40402, "message": "商品不存在", "data": None})
                if product["stock"] < quantity:
                    return self._send_json(409, {"code": 40901, "message": "商品库存不足", "data": None})

                order_id = f"ORD{uuid.uuid4().hex[:10].upper()}"
                total_amount = round(product["price"] * quantity, 2)
                conn.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ?",
                    (quantity, product_id),
                )
                conn.execute(
                    """
                    INSERT INTO orders (order_id, username, product_id, quantity, total_amount, status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'CREATED', ?)
                    """,
                    (order_id, username, product_id, quantity, total_amount, int(time.time())),
                )
                conn.commit()

            return self._send_json(
                201,
                {
                    "code": 0,
                    "message": "下单成功",
                    "data": {
                        "order_id": order_id,
                        "product_id": product_id,
                        "quantity": quantity,
                        "total_amount": total_amount,
                        "status": "CREATED",
                    },
                },
            )

        return self._send_json(404, {"code": 40400, "message": f"路由不存在: {path}", "data": None})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/v1/orders/"):
            username = self._authenticate()
            if not username:
                return
            order_id = path.split("/")[-1]
            with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                order = conn.execute(
                    "SELECT * FROM orders WHERE order_id = ? AND username = ?",
                    (order_id, username),
                ).fetchone()
                if not order:
                    return self._send_json(404, {"code": 40401, "message": "订单不存在", "data": None})
                # 删除订单并归还库存（模拟取消订单/清理测试数据）
                conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (order["quantity"], order["product_id"]))
                conn.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
                conn.commit()
            return self._send_json(200, {"code": 0, "message": "订单已取消", "data": {"order_id": order_id}})

        return self._send_json(404, {"code": 40400, "message": f"路由不存在: {path}", "data": None})


def start_server(host: str = "127.0.0.1", port: int = 8899) -> ThreadingHTTPServer:
    init_db()
    server = ThreadingHTTPServer((host, port), ShopHandler)
    return server


if __name__ == "__main__":
    srv = start_server()
    print("🚀 本地电商靶场已启动: http://127.0.0.1:8899")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n靶场已关闭")
        srv.server_close()
