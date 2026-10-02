from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import request_validation_handler
from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.schema_guard import ensure_constraints
from app.services.seed import seed_if_empty


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # 旧库补齐数据库层 CHECK（幂等），顺序：建表 -> 补约束 -> 种子
    guard = ensure_constraints(engine)
    if guard.get("conformed_vendors"):
        # 旧库里超新交叉规则的历史行已收敛到合法上限，保证起服分配不被卡住
        import logging
        logging.getLogger("stallspan").warning(
            "schema guard 收敛了 %s 个超摊宽上限的历史摊主行",
            guard["conformed_vendors"])
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="StallSpan", version="0.1.0", lifespan=lifespan)
app.add_exception_handler(RequestValidationError, request_validation_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
