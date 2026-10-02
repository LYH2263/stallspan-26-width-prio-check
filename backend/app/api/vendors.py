from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import MarketDay, Vendor
from app.services.rules import RuleViolation, validate_vendor_rules

router = APIRouter(prefix="/vendors", tags=["vendors"])


class VendorWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_day_id: int
    name: str = Field(min_length=1, max_length=64)
    stall_width_m: float = Field()
    priority: int = Field()


def _serialize(r: Vendor) -> dict:
    return {"id": r.id, "market_day_id": r.market_day_id, "name": r.name,
            "stall_width_m": r.stall_width_m, "priority": r.priority}


def _reject_violation(e: RuleViolation) -> HTTPException:
    # 422 点名字段；消息与摊主页同一叫法，且不是“空档不够”类分配原因
    return HTTPException(422, detail={"field": e.field, "message": e.message})


def _get_day_or_404(db: Session, day_id: int) -> MarketDay:
    day = db.get(MarketDay, day_id)
    if not day:
        raise HTTPException(404, f"集日不存在：{day_id}")
    return day


@router.get("")
def list_vendors(db: Session = Depends(get_db)):
    return [_serialize(r)
            for r in db.scalars(select(Vendor).order_by(Vendor.priority, Vendor.id)).all()]


@router.post("", status_code=201)
def create_vendor(body: VendorWrite, db: Session = Depends(get_db)):
    """新建摊主。交叉规则按提交瞬间的 priority/width 校验，写与改写同拒、整笔原子。"""
    validate_payload(body)
    _get_day_or_404(db, body.market_day_id)
    row = Vendor(market_day_id=body.market_day_id, name=body.name,
                 stall_width_m=body.stall_width_m, priority=body.priority)
    db.add(row)
    try:
        db.commit()  # 库内 CHECK 是第二道；违规时整笔回滚，不存在半成功
    except IntegrityError:
        db.rollback()
        raise HTTPException(422, detail={
            "field": "stall_width_m",
            "message": "摊宽(stall_width_m)与优先级(priority)交叉规则被数据库拒绝",
        })
    db.refresh(row)
    return _serialize(row)


@router.put("/{vendor_id}")
def update_vendor(vendor_id: int, body: VendorWrite, db: Session = Depends(get_db)):
    """改写摊主。禁止吃改前优先缓存：只用本次提交的 priority+width 重检。

    失败时事务回滚，库里仍停在改前值；历史 allocation_runs 与主图色块均不受影响。
    """
    row = db.get(Vendor, vendor_id)
    if not row:
        raise HTTPException(404, f"摊主不存在：{vendor_id}")
    validate_payload(body)
    _get_day_or_404(db, body.market_day_id)
    row.market_day_id = body.market_day_id
    row.name = body.name
    row.stall_width_m = body.stall_width_m
    row.priority = body.priority
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(422, detail={
            "field": "stall_width_m",
            "message": "摊宽(stall_width_m)与优先级(priority)交叉规则被数据库拒绝",
        })
    db.refresh(row)
    return _serialize(row)


def validate_payload(body: VendorWrite) -> None:
    try:
        validate_vendor_rules(body.priority, body.stall_width_m)
    except RuleViolation as e:
        raise _reject_violation(e)
