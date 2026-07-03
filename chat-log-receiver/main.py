import hmac
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

import db
from config import RECEIVER_AUTH_TOKEN
from models import ChatEntry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chat-log-receiver")

app = FastAPI(title="Chat Log Receiver")


@app.on_event("shutdown")
async def shutdown() -> None:
    await db.close_pool()


def _check_authorization(authorization: str | None) -> None:
    if authorization is None or not hmac.compare_digest(authorization, RECEIVER_AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.post("/submit")
async def submit(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
    _check_authorization(authorization)

    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Malformed JSON body") from exc

    if not isinstance(body, list):
        raise HTTPException(status_code=400, detail="Body must be a JSON array")

    try:
        entries = [ChatEntry.model_validate(item).model_dump() for item in body]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid entry: {exc}") from exc

    if not entries:
        return JSONResponse(status_code=200, content={"received": 0})

    try:
        count = await db.insert_entries(entries)
    except Exception:
        logger.exception("Failed to persist chat entries")
        raise HTTPException(status_code=500, detail="Failed to persist entries")

    return JSONResponse(status_code=200, content={"received": count})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
