"""摊主优先级 × 摊宽交叉规则 —— 应用层与数据库层的唯一共同来源。

档位（摊宽上限，米）：
  优先 1-3 → 摊宽 ≤ 4
  优先 4-6 → 摊宽 ≤ 6
  优先 7-9 → 摊宽 ≤ 8
另：街宽 > 0、摊宽 > 0、优先级为 1-9 的整数。

API 入参校验（app/api/vendors.py）与数据库 CHECK（app/models/models.py，
启动迁移也用同一段 SQL）都从本文件取档位与字段名，不得在别处另写一份。
"""
from __future__ import annotations

# (优先级下限, 优先级上限, 摊宽上限m) —— 唯一档位定义
PRIORITY_WIDTH_CAPS: tuple[tuple[int, int, float], ...] = (
    (1, 3, 4.0),
    (4, 6, 6.0),
    (7, 9, 8.0),
)
PRIORITY_MIN = 1
PRIORITY_MAX = 9

# 接口点名字段 == 摊主页提示叫法，前后端共用这几个 key
FIELD_STALL_WIDTH = "stall_width_m"
FIELD_PRIORITY = "priority"
FIELD_STREET_WIDTH = "width_m"

# 摊主页/接口统一展示名
LABEL_STALL_WIDTH = "摊宽(stall_width_m)"
LABEL_PRIORITY = "优先级(priority)"
LABEL_STREET_WIDTH = "街宽(width_m)"

# 与分配引擎的“空档不够”严格区分，非法改宽禁止套这个原因
SPACE_SHORTAGE_REASON = "无连续空档可放下且不跨越挡柱"

_EPS = 1e-9


class RuleViolation(Exception):
    """点名字段的规则冲突；field 取值必须是上面的 FIELD_* 常量。"""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


def cap_for_priority(priority: int) -> float | None:
    for lo, hi, cap in PRIORITY_WIDTH_CAPS:
        if lo <= priority <= hi:
            return cap
    return None


def validate_vendor_rules(priority, stall_width_m) -> None:
    """按“提交瞬间”的 priority/width 校验，不读任何缓存。失败抛 RuleViolation。"""
    # 优先级：1-9 整数（入参经 pydantic 为数字，bool/非整数一律拒）
    p_ok = isinstance(priority, int) and not isinstance(priority, bool)
    p_val = int(priority) if p_ok else None
    if not p_ok or not (PRIORITY_MIN <= p_val <= PRIORITY_MAX):
        raise RuleViolation(
            FIELD_PRIORITY,
            f"{LABEL_PRIORITY}必须为{PRIORITY_MIN}到{PRIORITY_MAX}的整数，当前：{priority}",
        )

    # 摊宽：数字且 > 0（NaN 直接拒）
    try:
        w = float(stall_width_m)
    except (TypeError, ValueError):
        raise RuleViolation(FIELD_STALL_WIDTH, f"{LABEL_STALL_WIDTH}必须为数字，当前：{stall_width_m}")
    if w != w or w <= 0:
        raise RuleViolation(FIELD_STALL_WIDTH, f"{LABEL_STALL_WIDTH}必须大于0，当前：{stall_width_m}")

    cap = cap_for_priority(p_val)
    if w > cap + _EPS:
        bands = "，".join(f"优先{lo}-{h}≤{g:g}" for lo, h, g in PRIORITY_WIDTH_CAPS)
        raise RuleViolation(
            FIELD_STALL_WIDTH,
            f"{LABEL_STALL_WIDTH} {w:g}m 超过{LABEL_PRIORITY}={p_val} 档上限 {cap:g}m（{bands}）",
        )


def validate_street_width(width_m) -> None:
    try:
        w = float(width_m)
    except (TypeError, ValueError):
        raise RuleViolation(FIELD_STREET_WIDTH, f"{LABEL_STREET_WIDTH}必须为数字，当前：{width_m}")
    if w != w or w <= 0:
        raise RuleViolation(FIELD_STREET_WIDTH, f"{LABEL_STREET_WIDTH}必须大于0，当前：{width_m}")


def vendor_check_sql(stall_col: str = FIELD_STALL_WIDTH, pri_col: str = FIELD_PRIORITY) -> str:
    """生成与 validate_vendor_rules 同档位的库内 CHECK 片段（PostgreSQL / SQLite 通用）。"""
    whens = " ".join(
        f"WHEN {pri_col} BETWEEN {lo} AND {hi} THEN {stall_col} <= {cap}"
        for lo, hi, cap in PRIORITY_WIDTH_CAPS
    )
    return (
        f"({stall_col} > 0 AND {pri_col} BETWEEN {PRIORITY_MIN} AND {PRIORITY_MAX} "
        # 显式整数约束（SQLite 的 INTEGER 亲和不挡 2.5；PG 列类型本就是 integer）
        f"AND {pri_col} = CAST({pri_col} AS INTEGER) "
        # CASE 各分支必须同为布尔：ELSE 用 (1=0)，否则 PG 报 boolean/integer 类型不匹配
        f"AND (CASE {whens} ELSE (1=0) END))"
    )


def segment_check_sql(width_col: str = FIELD_STREET_WIDTH) -> str:
    return f"({width_col} > 0)"
