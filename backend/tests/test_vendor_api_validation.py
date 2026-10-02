"""接口层拒绝测试——写与改写同拒、提交瞬间重检、无半成功、历史运行不清、
非法改宽不记成分配成功。与直插失败测试分文件。"""
import json

from sqlalchemy import func, select

from app.models.models import AllocationRun, Vendor


# ---------- 合法边 ----------

def test_priority3_width4_accepted(client):
    r = client.post("/api/vendors", json={
        "name": "贴边合法", "stall_width_m": 4.0, "priority": 3})
    assert r.status_code == 200, r.text
    assert r.json()["priority"] == 3 and r.json()["stall_width_m"] == 4.0


def test_priority3_width4point1_rejected_by_api(client):
    r = client.post("/api/vendors", json={
        "name": "越界", "stall_width_m": 4.1, "priority": 3})
    assert r.status_code == 400
    body = r.json()
    # 点名字段与摊主页同一叫法
    assert body["field"] == "stall_width_m"
    assert body["field_label"] == "摊宽"
    assert "4.1" in body["message"]


# ---------- 三个档的越界新建都拒 ----------

def test_each_band_overflow_create_rejected(client):
    for pri, over in [(2, 4.5), (5, 6.2), (8, 8.01)]:
        r = client.post("/api/vendors", json={
            "name": f"p{pri}", "stall_width_m": over, "priority": pri})
        assert r.status_code == 400
        assert r.json()["field"] == "stall_width_m"


def test_invalid_priority_range_rejected(client):
    r = client.post("/api/vendors", json={
        "name": "x", "stall_width_m": 2.0, "priority": 10})
    assert r.status_code == 400
    assert r.json()["field"] == "priority"
    assert r.json()["field_label"] == "优先级"


def test_priority_decimal_rejected(client):
    r = client.post("/api/vendors", json={
        "name": "x", "stall_width_m": 2.0, "priority": 2.5})
    assert r.status_code == 400
    assert r.json()["field_label"] == "优先级"


def test_zero_stall_width_rejected_named(client):
    r = client.post("/api/vendors", json={
        "name": "x", "stall_width_m": 0, "priority": 1})
    assert r.status_code == 400
    body = r.json()
    assert body["field"] == "stall_width_m" and body["field_label"] == "摊宽"


# ---------- 改写与新建同拒 ----------

def test_update_illegal_width_rejected_like_create(client):
    # 种子里挑一个合法摊主（林记糖水 3.0/p1），把摊宽改成 p1 越界的 4.1
    vid = next(v for v in client.get("/api/vendors").json() if v["name"] == "林记糖水")["id"]
    r = client.put(f"/api/vendors/{vid}", json={"stall_width_m": 4.1})
    assert r.status_code == 400
    body = r.json()
    assert body["field"] == "stall_width_m" and body["field_label"] == "摊宽"

    # 被拒时停在改前：库里与再读到的仍是旧值，无半成功写入
    again = client.get("/api/vendors").json()
    row = next(v for v in again if v["id"] == vid)
    assert row["stall_width_m"] == 3.0 and row["priority"] == 1


def test_legal_update_succeeds(client):
    vid = client.get("/api/vendors").json()[0]["id"]
    r = client.put(f"/api/vendors/{vid}", json={"stall_width_m": 4.0, "priority": 3})
    assert r.status_code == 200, r.text
    assert r.json()["stall_width_m"] == 4.0 and r.json()["priority"] == 3


# ---------- 改优先后再保存：按提交瞬间交叉规则重检，禁止吃改前缓存 ----------

def test_priority_change_revalidated_with_submitted_values(client):
    # 林记糖水 3.0/p1：先合法改成 5.5/p4（p4~6 档上限 6，可过）
    vid = next(v for v in client.get("/api/vendors").json() if v["name"] == "林记糖水")["id"]
    r = client.put(f"/api/vendors/{vid}", json={"stall_width_m": 5.5, "priority": 4})
    assert r.status_code == 200, r.text
    # 再只改优先级到 2：5.5 m 对 p1~3 档（上限 4）非法，必须按"新优先级+当前宽度"拒，
    # 不能因为"改之前是 p4 合法"而放行
    r = client.put(f"/api/vendors/{vid}", json={"priority": 2})
    assert r.status_code == 400
    assert r.json()["field"] == "stall_width_m"
    # 库里停在改前（5.5/p4），而不是半成功改成 5.5/p2
    row = next(v for v in client.get("/api/vendors").json() if v["id"] == vid)
    assert row["priority"] == 4 and row["stall_width_m"] == 5.5

    # 反向也成立：4.0/p3 合法；只把优先级改成 1 仍合法
    r = client.put(f"/api/vendors/{vid}", json={"stall_width_m": 4.0, "priority": 3})
    assert r.status_code == 200
    r = client.put(f"/api/vendors/{vid}", json={"priority": 1})
    assert r.status_code == 200


# ---------- 历史开间运行不得被改写清掉；主图色块不消失 ----------

def test_failed_width_edit_keeps_allocation_history(client, db):
    # 先跑出一次分配，留下历史 AllocationRun
    run = client.post("/api/allocate/run?segment_id=1")
    assert run.status_code == 200
    placed_before = len(run.json()["placements"])
    assert placed_before > 0

    session = db()
    runs_before = session.scalar(select(func.count()).select_from(AllocationRun))
    vid = session.scalars(select(Vendor).where(Vendor.name == "林记糖水")).first().id
    session.close()

    # 非法改宽被拒
    r = client.put(f"/api/vendors/{vid}", json={"stall_width_m": 9.9, "priority": 1})
    assert r.status_code == 400
    assert r.json()["field_label"] == "摊宽"

    session = db()
    # 历史开间运行一条不少
    assert session.scalar(select(func.count()).select_from(AllocationRun)) == runs_before
    # 最近一次运行结果（主图已落色块的来源）原封不动
    latest = session.scalars(
        select(AllocationRun).order_by(AllocationRun.id.desc())).first()
    data = json.loads(latest.result_json)
    assert len(data["placements"]) == placed_before
    assert {p["vendor_name"] for p in data["placements"]}
    session.close()

    # /allocate/latest 读到的色块仍在；非法改宽不会被记成一次成功分配
    latest_api = client.get("/api/allocate/latest?segment_id=1").json()
    assert len(latest_api["placements"]) == placed_before


def test_illegal_width_edit_not_recorded_as_allocation(client, db):
    client.post("/api/allocate/run?segment_id=1")
    session = db()
    runs_before = session.scalar(select(func.count()).select_from(AllocationRun))
    vid = session.scalars(select(Vendor)).first().id
    session.close()

    bad = client.put(f"/api/vendors/{vid}", json={"stall_width_m": 5.0, "priority": 1})
    assert bad.status_code == 400
    # 失败理由是摊宽规则，不是"空档不够"
    assert "空档" not in bad.json()["message"]

    session = db()
    assert session.scalar(select(func.count()).select_from(AllocationRun)) == runs_before
    session.close()


# ---------- 街宽 > 0 ----------

def test_segment_width_must_be_positive(client):
    r = client.post("/api/segments", json={"name": "零宽街", "width_m": 0})
    assert r.status_code == 400
    assert r.json()["field"] == "width_m" and r.json()["field_label"] == "街宽"

    seg_id = client.get("/api/segments").json()[0]["id"]
    r = client.put(f"/api/segments/{seg_id}", json={"width_m": -3})
    assert r.status_code == 400
    assert r.json()["field_label"] == "街宽"


# ---------- 种子迁完仍能起服分配 ----------

def test_seeded_data_allocates_cleanly(client):
    r = client.post("/api/allocate/run?segment_id=1")
    assert r.status_code == 200
    data = r.json()
    # 全部摊主要么落下要么进放不下，且没有任何异常
    assert len(data["placements"]) + len(data["rejected"]) == 7
    # 主图有色块
    assert len(data["placements"]) >= 1
