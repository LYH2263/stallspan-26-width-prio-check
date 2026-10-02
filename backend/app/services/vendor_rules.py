"""摊主 摊宽 × 优先级 交叉规则——应用层与数据库层共用的同一套规则。

边界：
- 优先级 1~3：摊宽上限 4 m
- 优先级 4~6：摊宽上限 6 m
- 优先级 7~9：摊宽上限 8 m
另：摊宽 > 0、街宽 > 0、优先级为 1~9 整数。

合法边：优先 3 摊宽 4 可过；优先 3 摊宽 4.1 不可。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# 字段在接口错误与摊主页提示中的同一叫法
LABEL_STALL_WIDTH = "摊宽"
LABEL_PRIORITY = "优先级"
LABEL_STREET_WIDTH = "街宽"


@dataclass(frozen=True)
class RuleViolation(Exception):
    """规则失败。field 点名字段名，field_label 是接口与页面共用的同一叫法。"""

    field: str
    field_label: str
    message: str

    def __str__(self) -> str:
        return self.message


def max_stall_width(priority: int) -> float:
    """当前优先级对应的摊宽上限。priority 必须是 1~9 整数。"""
    if priority in (1, 2, 3):
        return 4.0
    if priority in (4, 5, 6):
        return 6.0
    if priority in (7, 8, 9):
        return 8.0
    raise AssertionError(f"unknown priority {priority!r}")


def is_valid_priority(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 9


def validate_vendor_values(stall_width_m, priority) -> list[RuleViolation]:
    """校验单个摊主的 摊宽/优先级，返回全部违规（可同时报多个）。"""
    violations: list[RuleViolation] = []
    if not is_valid_priority(priority):
        violations.append(RuleViolation(
            field="priority",
            field_label=LABEL_PRIORITY,
            message="优先级须为 1 到 9 的整数",
        ))
    width_ok = (
        isinstance(stall_width_m, (int, float))
        and not isinstance(stall_width_m, bool)
        and math.isfinite(float(stall_width_m))
        and float(stall_width_m) > 0
    )
    if not width_ok:
        violations.append(RuleViolation(
            field="stall_width_m",
            field_label=LABEL_STALL_WIDTH,
            message="摊宽须为大于 0 的数（米）",
        ))
    # 交叉规则：只有优先级本身合法时才比对上限，避免级联误报
    if is_valid_priority(priority) and width_ok:
        cap = max_stall_width(priority)
        if float(stall_width_m) > cap:
            violations.append(RuleViolation(
                field="stall_width_m",
                field_label=LABEL_STALL_WIDTH,
                message=(
                    f"摊宽超限：优先级 {priority}（{_priority_band(priority)}）"
                    f"摊宽不得超过 {cap:g} m，当前 {float(stall_width_m):g} m"
                ),
            ))
    return violations


def _priority_band(priority: int) -> str:
    if priority in (1, 2, 3):
        return "1 到 3"
    if priority in (4, 5, 6):
        return "4 到 6"
    return "7 到 9"


def validate_street_width(width_m) -> RuleViolation | None:
    """街宽须大于 0。"""
    if (not isinstance(width_m, (int, float)) or isinstance(width_m, bool)
            or not math.isfinite(float(width_m)) or float(width_m) <= 0):
        return RuleViolation(
            field="width_m",
            field_label=LABEL_STREET_WIDTH,
            message="街宽须为大于 0 的数（米）",
        )
    return None


def ensure_vendor_values(stall_width_m, priority) -> None:
    """有任一违规即抛出第一个。供 ORM 事件/写接口在提交瞬间重检。"""
    violations = validate_vendor_values(stall_width_m, priority)
    if violations:
        raise violations[0]


# ---- 数据库层 CHECK 表达式（与上面函数同一套阈值，改阈值两处同改） ----

# 优先级 1~9 整数；摊宽 > 0；交叉上限：
#   优先级 1~3 摊宽 <= 4；4~6 <= 6；7~9 <= 8
# priority = CAST(priority AS INTEGER) 在 SQLite 动态类型下也能挡住小数直插；
# PG 的 INTEGER 列本身只收整数，该式恒真、无害。
VENDOR_CHECK_SQL = (
    "priority BETWEEN 1 AND 9"
    " AND priority = CAST(priority AS INTEGER)"
    " AND stall_width_m > 0"
    " AND stall_width_m <= CASE"
    "     WHEN priority BETWEEN 1 AND 3 THEN 4"
    "     WHEN priority BETWEEN 4 AND 6 THEN 6"
    "     ELSE 8"
    " END"
)

# 街宽 > 0
SEGMENT_CHECK_SQL = "width_m > 0"
