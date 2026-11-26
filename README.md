# 企业级 Python 接口自动化测试框架实战（项目一）

## 1. 快速运行

在当前项目目录下执行：

```bash
# 运行全量测试，并在 reports/report.html 生成单文件可视化报告
pytest

# 只运行核心 P0 冒烟用例
pytest -m smoke

# 只运行反向异常用例
pytest -m negative

# 生成 Allure 报告原始数据（若本机已装 allure CLI，可用 allure serve 查看）
pytest --alluredir=reports/allure-results
```

## 2. 项目分层设计（面试必讲架构）

- `mock_server/app.py`：本地迷你电商后端靶场（登录鉴权、商品、下单、查单、取消订单 + SQLite 数据库）。
- `config/`：多环境配置分离（通过 `TEST_ENV` 切换环境）。
- `core/`：框架底层能力封装
  - `http_client.py`：`requests.Session` 封装、统一日志、自动重试、Token 管理、Allure 附件。
  - `db_client.py`：数据库落库断言与清理封装。
  - `extractor.py`：上下游响应变量提取 + `${var}` 占位符渲染引擎。
- `data/`：YAML 数据驱动文件（测试数据与脚本代码完全解耦）。
- `testcases/`：
  - `conftest.py`：全局 Fixture（自动拉起靶场、`session` 级单次登录复用 Token、DB 连接）。
  - `test_login.py`：参数化登录测试 + `jsonschema` 契约校验 + SLA 耗时断言。
  - `test_order_flow.py`：端到端下单全链路 + 数据库库存断言 + `try...finally` 脏数据清理。
- `.github/workflows/api-tests.yml`：GitHub Actions CI/CD 流水线（支持 Push/PR 自动触发、每日定时巡检、手动按标签触发、失败自动上传报告与 Webhook 告警）。
