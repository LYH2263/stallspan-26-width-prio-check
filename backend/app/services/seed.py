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
        # 全部贴交叉规则合法：p1~3 摊宽 <= 4，p4~6 <= 6，p7~9 <= 8
        ("阿强烧烤", 4.0, 1), ("林记糖水", 3.0, 1), ("老周水果", 4.0, 2),
        ("小美饰品", 2.5, 2), ("大碗面", 4.0, 1), ("手作皮具", 3.5, 3),
        # 交叉规则合法边：优先级 7~9 摊宽上限 8 m。8.0/p9 合法可入库；
        # 分配时各连续空档已被前排占满（余 0.25/1.5/6.25 m），它仍进"放不下"。
        ("巨型舞台车", 8.0, 9),
    ]
    for name, wdt, pri in vendors:
        db.add(Vendor(market_day_id=day.id, name=name, stall_width_m=wdt, priority=pri))
    db.commit()
