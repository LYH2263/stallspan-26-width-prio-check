from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import MarketDay, Vendor
from app.services.vendor_rules import LABEL_STALL_WIDTH, validate_vendor_values

router = APIRouter(prefix="/vendors", tags=["vendors"])


class VendorWrite(BaseModel):
    # 拒绝额外字段混入，强制数值类型（3/4 过、3/4.1 判定在业务层）
    model_config = ConfigDict(extra="ignore")
    name: str
    stall_width_m: float
    priority: int
    market_day_id: int = 1


class VendorPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    stall_width_m: float | None = None
    priority: int | None = None
    market_day_id: int | None = None


class _DbFallback:
    field = "stall_width_m"
    field_label = LABEL_STALL_WIDTH

    def __str__(self):
        return "摊宽与优先级不符交叉规则，数据库拒绝写入"


def _row(r: Vendor) -> dict:
    return {"id": r.id, "market_day_id": r.market_day_id, "name": r.name,
            "stall_width_m": r.stall_width_m, "priority": r.priority}


def _reject(v, status: int = 400) -> JSONResponse:
    """规则违规/数据库约束失败 -> 点名字段、与摊主页同一叫法的 400。"""
    return JSONResponse(status_code=status, content={
        "field": getattr(v, "field", "stall_width_m"),
        "field_label": getattr(v, "field_label", LABEL_STALL_WIDTH),
        "message": str(v),
    })


def _commit_vendor(db: Session, obj: Vendor, width: float, priority: int):
    """整笔提交：应用层已过，ORM 事件与数据库 CHECK 再兜底。

    任何失败整笔回滚，禁止半成功写入；历史 allocation_runs 不在此事务内，不受影响。
    """
    db.add(obj)
    try:
        db.commit()
    except Exception:
        # 可能是 ORM before_insert/update 事件抛的 RuleViolation，
        # 也可能是数据库层 CHECK 的 IntegrityError——两种都按规则失败处理，
        # 绝不上抛成 500，更绝不写成"空档不够"这类分配理由。
        db.rollback()
        violations = validate_vendor_values(width, priority)
        return _reject(violations[0] if violations else _DbFallback())
    db.refresh(obj)
    return None


@router.get("")
def list_vendors(db: Session = Depends(get_db)):
    return [_row(r) for r in
            db.scalars(select(Vendor).order_by(Vendor.priority, Vendor.id)).all()]


@router.post("")
def create_vendor(body: VendorWrite, db: Session = Depends(get_db)):
    # 提交瞬间按请求里的 摊宽/优先级 交叉重检，不依赖任何改前缓存
    violations = validate_vendor_values(body.stall_width_m, body.priority)
    if violations:
        return _reject(violations[0])
    if not db.get(MarketDay, body.market_day_id):
        return JSONResponse(status_code=404, content={
            "field": "market_day_id", "field_label": "集日ID",
            "message": "集不存在"})
    obj = Vendor(market_day_id=body.market_day_id, name=body.name,
                 stall_width_m=body.stall_width_m, priority=body.priority)
    err = _commit_vendor(db, obj, body.stall_width_m, body.priority)
    return err if err is not None else _row(obj)


@router.put("/{vendor_id}")
def update_vendor(vendor_id: int, body: VendorPatch, db: Session = Depends(get_db)):
    obj = db.get(Vendor, vendor_id)
    if not obj:
        return JSONResponse(status_code=404, content={
            "field": "id", "field_label": "摊主", "message": "摊主不存在"})
    # 改写与新建同一套：缺省字段沿用现值，提交瞬间用合并后的新值重检。
    # 改优先后再保存，按新优先级重算摊宽上限，禁止吃改前优先缓存。
    new_name = body.name if body.name is not None else obj.name
    new_width = body.stall_width_m if body.stall_width_m is not None else obj.stall_width_m
    new_priority = body.priority if body.priority is not None else obj.priority
    new_day = body.market_day_id if body.market_day_id is not None else obj.market_day_id
    violations = validate_vendor_values(new_width, new_priority)
    if violations:
        db.rollback()  # 被拒时数据停在改前
        return _reject(violations[0])
    if not db.get(MarketDay, new_day):
        return JSONResponse(status_code=404, content={
            "field": "market_day_id", "field_label": "集日ID",
            "message": "集日不存在"})
    obj.name, obj.stall_width_m, obj.priority, obj.market_day_id = \
        new_name, new_width, new_priority, new_day
    err = _commit_vendor(db, obj, new_width, new_priority)
    return err if err is not None else _row(obj)
