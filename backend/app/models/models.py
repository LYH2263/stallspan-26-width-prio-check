from datetime import date, datetime
from sqlalchemy import CheckConstraint, Date, DateTime, event, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.services.vendor_rules import (
    SEGMENT_CHECK_SQL,
    VENDOR_CHECK_SQL,
    ensure_vendor_values,
)

class MarketDay(Base):
    __tablename__ = "market_days"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    day: Mapped[date] = mapped_column(Date)

class Segment(Base):
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_day_id: Mapped[int] = mapped_column(ForeignKey("market_days.id"))
    name: Mapped[str] = mapped_column(String(64))
    width_m: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        CheckConstraint(SEGMENT_CHECK_SQL, name="ck_segments_width_positive"),
    )

class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_day_id: Mapped[int] = mapped_column(ForeignKey("market_days.id"))
    name: Mapped[str] = mapped_column(String(64))
    stall_width_m: Mapped[float] = mapped_column(Float)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        # 数据库层兜底：摊宽 × 优先级 交叉规则与 vendor_rules.py 同一套阈值
        CheckConstraint(VENDOR_CHECK_SQL, name="ck_vendors_priority_width"),
    )

class Pillar(Base):
    __tablename__ = "pillars"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"))
    position_m: Mapped[float] = mapped_column(Float)
    thickness_m: Mapped[float] = mapped_column(Float, default=0.4)
    label: Mapped[str] = mapped_column(String(32), default="挡柱")

class AllocationRun(Base):
    __tablename__ = "allocation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result_json: Mapped[str] = mapped_column(Text, default="{}")


# ---- 应用层兜底：ORM 写入（含绕过接口直插 session）在 flush 瞬间按当前值重检 ----
# 新建与改写走同一钩子；改优先级后保存也按提交瞬间的新交叉规则判定，不吃改前缓存。
def _validate_vendor_target(_mapper, _connection, target: "Vendor") -> None:
    ensure_vendor_values(target.stall_width_m, target.priority)


event.listen(Vendor, "before_insert", _validate_vendor_target)
event.listen(Vendor, "before_update", _validate_vendor_target)
