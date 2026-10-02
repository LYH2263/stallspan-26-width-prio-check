"""请求体校验失败统一出口：点名字段 + 与摊主页同一叫法，全部落 HTTP 400。"""
from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# 接口字段 -> 页面/提示同一叫法
FIELD_LABELS = {
    "stall_width_m": "摊宽",
    "priority": "优先级",
    "width_m": "街宽",
    "name": "名称",
    "market_day_id": "集日ID",
}


def error_body(field: str, field_label: str, message: str) -> dict:
    return {"field": field, "field_label": field_label, "message": message}


async def request_validation_handler(_request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {"loc": (), "msg": "请求内容无效"}
    loc = first.get("loc") or ()
    field = str(loc[-1]) if loc else "body"
    label = FIELD_LABELS.get(field, field)
    return JSONResponse(
        status_code=400,
        content=error_body(field, label, f"{label}填写无效（{first.get('msg', '格式不符')}）"),
    )
