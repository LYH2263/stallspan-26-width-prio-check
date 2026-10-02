"""启动期幂等迁移：为旧库补齐 摊宽×优先级 同一套 CHECK 约束。

- PostgreSQL：约束缺失则 ALTER TABLE ... ADD CONSTRAINT（CHECK 不支持 IF NOT EXISTS）。
- SQLite：不支持 ADD CONSTRAINT，缺约束时整表重建（仅本项目两张无索引/触发器的表）。
- 上约束前先把历史违规行收敛到合法上限（旧种子里 p9/12m 这类演示数据），
  保证旧卷启动后仍能起服分配；allocation_runs 历史开间运行一律不触碰。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.vendor_rules import SEGMENT_CHECK_SQL, VENDOR_CHECK_SQL

VENDOR_CK = "ck_vendors_priority_width"
SEGMENT_CK = "ck_segments_width_positive"


def _pg_constraint_exists(conn, table: str, name: str) -> bool:
    row = conn.execute(text(
        "SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
        "WHERE t.relname = :tbl AND c.conname = :name"
    ), {"tbl": table, "name": name}).first()
    return row is not None


def _sqlite_sql_text(conn, table: str) -> str:
    row = conn.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = :tbl"
    ), {"tbl": table}).first()
    return (row[0] or "") if row else ""


def _conform_existing_rows(conn) -> int:
    """把违反新交叉规则的旧摊主行收敛到优先级对应上限；返回修正行数。"""
    result = conn.execute(text(
        "UPDATE vendors SET stall_width_m = CASE"
        "     WHEN priority BETWEEN 1 AND 3 THEN 4.0"
        "     WHEN priority BETWEEN 4 AND 6 THEN 6.0"
        "     ELSE 8.0 END"
        " WHERE priority BETWEEN 1 AND 9 AND stall_width_m > 0"
        "   AND stall_width_m > CASE"
        "     WHEN priority BETWEEN 1 AND 3 THEN 4.0"
        "     WHEN priority BETWEEN 4 AND 6 THEN 6.0"
        "     ELSE 8.0 END"
    ))
    return result.rowcount or 0


def _add_pg_constraint(conn, table: str, name: str, check_sql: str) -> None:
    if _pg_constraint_exists(conn, table, name):
        return
    conn.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check_sql})"))


def _sqlite_rebuild_with_check(conn, table: str, name: str, check_sql: str) -> None:
    sql_text = _sqlite_sql_text(conn, table)
    if name in sql_text:
        return
    cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
    col_defs = []
    pk_cols = [c[1] for c in cols if c[5]]
    for c in cols:
        _, col_name, col_type, notnull, dflt, pk = c
        d = f"{col_name} {col_type or 'NUMERIC'}"
        if dflt is not None:
            d += f" DEFAULT {dflt}"
        if notnull:
            d += " NOT NULL"
        if len(pk_cols) == 1 and pk:
            d += " PRIMARY KEY"
        col_defs.append(d)
    col_list = ", ".join(c[1] for c in cols)
    pk_clause = f", PRIMARY KEY ({', '.join(pk_cols)})" if len(pk_cols) > 1 else ""
    tmp = f"{table}__guard_new"
    conn.execute(text(f"DROP TABLE IF EXISTS {tmp}"))
    conn.execute(text(
        f"CREATE TABLE {tmp} ({', '.join(col_defs)}{pk_clause}, "
        f"CONSTRAINT {name} CHECK ({check_sql}))"
    ))
    conn.execute(text(f"INSERT INTO {tmp} ({col_list}) SELECT {col_list} FROM {table}"))
    conn.execute(text(f"DROP TABLE {table}"))
    conn.execute(text(f"ALTER TABLE {tmp} RENAME TO {table}"))


def ensure_constraints(engine: Engine) -> dict[str, int]:
    """幂等补约束。返回 {'conformed_vendors': n}，n 为被收敛的历史违规行数。"""
    with engine.begin() as conn:
        conformed = _conform_existing_rows(conn)
        if engine.dialect.name == "postgresql":
            _add_pg_constraint(conn, "vendors", VENDOR_CK, VENDOR_CHECK_SQL)
            _add_pg_constraint(conn, "segments", SEGMENT_CK, SEGMENT_CHECK_SQL)
        elif engine.dialect.name == "sqlite":
            _sqlite_rebuild_with_check(conn, "vendors", VENDOR_CK, VENDOR_CHECK_SQL)
            _sqlite_rebuild_with_check(conn, "segments", SEGMENT_CK, SEGMENT_CHECK_SQL)
        else:  # 未知方言：不静默装作已迁移，直接失败暴露
            raise RuntimeError(f"unsupported dialect for schema guard: {engine.dialect.name}")
    return {"conformed_vendors": conformed}
