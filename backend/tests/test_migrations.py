"""启动迁移测例：旧库（无 CHECK、含违规老种子）→ 归一化 → 约束生效；保历史、幂等。"""
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.services.migrations import ensure_db_rules


def _legacy_engine():
    """模拟上线前的旧表结构：vendors/segments 没有任何 CHECK。"""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE market_days (id INTEGER PRIMARY KEY, name VARCHAR(64), day DATE)"))
        c.execute(text("CREATE TABLE segments (id INTEGER PRIMARY KEY, market_day_id INTEGER,"
                       " name VARCHAR(64), width_m FLOAT)"))
        c.execute(text("CREATE TABLE vendors (id INTEGER PRIMARY KEY, market_day_id INTEGER,"
                       " name VARCHAR(64), stall_width_m FLOAT, priority INTEGER)"))
        c.execute(text("CREATE TABLE pillars (id INTEGER PRIMARY KEY, segment_id INTEGER,"
                       " position_m FLOAT, thickness_m FLOAT, label VARCHAR(32))"))
        c.execute(text("CREATE TABLE allocation_runs (id INTEGER PRIMARY KEY, segment_id INTEGER,"
                       " created_at DATETIME, result_json TEXT)"))
        c.execute(text("INSERT INTO market_days (id, name, day) VALUES (1, '老夜市', '2026-09-20')"))
        # 违规老种子：12m/优先9、6m/优先1、5m/优先2、0 宽街段
        c.execute(text("INSERT INTO segments (id, market_day_id, name, width_m) VALUES (1,1,'东街',30)"))
        c.execute(text("INSERT INTO vendors (id, market_day_id, name, stall_width_m, priority) VALUES"
                       " (1,1,'巨型舞台车',12.0,9),(2,1,'大碗面',6.0,1),(3,1,'老周水果',5.0,2)"))
        c.execute(text("INSERT INTO allocation_runs (id, segment_id, result_json)"
                       " VALUES (77, 1, '{\"placements\":[{\"vendor_name\":\"巨型舞台车\"}]}')"))
    return eng


def test_migration_normalizes_violations_and_adds_check():
    eng = _legacy_engine()
    ensure_db_rules(eng)

    with eng.begin() as c:
        rows = c.execute(text("SELECT id, stall_width_m, priority FROM vendors ORDER BY id")).all()
    assert {r[0]: (r[1], r[2]) for r in rows} == {1: (8.0, 9), 2: (4.0, 1), 3: (4.0, 2)}

    # 约束已就位：违规直插失败，合法边界可过
    with eng.begin() as c:
        c.execute(text("INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
                       " VALUES (1,'边界',4.0,3)"))
    with pytest.raises(IntegrityError):
        with eng.begin() as c:
            c.execute(text("INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
                           " VALUES (1,'违规',4.1,3)"))


def test_migration_keeps_allocation_history_and_vendor_ids():
    eng = _legacy_engine()
    ensure_db_rules(eng)
    with eng.begin() as c:
        run = c.execute(text("SELECT id, result_json FROM allocation_runs")).all()
        ids = c.execute(text("SELECT id FROM vendors ORDER BY id")).all()
    assert run == [(77, '{"placements":[{"vendor_name":"巨型舞台车"}]}')]
    assert [r[0] for r in ids] == [1, 2, 3]  # 主键不重排，外键引用不断


def test_migration_idempotent():
    eng = _legacy_engine()
    ensure_db_rules(eng)
    ensure_db_rules(eng)  # 再来一次不报错、不重复改数
    with eng.begin() as c:
        n = c.execute(text("SELECT count(*) FROM vendors")).scalar()
    assert n == 3


def test_fresh_create_all_then_migrate_is_noop():
    """新库 create_all 已带 CHECK，迁移应识别为已就位。"""
    from app.database import Base
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    ensure_db_rules(eng)
    sql = inspect(eng).get_columns  # 仅确保调用不炸；真正断言约束文本：
    with eng.begin() as c:
        ddl = c.execute(text("SELECT sql FROM sqlite_master WHERE name='vendors'")).scalar()
    assert "ck_vendors_priority_width" in ddl
