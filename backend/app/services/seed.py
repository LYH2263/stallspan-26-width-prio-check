from datetime import date
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.models import MarketDay, Pillar, Segment, Vendor

def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(MarketDay)) or 0) > 0:
        return
    day = MarketDay(name="周末夜市", day=date(2026, 9, 20))
    db.add(day); db.flush()
    seg = Segment(market_day_id=day.id, name="东街段", width_m=30.0)
    db.add(seg); db.flush()
    db.add(Pillar(segment_id=seg.id, position_m=10.0, thickness_m=0.5, label="灯柱A"))
    db.add(Pillar(segment_id=seg.id, position_m=20.0, thickness_m=0.5, label="灯柱B"))
    vendors = [
        # (名称, 摊宽m, 优先) —— 全部满足交叉档位：1-3≤4 / 4-6≤6 / 7-9≤8
        ("阿强烧烤", 4.0, 1), ("林记糖水", 3.0, 1), ("老周水果", 5.0, 4),
        ("小美饰品", 2.5, 2), ("大碗面", 6.0, 4), ("手作皮具", 4.0, 3),
        ("巨型舞台车", 8.0, 9),
    ]
    for name, wdt, pri in vendors:
        db.add(Vendor(market_day_id=day.id, name=name, stall_width_m=wdt, priority=pri))
    db.commit()
