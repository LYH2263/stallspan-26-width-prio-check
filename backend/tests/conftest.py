"""接口/直插测试共用：SQLite 临时文件库，覆盖 create_all -> 迁移补约束 -> 种子 全链路。

必须在 import app.* 之前设置 DATABASE_URL（config 在导入时读环境变量）。
"""
import os
import tempfile

_DB_PATH = os.path.join(tempfile.mkdtemp(prefix="stallspan_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["SEED_ON_EMPTY"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.schema_guard import ensure_constraints  # noqa: E402
from app.services.seed import seed_if_empty  # noqa: E402


@pytest.fixture()
def db():
    """每个测试一个干净且已上约束、已种子的库。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ensure_constraints(engine)
    session = SessionLocal()
    try:
        seed_if_empty(session)
    finally:
        session.close()
    yield SessionLocal
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        yield c
