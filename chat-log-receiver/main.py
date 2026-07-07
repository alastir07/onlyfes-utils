import asyncio
import csv
import hmac
import io
import logging
from datetime import datetime
from uuid import UUID

import asyncpg
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import db
from config import RECEIVER_AUTH_TOKEN
from models import ChatEntry, ChatSearchFilters, ChatSearchPage, ChatSearchResult, MemberSearchResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chat-log-receiver")

app = FastAPI(title="Chat Log Receiver")
app.mount("/static", StaticFiles(directory="static"), name="static")

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


def _record_to_result(record: asyncpg.Record) -> ChatSearchResult:
    return ChatSearchResult(
        id=record["id"],
        chat_name=record["chat_name"],
        chat_type=record["chat_type"],
        sender=record["sender"],
        rank=record["rank"],
        message=record["message"],
        message_timestamp=record["message_timestamp"],
        member_id=record["member_id"],
        sender_rank_name=record["sender_rank_name"],
    )


def _search_filters(
    q: str | None,
    regex: bool,
    member_id: UUID | None,
    exclude_broadcasts: bool,
    date_from: datetime | None,
    date_to: datetime | None,
) -> ChatSearchFilters:
    return ChatSearchFilters(
        query=q,
        regex=regex,
        member_id=member_id,
        exclude_broadcasts=exclude_broadcasts,
        date_from=date_from,
        date_to=date_to,
    )


@app.get("/api/search")
async def api_search(
    q: str | None = Query(default=None),
    regex: bool = Query(default=False),
    member_id: UUID | None = Query(default=None),
    exclude_broadcasts: bool = Query(default=False),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    before_id: int | None = Query(default=None),
    after_id: int | None = Query(default=None),
) -> ChatSearchPage:
    filters = _search_filters(q, regex, member_id, exclude_broadcasts, date_from, date_to)

    try:
        if after_id is not None:
            records = await db.search_entries_since(filters, after_id=after_id)
        else:
            records = await db.search_entries(filters, before_id=before_id)
    except asyncpg.exceptions.InvalidRegularExpressionError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}") from exc

    results = [_record_to_result(r) for r in records]
    next_cursor = str(results[-1].id) if (after_id is None and len(results) == db.SEARCH_PAGE_SIZE) else None
    return ChatSearchPage(results=results, next_cursor=next_cursor)


@app.get("/api/export")
async def api_export(
    q: str | None = Query(default=None),
    regex: bool = Query(default=False),
    member_id: UUID | None = Query(default=None),
    exclude_broadcasts: bool = Query(default=False),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> StreamingResponse:
    filters = _search_filters(q, regex, member_id, exclude_broadcasts, date_from, date_to)

    try:
        # Force Postgres to validate the regex before the streaming response starts, since a
        # StreamingResponse can't be turned into a clean 400 once headers have already been sent.
        await db.validate_search_filters(filters)
    except asyncpg.exceptions.InvalidRegularExpressionError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}") from exc

    async def stream_csv():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["timestamp", "chat_name", "sender", "rank", "sender_rank_name", "message", "member_id"]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        async for record in db.search_entries_all(filters):
            writer.writerow(
                [
                    record["message_timestamp"].isoformat(),
                    record["chat_name"],
                    record["sender"],
                    record["rank"],
                    record["sender_rank_name"] or "",
                    record["message"],
                    str(record["member_id"]) if record["member_id"] else "",
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    return StreamingResponse(
        stream_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=chat_log_export.csv"},
    )


@app.get("/api/members/search")
async def api_members_search(q: str = Query(min_length=1)) -> list[MemberSearchResult]:
    records = await db.search_members(q)
    return [MemberSearchResult(member_id=r["member_id"], display_rsn=r["display_rsn"]) for r in records]


@app.get("/")
async def index():
    return FileResponse("static/index.html")
