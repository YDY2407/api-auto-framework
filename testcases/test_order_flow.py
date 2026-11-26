"""
订单核心业务全链路测试
演示知识点：
1. 上下游接口参数关联（查商品 -> 提取 product_id -> 下单 -> 提取 order_id -> ${order_id} 查订单）
2. 数据库落库断言（查 SQLite 确认订单记录、总金额、库存扣减全部正确）
3. 测试后置脏数据清理（try...finally 保证无论用例成败都会清理订单并归还库存）
4. 反向异常与未鉴权 401 测试
"""
import allure
import pytest
from utils.yaml_loader import load_yaml

ORDER_NEG_CASES = load_yaml("data/order_cases.yaml")


@allure.feature("订单核心链路")
class TestOrderFlow:
    @pytest.mark.smoke
    def test_order_full_lifecycle(self, authed_client, db, var_pool):
        allure.dynamic.title("ORDER_001 - 查商品 -> 下单 -> 查订单 -> 数据库落库断言 -> 取消清理")

        # 1. 查询商品列表，提取第 1 个商品的 ID 和当前库存
        with allure.step("1. 查询商品列表并提取商品信息"):
            prod_resp = authed_client.request("GET", "/api/v1/products")
            assert prod_resp.status_code == 200
            prod_body = prod_resp.json()
            product_id = var_pool.extract(prod_body, "product_id", "data.items.0.id")
            unit_price = var_pool.extract(prod_body, "unit_price", "data.items.0.price")
            stock_before = var_pool.extract(prod_body, "stock_before", "data.items.0.stock")

        buy_qty = 2
        order_id = None
        try:
            # 2. 创建订单
            with allure.step("2. 提交订单并提取 order_id"):
                create_resp = authed_client.request(
                    "POST",
                    "/api/v1/orders",
                    json={"product_id": product_id, "quantity": buy_qty},
                )
                assert create_resp.status_code == 201
                create_body = create_resp.json()
                order_id = var_pool.extract(create_body, "order_id", "data.order_id")
                assert create_body["data"]["total_amount"] == round(unit_price * buy_qty, 2)

            # 3. 使用 ${order_id} 占位符渲染 URL，查询订单详情
            with allure.step("3. 通过动态变量查询订单详情"):
                detail_path = var_pool.render("/api/v1/orders/${order_id}")
                detail_resp = authed_client.request("GET", detail_path)
                assert detail_resp.status_code == 200
                assert detail_resp.json()["data"]["status"] == "CREATED"

            # 4. 数据库落库断言（防止接口“假成功”）
            with allure.step("4. 数据库断言：校验订单表落库与商品库存扣减"):
                db_order = db.fetch_one("SELECT * FROM orders WHERE order_id = ?", (order_id,))
                assert db_order is not None, "数据库未查到新建订单"
                assert db_order["quantity"] == buy_qty
                assert db_order["total_amount"] == round(unit_price * buy_qty, 2)

                db_product = db.fetch_one("SELECT stock FROM products WHERE id = ?", (product_id,))
                assert db_product["stock"] == stock_before - buy_qty, "商品库存未正确扣减"

        finally:
            # 5. 谁污染谁治理：无论断言成败，都取消订单清理脏数据并验证库存归还
            if order_id:
                with allure.step("5. 后置清理：取消订单并验证库存恢复"):
                    del_path = var_pool.render("/api/v1/orders/${order_id}")
                    del_resp = authed_client.request("DELETE", del_path)
                    assert del_resp.status_code == 200

                    db_order_after = db.fetch_one("SELECT * FROM orders WHERE order_id = ?", (order_id,))
                    assert db_order_after is None, "脏数据订单未清理干净"
                    db_product_after = db.fetch_one("SELECT stock FROM products WHERE id = ?", (product_id,))
                    assert db_product_after["stock"] == stock_before, "取消订单后库存未归还"

    @pytest.mark.negative
    @pytest.mark.parametrize("case", ORDER_NEG_CASES, ids=[c["title"] for c in ORDER_NEG_CASES])
    def test_create_order_negative(self, authed_client, case):
        allure.dynamic.title(f"{case['case_id']} - {case['title']}")
        resp = authed_client.request("POST", "/api/v1/orders", json=case["payload"])
        assert resp.status_code == case["expected"]["status_code"]
        assert resp.json()["code"] == case["expected"]["biz_code"]

    @pytest.mark.negative
    def test_products_without_token_returns_401(self, raw_client):
        allure.dynamic.title("AUTH_001 - 未携带 Token 访问受保护接口返回 401")
        resp = raw_client.request("GET", "/api/v1/products")
        assert resp.status_code == 401
        assert resp.json()["code"] == 40101
