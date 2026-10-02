"""纯规则边界测试——摊宽 × 优先级交叉规则（不触库、不走接口）。"""
import math

import pytest

from app.services.vendor_rules import (
    LABEL_PRIORITY,
    LABEL_STALL_WIDTH,
    LABEL_STREET_WIDTH,
    RuleViolation,
    ensure_vendor_values,
    max_stall_width,
    validate_street_width,
    validate_vendor_values,
)


def test_band_caps():
    assert max_stall_width(1) == 4.0
    assert max_stall_width(3) == 4.0
    assert max_stall_width(4) == 6.0
    assert max_stall_width(6) == 6.0
    assert max_stall_width(7) == 8.0
    assert max_stall_width(9) == 8.0


def test_legal_edge_priority3_width4_passes():
    # 合法边：优先 3 摊宽 4 可过
    assert validate_vendor_values(4.0, 3) == []
    ensure_vendor_values(4.0, 3)  # 不抛


def test_priority3_width4point1_rejected():
    # 合法边外侧：优先 3 摊宽 4.1 不可
    violations = validate_vendor_values(4.1, 3)
    assert len(violations) == 1
    assert violations[0].field == "stall_width_m"
    assert violations[0].field_label == LABEL_STALL_WIDTH
    assert "4.1" in violations[0].message and "4" in violations[0].message
    with pytest.raises(RuleViolation):
        ensure_vendor_values(4.1, 3)


@pytest.mark.parametrize("priority,width,ok", [
    (1, 4.0, True), (1, 4.0000001, False),
    (2, 4.0, True), (3, 4.0, True),
    (4, 6.0, True), (5, 6.0, True), (6, 6.001, False),
    (7, 8.0, True), (8, 8.0, True), (9, 8.0000001, False),
    (4, 6.0, True), (3, 6.0, False),     # 跨档：p3 拿 p4 档宽度不行
    (6, 8.0, False), (7, 4.0, True),    # 低档宽度放高优先级当然合法
])
def test_cross_band_edges(priority, width, ok):
    violations = validate_vendor_values(width, priority)
    assert (violations == []) is ok
    if not ok:
        assert violations[0].field == "stall_width_m"
        assert violations[0].field_label == LABEL_STALL_WIDTH


@pytest.mark.parametrize("bad_priority", [0, 10, -1, 1.5, 2.0, "3", None, True, False])
def test_priority_must_be_int_1_to_9(bad_priority):
    # bool 是 int 子类，必须单独挡住
    violations = validate_vendor_values(2.0, bad_priority)
    assert any(v.field == "priority" and v.field_label == LABEL_PRIORITY for v in violations)


@pytest.mark.parametrize("bad_width", [0, -0.1, -1, float("nan"), float("inf"), "2", None, True])
def test_stall_width_must_be_positive_number(bad_width):
    violations = validate_vendor_values(bad_width, 1)
    assert any(v.field == "stall_width_m" for v in violations)


def test_both_bad_reports_each_field():
    violations = validate_vendor_values(-1, 99)
    fields = {v.field for v in violations}
    assert fields == {"stall_width_m", "priority"}


@pytest.mark.parametrize("w,ok", [(0.0001, True), (0, False), (-2, False),
                                  (float("nan"), False), (30, True)])
def test_street_width_positive(w, ok):
    v = validate_street_width(w)
    if ok:
        assert v is None
    else:
        assert v.field == "width_m" and v.field_label == LABEL_STREET_WIDTH
