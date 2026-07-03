import asyncio
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

DEDUP_SWEEP_INTERVAL_SECONDS = 24 * 60 * 60

_dedup_sweep_task: asyncio.Task | None = None


async def _dedup_sweep_loop() -> None:
    """Daily safety net: re-checks the last 24h of messages for duplicates the app-side dedup
    in insert_entries missed (e.g. a deploy gap, or an unforeseen race), so historical data
    doesn't quietly accumulate cruft between manual spot-checks."""
    while True:
        try:
            deleted = await db.sweep_duplicates(since_hours=24)
            if deleted:
                logger.info("Dedup sweep removed %d duplicate row(s)", deleted)
        except Exception:
            logger.exception("Dedup sweep failed")
        await asyncio.sleep(DEDUP_SWEEP_INTERVAL_SECONDS)


@app.on_event("startup")
async def startup() -> None:
    global _dedup_sweep_task
    _dedup_sweep_task = asyncio.create_task(_dedup_sweep_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    if _dedup_sweep_task is not None:
        _dedup_sweep_task.cancel()
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
