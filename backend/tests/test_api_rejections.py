"""接口层拒绝测例（POST/PUT /vendors、POST /segments、/allocate/run）。

直插数据库的兜底测例见 test_direct_insert_db.py，两者有意分开。
"""
import pytest

from app.services.rules import SPACE_SHORTAGE_REASON


def _payload(day_id, **over):
    body = {"market_day_id": day_id, "name": "新摊主", "stall_width_m": 3.0, "priority": 1}
    body.update(over)
    return body


# ---------- 合法边界 / 非法边界 ----------

def test_legal_edge_priority3_width4_passes(client, seeded):
    r = client.post("/api/vendors", json=_payload(seeded["day_id"], priority=3, stall_width_m=4.0))
    assert r.status_code == 201, r.text
    assert r.json()["stall_width_m"] == 4.0


@pytest.mark.parametrize("priority,width", [(3, 4.1), (1, 4.0000001), (4, 6.1), (9, 8.1)])
def test_width_over_band_cap_rejected(client, seeded, priority, width):
    r = client.post("/api/vendors", json=_payload(seeded["day_id"], priority=priority, stall_width_m=width))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    # 点名字段，叫法与摊主页一致
    assert detail["field"] == "stall_width_m"
    assert "摊宽(stall_width_m)" in detail["message"]
    assert "优先级(priority)" in detail["message"]
    # 非法改宽不得套“空档不够”的分配原因
    assert SPACE_SHORTAGE_REASON not in detail["message"]


@pytest.mark.parametrize("priority", [0, 10, -1])
def test_priority_out_of_range_rejected(client, seeded, priority):
    r = client.post("/api/vendors", json=_payload(seeded["day_id"], priority=priority, stall_width_m=2.0))
    assert r.status_code == 422
    assert r.json()["detail"]["field"] == "priority"


def test_priority_must_be_integer(client, seeded):
    r = client.post("/api/vendors", json=_payload(seeded["day_id"], priority=2.5, stall_width_m=2.0))
    assert r.status_code == 422


@pytest.mark.parametrize("width", [0, -1.0])
def test_stall_width_must_be_positive(client, seeded, width):
    r = client.post("/api/vendors", json=_payload(seeded["day_id"], stall_width_m=width))
    assert r.status_code == 422
    assert r.json()["detail"]["field"] == "stall_width_m"


def test_segment_width_must_be_positive(client, seeded):
    r = client.post("/api/segments",
                    json={"market_day_id": seeded["day_id"], "name": "窄街", "width_m": 0})
    assert r.status_code == 422
    assert r.json()["detail"]["field"] == "width_m"
    assert "街宽(width_m)" in r.json()["detail"]["message"]


# ---------- 写与改写同拒；失败停留改前、无半成功 ----------

def test_put_illegal_width_rejected_and_row_untouched(client, seeded):
    create = client.post("/api/vendors", json=_payload(seeded["day_id"], priority=3, stall_width_m=4.0))
    vid = create.json()["id"]
    r = client.put(f"/api/vendors/{vid}",
                   json=_payload(seeded["day_id"], name="改名", priority=3, stall_width_m=4.1))
    assert r.status_code == 422
    after = client.get("/api/vendors").json()
    row = next(x for x in after if x["id"] == vid)
    # 页面停在改前：宽度与名字都不许半成功
    assert row["stall_width_m"] == 4.0
    assert row["name"] == "新摊主"


def test_failed_post_leaves_no_row(client, seeded):
    before = len(client.get("/api/vendors").json())
    r = client.post("/api/vendors", json=_payload(seeded["day_id"], priority=3, stall_width_m=5.0))
    assert r.status_code == 422
    assert len(client.get("/api/vendors").json()) == before


def test_priority_change_revalidated_with_submitted_values(client, seeded):
    """改优先后再保存，必须按提交瞬间交叉规则重检，不许吃改前优先缓存。

    原行 p9/w8 合法；仅把优先改成 3、宽度仍为 8，必须拒（3 档上限 4）。
    """
    create = client.post("/api/vendors", json=_payload(seeded["day_id"], priority=9, stall_width_m=8.0))
    vid = create.json()["id"]
    r = client.put(f"/api/vendors/{vid}",
                   json=_payload(seeded["day_id"], priority=3, stall_width_m=8.0))
    assert r.status_code == 422
    assert r.json()["detail"]["field"] == "stall_width_m"
    row = next(x for x in client.get("/api/vendors").json() if x["id"] == vid)
    assert row["priority"] == 9 and row["stall_width_m"] == 8.0

    # 反向：p3/w4 改优先到 9，宽 4 在 9 档内，可过
    ok = client.put(f"/api/vendors/{vid}",
                    json=_payload(seeded["day_id"], priority=9, stall_width_m=4.0))
    assert ok.status_code == 200
    assert ok.json()["priority"] == 9


def test_legal_rewrite_passes(client, seeded):
    vid = client.post("/api/vendors", json=_payload(seeded["day_id"], priority=1, stall_width_m=4.0)).json()["id"]
    r = client.put(f"/api/vendors/{vid}",
                   json=_payload(seeded["day_id"], priority=6, stall_width_m=6.0))
    assert r.status_code == 200
    assert r.json()["priority"] == 6 and r.json()["stall_width_m"] == 6.0


# ---------- 非法改宽不得记成分配成功 / 空档不够 ----------

def test_illegal_width_not_recorded_as_allocation(client, seeded):
    vid = client.post("/api/vendors", json=_payload(seeded["day_id"], name="阿摊",
                                                    priority=3, stall_width_m=4.0)).json()["id"]
    bad = client.put(f"/api/vendors/{vid}",
                     json=_payload(seeded["day_id"], name="阿摊", priority=3, stall_width_m=4.1))
    assert bad.status_code == 422

    run = client.post(f"/api/allocate/run?segment_id={seeded['segment_id']}").json()
    me = [p for p in run["placements"] if p["vendor_name"] == "阿摊"]
    # 改宽被拒 → 仍按 4.0 正常分配，而不是以 4.1 落色块或被记“空档不够”
    assert len(me) == 1 and me[0]["width_m"] == 4.0
    assert all(x["reason"] == SPACE_SHORTAGE_REASON for x in run["rejected"])


# ---------- 历史开间运行不被改写清掉；主图色块不消失 ----------

def test_rewrite_keeps_allocation_history(client, seeded):
    run1 = client.post(f"/api/allocate/run?segment_id={seeded['segment_id']}").json()
    first_id = run1["id"]
    first_placements = run1["placements"]

    vid = next(v for v in client.get("/api/vendors").json() if v["name"] == "边界三摊")["id"]
    # 合法改写
    ok = client.put(f"/api/vendors/{vid}",
                    json=_payload(seeded["day_id"], name="边界三摊", priority=2, stall_width_m=3.0))
    assert ok.status_code == 200
    # 非法改写
    bad = client.put(f"/api/vendors/{vid}",
                     json=_payload(seeded["day_id"], name="边界三摊", priority=2, stall_width_m=9.0))
    assert bad.status_code == 422

    latest = client.get(f"/api/allocate/latest?segment_id={seeded['segment_id']}").json()
    # 历史 run 没被清，已落色块仍是改前那次
    assert latest["id"] == first_id
    assert latest["placements"] == first_placements


# ---------- 应用层被绕过时，同一套库内规则仍在接口处兜底 ----------

def test_api_still_rejects_when_app_validation_bypassed(client, seeded, monkeypatch):
    monkeypatch.setattr("app.api.vendors.validate_payload", lambda body: None)
    r = client.post("/api/vendors", json=_payload(seeded["day_id"], priority=3, stall_width_m=4.1))
    assert r.status_code == 422
    assert r.json()["detail"]["field"] == "stall_width_m"
    # 兜底失败同样整笔回滚，没有半成功行
    assert all(v["stall_width_m"] != 4.1 for v in client.get("/api/vendors").json())


def test_segment_api_still_rejects_when_app_validation_bypassed(client, seeded, monkeypatch):
    import app.api.segments as seg_mod
    monkeypatch.setattr(seg_mod, "validate_street_width", lambda w: None)
    r = client.post("/api/segments",
                    json={"market_day_id": seeded["day_id"], "name": "零宽街", "width_m": 0})
    assert r.status_code == 422
    assert r.json()["detail"]["field"] == "width_m"


# ---------- 种子数据合法，迁完仍能起服分配 ----------

def test_seed_data_serves_allocation(client, engine):
    # 全新库（无 seeded）：走真实启动流程后补种子
    from sqlalchemy.orm import sessionmaker
    from app.services.seed import seed_if_empty
    db = sessionmaker(bind=engine)()
    seed_if_empty(db)
    db.close()
    # 整服跑一次分配：合法种子必须放得出结果，不被自家 CHECK/校验挡住
    seg_id = client.get("/api/segments").json()[0]["id"]
    r = client.post(f"/api/allocate/run?segment_id={seg_id}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["placements"]) + len(data["rejected"]) == 7
    # 合法种子里没有因规则原因被拒的；拒因只能是“空档不够”
    assert all(x["reason"] == SPACE_SHORTAGE_REASON for x in data["rejected"])
