# StallSpan 市集摊档开间

沿街段一维 First-Fit 开间分配，挡柱不可被摊位跨越，输出分配图与放不下清单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4700 |
| API | http://localhost:9700 |
| API 文档 | http://localhost:9700/docs |
| Postgres | localhost:5448 |

健康检查：`GET http://localhost:9700/api/health`

## 使用说明

1. 在「集日」「街段」确认开市日与可用宽度。
2. 在「摊主」「挡柱」维护需求宽度与障碍位置。
3. 打开「分配图」执行一维开间分配。
4. 在「放不下」查看无法安置的摊位。

## 摊宽 × 优先级 交叉规则

摊主优先级为 1~9 的整数，摊宽与街宽均须大于 0；摊宽随优先级设上限：

| 优先级 | 摊宽上限 |
| --- | --- |
| 1 ~ 3 | 4 m |
| 4 ~ 6 | 6 m |
| 7 ~ 9 | 8 m |

- 合法边：优先级 3、摊宽 4.0 可过；优先级 3、摊宽 4.1 拒绝。
- 应用层（接口 + ORM 事件）与数据库层（CHECK 约束）是同一套规则，任一层都拦；
  绕过接口直接写库同样失败。
- 新建与改写同拒；改写被拒时整笔回滚、停在改前，不会产生半成功写入，
  也不会清掉历史开间运行或让主图已落色块消失。
- 非法改宽报的是「摊宽」规则错误，不会记成一次分配成功，也不会写成「空档不够」。
- 改优先后再保存，按提交瞬间的新优先级与摊宽重新交叉判定。
- 接口错误体统一为 `{"field", "field_label", "message"}`，页面提示与接口点名字段同一叫法。

摊主写入接口：`POST /api/vendors`（新建）、`PUT /api/vendors/{id}`（改写）；
街段：`POST /api/segments`、`PUT /api/segments/{id}`（街宽须大于 0）。

## 开发与测试

```bash
docker compose exec api pytest -q
```

测试分文件：`test_vendor_rules.py`（纯规则边界）、
`test_vendor_api_validation.py`（接口拒绝）、
`test_direct_insert_rejected.py`（绕过接口直插/裸 SQL 必败与旧库迁移）。
