"""Small helpers shared by main.py and admin.py."""
import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from .security import ApiError


def ok(data=None, **kw):
    return JSONResponse({"ok": True, **(data or {}), **kw}, headers={"Cache-Control": "no-store"})


async def body(request: Request, limit=200_000) -> dict:
    raw = await request.body()
    if len(raw) > limit:
        raise ApiError(413, "Request too large")
    try:
        d = json.loads(raw or b"{}")
    except ValueError:
        raise ApiError(400, "Invalid JSON")
    if not isinstance(d, dict):
        raise ApiError(400, "Invalid JSON")
    return d
