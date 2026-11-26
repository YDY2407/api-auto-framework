"""
Locust 接口性能压测脚本（纯 Python 编写，可直接模拟高并发用户访问）
运行方式：
  1. 先启动本地靶场：python mock_server/app.py
  2. 无头模式压测（20并发用户，每秒递增5个，持续10秒，生成HTML压测报告）：
     locust -f performance/locustfile.py --host=http://127.0.0.1:8899 --headless -u 20 -r 5 -t 10s --html=reports/perf_report.html
  3. Web UI 模式（浏览器打开 http://localhost:8089 实时看 QPS 曲线图）：
     locust -f performance/locustfile.py --host=http://127.0.0.1:8899
"""
from locust import HttpUser, between, task


class ShopPerformanceUser(HttpUser):
    # 模拟真实用户思考时间（0.1~0.5秒）
    wait_time = between(0.1, 0.5)

    def on_start(self):
        """每个虚拟用户上线时先登录一次，获取独立 Bearer Token"""
        self.client.trust_env = False
        resp = self.client.post(
            "/api/v1/login",
            json={"username": "tester", "password": "Password123"},
            name="/api/v1/login",
        )
        if resp.status_code == 200:
            token = resp.json()["data"]["token"]
            self.headers = {"Authorization": f"Bearer {token}"}
        else:
            self.headers = {}

    @task(3)
    def browse_products(self):
        """高频场景（权重 3）：浏览商品列表"""
        with self.client.get("/api/v1/products", headers=self.headers, name="/api/v1/products", catch_response=True) as resp:
            if resp.status_code != 200 or resp.json().get("code") != 0:
                resp.failure(f"商品列表查询异常: {resp.status_code} {resp.text}")

    @task(1)
    def create_and_cancel_order(self):
        """低频核心链路（权重 1）：下单 + 立即取消（避免压测耗尽库存和留脏数据）"""
        with self.client.post(
            "/api/v1/orders",
            headers=self.headers,
            json={"product_id": 2, "quantity": 1},
            name="/api/v1/orders [POST]",
            catch_response=True,
        ) as resp:
            if resp.status_code != 201:
                resp.failure(f"下单失败: {resp.status_code} {resp.text}")
                return
            order_id = resp.json()["data"]["order_id"]

        # 立即归还库存
        self.client.delete(
            f"/api/v1/orders/{order_id}",
            headers=self.headers,
            name="/api/v1/orders/{id} [DELETE]",
        )
