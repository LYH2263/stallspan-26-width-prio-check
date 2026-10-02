"""绕过接口直插数据库的兜底测例 —— 与接口拒绝测例有意分文件。

任何不经 API 的写入（ORM session.add / 裸 SQL INSERT）撞同一套 CHECK 都必须败。
"""
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.models import AllocationRun, MarketDay, Segment, Vendor


@pytest.fixture()
def day_id(engine):
    db = sessionmaker(bind=engine)()
    day = MarketDay(name="直插夜市", day=date(2026, 10, 2))
    db.add(day); db.flush()
    seg = Segment(market_day_id=day.id, name="直插街", width_m=30.0)
    db.add(seg); db.commit()
    yield day.id
    db.close()


@pytest.mark.parametrize("priority,width,msg", [
    (3, 4.1, "跨档 0.1 也必须败"),
    (1, 4.000001, "优先1上限4"),
    (6, 6.5, "优先6上限6"),
    (7, 8.1, "优先7上限8"),
    (9, 12.0, "老种子里的12m大车"),
    (2, -1.0, "摊宽为负"),
    (0, 3.0, "优先0"),
    (10, 3.0, "优先10"),
])
def test_orm_add_illegal_vendor_fails(engine, day_id, priority, width, msg):
    db = sessionmaker(bind=engine)()
    db.add(Vendor(market_day_id=day_id, name=msg, stall_width_m=width, priority=priority))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    n = db.execute(text("SELECT count(*) FROM vendors WHERE name=:n"), {"n": msg}).scalar()
    assert n == 0  # 失败不留行
    db.close()


@pytest.mark.parametrize("priority,width", [(1, 4.0), (3, 4.0), (4, 6.0), (6, 6.0), (7, 8.0), (9, 8.0)])
def test_orm_add_legal_edge_inserts(engine, day_id, priority, width):
    db = sessionmaker(bind=engine)()
    v = Vendor(market_day_id=day_id, name=f"合法{priority}", stall_width_m=width, priority=priority)
    db.add(v); db.commit(); db.refresh(v)
    assert v.id is not None
    db.close()


def test_raw_sql_insert_illegal_fails(engine, day_id):
    db = sessionmaker(bind=engine)()
    with pytest.raises(IntegrityError):
        db.execute(text(
            "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
            " VALUES (:d, '裸插4.1', 4.1, 3)"), {"d": day_id})
        db.commit()
    db.rollback()
    n = db.execute(text("SELECT count(*) FROM vendors WHERE name='裸插4.1'")).scalar()
    assert n == 0
    db.close()


def test_raw_insert_fractional_priority_fails(engine, day_id):
    """绕过 pydantic 直插 2.5 优先级：库内整数子句必须挡住（SQLite 也不例外）。"""
    db = sessionmaker(bind=engine)()
    with pytest.raises(IntegrityError):
        db.execute(text(
            "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
            " VALUES (:d, '小数优先', 3.0, 2.5)"), {"d": day_id})
        db.commit()
    db.rollback()
    db.close()


def test_raw_sql_insert_legal_edge_ok(engine, day_id):
    db = sessionmaker(bind=engine)()
    db.execute(text(
        "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
        " VALUES (:d, '裸插边界', 4.0, 3)"), {"d": day_id})
    db.commit()
    n = db.execute(text("SELECT count(*) FROM vendors WHERE name='裸插边界'")).scalar()
    assert n == 1
    db.close()


def test_raw_insert_zero_street_width_fails(engine, day_id):
    db = sessionmaker(bind=engine)()
    with pytest.raises(IntegrityError):
        db.execute(text(
            "INSERT INTO segments (market_day_id, name, width_m) VALUES (:d, '零宽', 0)"),
            {"d": day_id})
        db.commit()
    db.rollback()
    db.close()


def test_direct_illegal_insert_does_not_touch_allocation_runs(engine, day_id):
    """直插违规失败，不得清掉历史开间运行。"""
    db = sessionmaker(bind=engine)()
    seg = db.execute(text("SELECT id FROM segments WHERE market_day_id=:d"), {"d": day_id}).scalar()
    db.add(AllocationRun(segment_id=seg, result_json='{"placements":[{"x":1}]}'))
    db.commit()
    before = db.execute(text("SELECT count(*) FROM allocation_runs")).scalar()

    with pytest.raises(IntegrityError):
        db.execute(text(
            "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
            " VALUES (:d, '冲约束', 9.0, 1)"), {"d": day_id})
        db.commit()
    db.rollback()

    after = db.execute(text("SELECT count(*) FROM allocation_runs")).scalar()
    assert after == before == 1
    db.close()
