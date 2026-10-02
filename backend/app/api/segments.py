from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import MarketDay, Segment
from app.services.rules import RuleViolation, validate_street_width
router = APIRouter(prefix="/segments", tags=["segments"])


class SegmentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_day_id: int
    name: str = Field(min_length=1, max_length=64)
    width_m: float


@router.get("")
def list_segments(db: Session = Depends(get_db)):
    return [{"id": r.id, "market_day_id": r.market_day_id, "name": r.name, "width_m": r.width_m}
            for r in db.scalars(select(Segment).order_by(Segment.id)).all()]


@router.post("", status_code=201)
def create_segment(body: SegmentWrite, db: Session = Depends(get_db)):
    """新建街段：街宽 > 0 应用层先拦，库内 CHECK 第二道；两层同一规则。"""
    try:
        validate_street_width(body.width_m)
    except RuleViolation as e:
        raise HTTPException(422, detail={"field": e.field, "message": e.message})
    if not db.get(MarketDay, body.market_day_id):
        raise HTTPException(404, f"集日不存在：{body.market_day_id}")
    row = Segment(market_day_id=body.market_day_id, name=body.name, width_m=body.width_m)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(422, detail={
            "field": "width_m",
            "message": "街宽(width_m)必须大于0，写入被数据库拒绝",
        })
    db.refresh(row)
    return {"id": row.id, "market_day_id": row.market_day_id, "name": row.name,
            "width_m": row.width_m}
