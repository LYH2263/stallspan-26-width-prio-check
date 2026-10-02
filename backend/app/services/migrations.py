"""旧库到“优先×摊宽交叉规则”的启动期幂等迁移。

- 只给 vendors / segments 补 CHECK 约束，绝不 DELETE 任何行，
  allocation_runs（历史开间运行）整表不碰。
- 旧数据若违规则按 rules 的同一档位归一化（夹到合法档/上限），再上约束。
- 已存在同名约束则跳过，可反复启动。
"""
from __future__ import annotations

import logging
import math

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.services.rules import (
    PRIORITY_MAX,
    PRIORITY_MIN,
    PRIORITY_WIDTH_CAPS,
    cap_for_priority,
    segment_check_sql,
    vendor_check_sql,
)

log = logging.getLogger("stallspan.migrate")

VENDOR_CK = "ck_vendors_priority_width"
SEGMENT_CK = "ck_segments_width_positive"


def _normalize_vendor(priority, width) -> tuple[int, float] | None:
    """把老数据夹进合法域；返回 (new_priority, new_width)，已合法返回 None。"""
    try:
        p = int(round(float(priority)))
    except (TypeError, ValueError):
        p = PRIORITY_MIN
    p = max(PRIORITY_MIN, min(PRIORITY_MAX, p))
    try:
        w = float(width)
    except (TypeError, ValueError):
        w = math.nan
    if not math.isfinite(w) or w <= 0:
        w = cap_for_priority(p)  # 非正/缺失给整档上限，保证 > 0 且不超限
    cap = cap_for_priority(p)
    if w > cap:
        w = cap
    w = round(w, 3)
    if isinstance(priority, int) and not isinstance(priority, bool) and float(width) == w \
            and PRIORITY_MIN <= priority <= PRIORITY_MAX:
        return None
    return p, w


def _pg_constraint_exists(conn, name: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}
    ).first()
    return row is not None


def _sqlite_table_sql(conn, table: str) -> str:
    row = conn.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"), {"n": table}
    ).first()
    return (row[0] if row else "") or ""


def _normalize_existing_vendors(conn) -> int:
    rows = conn.execute(text("SELECT id, priority, stall_width_m FROM vendors")).all()
    fixed = 0
    for rid, pri, wdt in rows:
        norm = _normalize_vendor(pri, wdt)
        if norm is None:
            continue
        new_p, new_w = norm
        log.warning("归一化违规摊主 id=%s priority=%s width=%s -> priority=%s width=%s",
                    rid, pri, wdt, new_p, new_w)
        conn.execute(
            text("UPDATE vendors SET priority=:p, stall_width_m=:w WHERE id=:i"),
            {"p": new_p, "w": new_w, "i": rid},
        )
        fixed += 1
    return fixed


def _normalize_existing_segments(conn) -> int:
    rows = conn.execute(text("SELECT id, width_m FROM segments")).all()
    fixed = 0
    for rid, wdt in rows:
        try:
            w = float(wdt)
        except (TypeError, ValueError):
            w = math.nan
        if math.isfinite(w) and w > 0:
            continue
        log.warning("归一化违规街段 id=%s width=%s -> 1.0", rid, wdt)
        conn.execute(text("UPDATE segments SET width_m=1.0 WHERE id=:i"), {"i": rid})
        fixed += 1
    return fixed


def _migrate_postgres(engine: Engine) -> None:
    from app.models.models import Segment, Vendor  # 避免循环导入
    with engine.begin() as conn:
        if not _pg_constraint_exists(conn, VENDOR_CK):
            _normalize_existing_vendors(conn)
            conn.execute(text(
                f"ALTER TABLE vendors ADD CONSTRAINT {VENDOR_CK} CHECK {vendor_check_sql()}"
            ))
        if not _pg_constraint_exists(conn, SEGMENT_CK):
            _normalize_existing_segments(conn)
            conn.execute(text(
                f"ALTER TABLE segments ADD CONSTRAINT {SEGMENT_CK} CHECK {segment_check_sql()}"
            ))


def _sqlite_rebuild(engine: Engine) -> None:
    """SQLite 不能事后加 CHECK，按官方 12 步重建 vendors/segments；allocation_runs 不动。"""
    from app.models.models import Segment, Vendor

    need_v = need_s = False
    with engine.begin() as conn:
        need_v = VENDOR_CK not in _sqlite_table_sql(conn, "vendors")
        need_s = SEGMENT_CK not in _sqlite_table_sql(conn, "segments")
    if not need_v and not need_s:
        return

    is_sqlite = engine.dialect.name == "sqlite"
    raw = engine.raw_connection()
    if is_sqlite:
        raw.isolation_level = None  # autocommit：PRAGMA foreign_keys 不能在事务内切
    try:
        cur = raw.cursor()
        # PRAGMA foreign_keys 不能在事务内切换
        cur.execute("PRAGMA foreign_keys=OFF")

        if need_v:
            cur.execute("ALTER TABLE vendors RENAME TO vendors__old_ck")
            Vendor.__table__.create(bind=engine, checkfirst=True)
            old = cur.execute(
                "SELECT id, market_day_id, name, stall_width_m, priority FROM vendors__old_ck"
            ).fetchall()
            for rid, day_id, name, wdt, pri in old:
                norm = _normalize_vendor(pri, wdt)
                new_p, new_w = norm if norm else (pri, wdt)
                cur.execute(
                    "INSERT INTO vendors (id, market_day_id, name, stall_width_m, priority)"
                    " VALUES (?,?,?,?,?)",
                    (rid, day_id, name, new_w, new_p),
                )
            cur.execute("DROP TABLE vendors__old_ck")

        if need_s:
            cur.execute("ALTER TABLE segments RENAME TO segments__old_ck")
            Segment.__table__.create(bind=engine, checkfirst=True)
            old = cur.execute(
                "SELECT id, market_day_id, name, width_m FROM segments__old_ck"
            ).fetchall()
            for rid, day_id, name, wdt in old:
                try:
                    w = float(wdt)
                    new_w = w if math.isfinite(w) and w > 0 else 1.0
                except (TypeError, ValueError):
                    new_w = 1.0
                cur.execute(
                    "INSERT INTO segments (id, market_day_id, name, width_m)"
                    " VALUES (?,?,?,?)",
                    (rid, day_id, name, new_w),
                )
            cur.execute("DROP TABLE segments__old_ck")

        cur.execute("PRAGMA foreign_keys=ON")
    finally:
        if is_sqlite:
            raw.isolation_level = ""
        raw.close()


def ensure_db_rules(engine: Engine) -> None:
    """create_all 之后调用；确保库内 CHECK 与 rules.py 档位一致。"""
    tables = set(inspect(engine).get_table_names())
    if "vendors" not in tables or "segments" not in tables:
        return
    if engine.dialect.name == "postgresql":
        _migrate_postgres(engine)
    elif engine.dialect.name == "sqlite":
        _sqlite_rebuild(engine)
    else:
        log.warning("未知方言 %s，跳过库内约束迁移", engine.dialect.name)
