from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import MarketDay, Segment
from app.services.vendor_rules import LABEL_STREET_WIDTH, validate_street_width

router = APIRouter(prefix="/segments", tags=["segments"])


class SegmentWrite(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    width_m: float
    market_day_id: int = 1


class SegmentPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    width_m: float | None = None
    market_day_id: int | None = None


def _row(r: Segment) -> dict:
    return {"id": r.id, "market_day_id": r.market_day_id, "name": r.name,
            "width_m": r.width_m}


def _reject(v, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "field": getattr(v, "field", "width_m"),
        "field_label": getattr(v, "field_label", LABEL_STREET_WIDTH),
        "message": str(v),
    })


def _commit_segment(db: Session, obj: Segment, width: float):
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        v = validate_street_width(width)
        return _reject(v if v is not None else _DbFallback())
    db.refresh(obj)
    return None


class _DbFallback:
    field = "width_m"
    field_label = LABEL_STREET_WIDTH

    def __str__(self):
        return "街宽不合规，数据库拒绝写入"


@router.get("")
def list_segments(db: Session = Depends(get_db)):
    return [_row(r) for r in db.scalars(select(Segment).order_by(Segment.id)).all()]


@router.post("")
def create_segment(body: SegmentWrite, db: Session = Depends(get_db)):
    v = validate_street_width(body.width_m)
    if v is not None:
        return _reject(v)
    if not db.get(MarketDay, body.market_day_id):
        return JSONResponse(status_code=404, content={
            "field": "market_day_id", "field_label": "集日ID",
            "message": "集日不存在"})
    obj = Segment(market_day_id=body.market_day_id, name=body.name,
                  width_m=body.width_m)
    err = _commit_segment(db, obj, body.width_m)
    return err if err is not None else _row(obj)


@router.put("/{segment_id}")
def update_segment(segment_id: int, body: SegmentPatch, db: Session = Depends(get_db)):
    obj = db.get(Segment, segment_id)
    if not obj:
        return JSONResponse(status_code=404, content={
            "field": "id", "field_label": "街段", "message": "街段不存在"})
    new_name = body.name if body.name is not None else obj.name
    new_width = body.width_m if body.width_m is not None else obj.width_m
    new_day = body.market_day_id if body.market_day_id is not None else obj.market_day_id
    v = validate_street_width(new_width)
    if v is not None:
        db.rollback()
        return _reject(v)
    if not db.get(MarketDay, new_day):
        return JSONResponse(status_code=404, content={
            "field": "market_day_id", "field_label": "集日ID",
            "message": "集日不存在"})
    obj.name, obj.width_m, obj.market_day_id = new_name, new_width, new_day
    err = _commit_segment(db, obj, new_width)
    return err if err is not None else _row(obj)
