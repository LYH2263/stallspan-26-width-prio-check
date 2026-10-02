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

1. 在「集日」「街段」确认开市日与可用宽度（街宽必须 > 0）。
2. 在「摊主」维护需求宽度与优先级：新增或改写都会即时校验，被拒时页面停在改前值。
3. 打开「分配图」执行一维开间分配。
4. 在「放不下」查看无法安置的摊位。

## 摊主优先级 × 摊宽规则

| 优先级 | 摊宽上限 |
| --- | --- |
| 1-3 | 4 m |
| 4-6 | 6 m |
| 7-9 | 8 m |

另：优先级必须是 1-9 的整数，摊宽 > 0，街宽 > 0。合法边界优先 3 / 摊宽 4.0 可过，4.1 拒。

规则只有一份来源 `backend/app/services/rules.py`：应用层（`POST/PUT /api/vendors`、`POST /api/segments`）与数据库 `CHECK` 约束（`ck_vendors_priority_width`、`ck_segments_width_positive`）同源——绕过接口直插违规数据同样被库拒绝并整笔回滚。改写摊主只在成功时提交，失败不产生半成功写入，也不清 `allocation_runs` 历史开间与主图已落色块；校验按提交瞬间的优先级×摊宽重检，不读改前缓存。旧库启动时幂等迁移（违规老数据按档归一化后补约束，历史运行整表不碰）。

接口拒绝时返回 `422 {"detail":{"field":...,"message":...}}`，`field` 与摊主页提示同一叫法（`stall_width_m` / `priority` / `width_m`）；这是规则拒绝，与分配结果里的“无连续空档可放下”原因严格区分。

## 开发与测试

```bash
docker compose exec api pytest -q
```
