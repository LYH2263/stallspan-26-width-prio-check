"""绕过接口直插违规也必须败——与接口拒绝测试分文件。

两层分别验证：
1. ORM session 直接 add/flush（应用层 before_insert/before_update 事件拦）；
2. 裸 SQL INSERT（应用层全部绕过，只靠数据库层 CHECK 拦）。
另含旧库迁移：无约束旧表 + 违规历史行 -> 迁后约束生效、历史开间运行不丢。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.models import AllocationRun, Vendor
from app.services.schema_guard import ensure_constraints
from app.services.vendor_rules import RuleViolation

ILLEGAL_CASES = [
    # priority, stall_width_m, 说明
    (1, 4.1, "p1~3 上限 4"),
    (3, 4.1, "合法边外：p3/4.1"),
    (4, 6.5, "p4~6 上限 6"),
    (6, 6.01, "p6 贴边外侧"),
    (7, 8.5, "p7~9 上限 8"),
    (9, 12.0, "旧种子违规形态"),
]


# ---------- 1) ORM 直插/直改（绕过 HTTP 接口）----------

@pytest.mark.parametrize("priority,width,why", ILLEGAL_CASES)
def test_orm_direct_insert_blocked(db, priority, width, why):
    session = db()
    session.add(Vendor(market_day_id=1, name=f"直插{width}",
                       stall_width_m=width, priority=priority))
    with pytest.raises(RuleViolation) as ei:
        session.flush()
    session.rollback()
    assert ei.value.field == "stall_width_m"

    # 确认没有半成功残留
    assert session.query(Vendor).filter_by(name=f"直插{width}").count() == 0
    session.close()


def test_orm_direct_insert_non_integer_priority_blocked(db):
    session = db()
    session.add(Vendor(market_day_id=1, name="小数优先",
                       stall_width_m=2.0, priority=2.5))
    # before_insert 事件读到 2.5，先按"优先级须为整数"拦
    with pytest.raises(RuleViolation) as ei:
        session.flush()
    session.rollback()
    assert ei.value.field == "priority"
    session.close()


def test_orm_direct_update_blocked(db):
    session = db()
    v = session.query(Vendor).filter_by(name="林记糖水").first()
    v.stall_width_m = 9.0
    v.priority = 2  # p1~3 上限 4
    with pytest.raises(RuleViolation):
        session.flush()
    session.rollback()
    # 改前值不变
    session.expire_all()
    again = session.query(Vendor).filter_by(name="林记糖水").first()
    assert (again.stall_width_m, again.priority) == (3.0, 1)
    session.close()


# ---------- 2) 裸 SQL 直插（连 ORM 事件也绕过，只剩数据库层 CHECK）----------

@pytest.mark.parametrize("priority,width,why", ILLEGAL_CASES)
def test_raw_sql_insert_blocked_by_db_check(db, priority, width, why):
    session = db()
    with pytest.raises(IntegrityError):
        session.execute(text(
            "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
            " VALUES (1, :n, :w, :p)"),
            {"n": f"裸插{width}", "w": width, "p": priority})
    session.rollback()
    found = session.execute(
        text("SELECT COUNT(*) FROM vendors WHERE name = :n"),
        {"n": f"裸插{width}"}).scalar()
    assert found == 0
    session.close()


def test_raw_sql_insert_non_integer_priority_blocked(db):
    session = db()
    with pytest.raises(IntegrityError):
        session.execute(text(
            "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
            " VALUES (1, '裸插小数优先', 2.0, 2.5)"))
    session.rollback()
    session.close()


def test_raw_sql_insert_zero_width_blocked(db):
    session = db()
    with pytest.raises(IntegrityError):
        session.execute(text(
            "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
            " VALUES (1, '零宽摊', 0, 1)"))
    session.rollback()
    session.close()


def test_raw_sql_update_to_illegal_blocked(db):
    session = db()
    vid = session.query(Vendor).filter_by(name="林记糖水").first().id
    with pytest.raises(IntegrityError):
        session.execute(text(
            "UPDATE vendors SET stall_width_m = 5.0 WHERE id = :id"), {"id": vid})
    session.rollback()
    session.close()


def test_raw_sql_legal_edge_passes(db):
    # 合法边裸插 p3/4.0 必须过（不能误伤合法）
    session = db()
    session.execute(text(
        "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
        " VALUES (1, '裸插合法边', 4.0, 3)"))
    session.commit()
    found = session.execute(
        text("SELECT stall_width_m, priority FROM vendors WHERE name='裸插合法边'")
    ).first()
    assert found == (4.0, 3)
    session.close()


def test_raw_sql_segment_zero_width_blocked(db):
    session = db()
    with pytest.raises(IntegrityError):
        session.execute(text(
            "INSERT INTO segments (market_day_id, name, width_m) VALUES (1, '零宽街', 0)"))
    session.rollback()
    session.close()


# ---------- 3) 旧库迁移：补约束 + 收敛违规历史行，开间历史不丢 ----------

def test_migration_adds_constraint_to_legacy_table_and_conforms_rows(db):
    # 手工造一张"迁移前"的旧表：去掉 CHECK，并塞入违规行（模拟旧种子 p9/12）
    session = db()
    session.execute(text("ALTER TABLE vendors RENAME TO vendors_old"))
    session.execute(text(
        "CREATE TABLE vendors (id INTEGER PRIMARY KEY, market_day_id INTEGER,"
        " name VARCHAR(64), stall_width_m FLOAT, priority INTEGER)"))
    session.execute(text(
        "INSERT INTO vendors (id, market_day_id, name, stall_width_m, priority)"
        " SELECT id, market_day_id, name, stall_width_m, priority FROM vendors_old"))
    session.execute(text(
        "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
        " VALUES (1, '旧时代大摊', 12.0, 9)"))
    # 迁移前无约束：违规行能存在，裸插违规也能进
    session.execute(text(
        "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
        " VALUES (1, '迁移前裸插', 9.0, 1)"))
    session.commit()

    # 留一条开间运行历史，迁移不得清掉
    before_runs = session.query(AllocationRun).count()
    session.add(AllocationRun(segment_id=1, result_json='{"legacy": true}'))
    session.commit()
    session.close()

    from app.database import engine
    info = ensure_constraints(engine)
    assert info["conformed_vendors"] >= 2  # 12.0/p9 与 9.0/p1 都被收敛

    session = db()
    # 违规行被收敛到合法上限
    row = session.execute(text(
        "SELECT stall_width_m FROM vendors WHERE name='旧时代大摊'")).first()
    assert row[0] == 8.0
    # 开间运行历史一条不少（表重建没碰 allocation_runs）
    assert session.query(AllocationRun).count() == before_runs + 1
    assert session.execute(
        text("SELECT result_json FROM allocation_runs WHERE result_json LIKE '%legacy%'")
    ).scalar() == '{"legacy": true}'

    # 迁完后约束真正生效：裸插违规必败
    with pytest.raises(IntegrityError):
        session.execute(text(
            "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
            " VALUES (1, '迁后裸插', 9.0, 1)"))
    session.rollback()
    # 合法边仍可过
    session.execute(text(
        "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
        " VALUES (1, '迁后合法', 4.0, 3)"))
    session.commit()
    session.close()


def test_migration_is_idempotent(db):
    from app.database import engine
    ensure_constraints(engine)
    ensure_constraints(engine)  # 再跑不报错、不重复加
    session = db()
    # 约束仍在并生效
    with pytest.raises(IntegrityError):
        session.execute(text(
            "INSERT INTO vendors (market_day_id, name, stall_width_m, priority)"
            " VALUES (1, '幂等后裸插', 9.0, 1)"))
    session.rollback()
    session.close()
