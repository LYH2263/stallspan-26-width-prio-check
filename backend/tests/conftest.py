import os
from datetime import date

# 必须在导入 app.* 之前：让 app.config 的默认引擎不碰真实 Postgres
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SEED_ON_EMPTY", "false")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import MarketDay, Segment, Vendor


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def Session(engine):
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def client(engine):
    import app.main as main_mod
    TestingSession = sessionmaker(bind=engine, autoflush=False)

    def _get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    main_mod.engine = engine  # lifespan 的 create_all / ensure_db_rules 走测试库
    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded(engine):
    """一份合法的最小集日/街段数据。"""
    db = sessionmaker(bind=engine)()
    day = MarketDay(name="测试夜市", day=date(2026, 10, 2))
    db.add(day)
    db.flush()
    seg = Segment(market_day_id=day.id, name="东街", width_m=30.0)
    db.add(seg)
    db.flush()
    db.add_all([
        Vendor(market_day_id=day.id, name="边界三摊", stall_width_m=4.0, priority=3),
        Vendor(market_day_id=day.id, name="大车", stall_width_m=8.0, priority=9),
    ])
    db.commit()
    return {"day_id": day.id, "segment_id": seg.id}
