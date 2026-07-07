from typing import AsyncIterator

import asyncpg

from config import SUPABASE_DB_URL
from models import ChatSearchFilters
from rsn import normalize_string

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(SUPABASE_DB_URL, min_size=1, max_size=5)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def resolve_member_ids(conn: asyncpg.Connection, senders: list[str]) -> dict[str, str]:
    """Maps each distinct normalized sender name to a member_id, via member_rsns (current or past RSNs)."""
    normalized_to_original: dict[str, str] = {}
    for sender in senders:
        normalized_to_original[normalize_string(sender)] = sender

    if not normalized_to_original:
        return {}

    rows = await conn.fetch(
        """
        SELECT member_id, rsn
        FROM public.member_rsns
        WHERE lower(replace(replace(replace(replace(rsn, ' ', ''), '_', ''), '-', ''), '.', ''))
            = ANY($1::text[])
        """,
        list(normalized_to_original.keys()),
    )

    result: dict[str, str] = {}
    for row in rows:
        normalized_rsn = normalize_string(row["rsn"])
        original_sender = normalized_to_original.get(normalized_rsn)
        if original_sender is not None:
            result[original_sender] = str(row["member_id"])
    return result


# client_message_id and message_timestamp are generated independently by each staff client
# (client_message_id is RuneLite's local per-client message counter, not a server-assigned id),
# so different clients witnessing the same real chat message never agree on either value.
# Dedup instead treats two rows as the same message if they share (chat_name, sender, message)
# and their message_timestamp falls within this window of each other.
DEDUP_WINDOW = "2 seconds"


async def _is_duplicate(conn: asyncpg.Connection, chat_name: str, sender: str, message: str, timestamp) -> bool:
    return await conn.fetchval(
        f"""
        SELECT EXISTS (
            SELECT 1 FROM public.chat_log_entries
            WHERE chat_name = $1 AND sender = $2 AND message = $3
                AND message_timestamp BETWEEN $4::timestamptz - interval '{DEDUP_WINDOW}'
                                           AND $4::timestamptz + interval '{DEDUP_WINDOW}'
        )
        """,
        chat_name,
        sender,
        message,
        timestamp,
    )


async def _lock_dedup_key(conn: asyncpg.Connection, chat_name: str, sender: str, message: str) -> None:
    """Serializes concurrent inserts for the same logical message across overlapping /submit requests.

    Two staff clients can submit the same real chat message in requests that race each other on
    separate connections; without this, both could pass the not-yet-committed _is_duplicate check
    before either commits. Held for the rest of the transaction (pg_advisory_xact_lock).
    """
    await conn.execute(
        """
        SELECT pg_advisory_xact_lock(
            hashtextextended($1, 0) # hashtextextended($2, 0) # hashtextextended($3, 0)
        )
        """,
        chat_name,
        sender,
        message,
    )


async def insert_entries(entries: list[dict]) -> int:
    """Bulk inserts chat entries with member resolution and dedup. Returns count of rows actually inserted."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            senders = [e["sender"] for e in entries]
            member_map = await resolve_member_ids(conn, senders)

            inserted = 0
            accepted_in_batch: list[tuple] = []
            for e in entries:
                chat_name, sender, message, timestamp = e["chatName"], e["sender"], e["message"], e["timestamp"]

                await _lock_dedup_key(conn, chat_name, sender, message)

                if await _is_duplicate(conn, chat_name, sender, message, timestamp):
                    continue
                if any(
                    a_chat_name == chat_name
                    and a_sender == sender
                    and a_message == message
                    and abs((a_timestamp - timestamp).total_seconds()) <= 2
                    for a_chat_name, a_sender, a_message, a_timestamp in accepted_in_batch
                ):
                    continue

                await conn.execute(
                    """
                    INSERT INTO public.chat_log_entries
                        (client_message_id, chat_name, chat_type, sender, rank, message, message_timestamp, member_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    e["id"],
                    chat_name,
                    e["chatType"],
                    sender,
                    e["rank"],
                    message,
                    timestamp,
                    member_map.get(sender),
                )
                accepted_in_batch.append((chat_name, sender, message, timestamp))
                inserted += 1

            return inserted


async def sweep_duplicates(since_hours: int = 24) -> int:
    """Deletes rows that duplicate an earlier row within DEDUP_WINDOW, restricted to recent history.

    Safety net for the app-side dedup in insert_entries: catches anything that slipped through
    (e.g. a deploy gap where the old code was briefly live, or an as-yet-unknown race). Uses the
    same (chat_name, sender, message) + timestamp-window match, but compares each row against every
    other row directly rather than bucketing, so a duplicate pair can't be missed by falling on
    opposite sides of a fixed time bucket. Keeps the lowest id in each duplicate pair.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            deleted_ids = await conn.fetch(
                f"""
                DELETE FROM public.chat_log_entries newer
                WHERE newer.message_timestamp > now() - interval '{since_hours} hours'
                  AND EXISTS (
                      SELECT 1 FROM public.chat_log_entries older
                      WHERE older.id < newer.id
                        AND older.chat_name = newer.chat_name
                        AND older.sender = newer.sender
                        AND older.message = newer.message
                        AND older.message_timestamp BETWEEN newer.message_timestamp - interval '{DEDUP_WINDOW}'
                                                          AND newer.message_timestamp + interval '{DEDUP_WINDOW}'
                  )
                RETURNING newer.id
                """
            )
            deleted = len(deleted_ids)

            await conn.execute(
                "INSERT INTO public.dedup_sweep_runs (rows_deleted) VALUES ($1)",
                deleted,
            )
            return deleted


SEARCH_PAGE_SIZE = 100

# chat_log_entries.id is a monotonically increasing IDENTITY column assigned in insertion
# order, so keyset pagination on it alone doubles as "most recent first" / "older on scroll up"
# without needing a composite (message_timestamp, id) key -- simpler and just as correct here.


def _build_search_where(
    filters: ChatSearchFilters, params: list, before_id: int | None = None, after_id: int | None = None
) -> str:
    """Appends filter values to params (in place) and returns the WHERE clause body (no leading WHERE)."""
    clauses = ["1=1"]

    if filters.query:
        params.append(filters.query)
        if filters.regex:
            clauses.append(f"message ~ ${len(params)}")
        else:
            clauses.append(f"message ILIKE '%' || ${len(params)} || '%'")

    if filters.member_id is not None:
        params.append(filters.member_id)
        clauses.append(f"member_id = ${len(params)}")

    if filters.exclude_broadcasts:
        # Broadcasts (drops, level-ups, clog unlocks, system notices) are sent with sender
        # set to the clan/chat name itself and rank -2 -- confirmed against production data,
        # see chat-log-receiver phase 2 plan for the query used to verify this.
        clauses.append("NOT (lower(sender) = lower(chat_name) AND rank = -2)")

    if filters.date_from is not None:
        params.append(filters.date_from)
        clauses.append(f"message_timestamp >= ${len(params)}")

    if filters.date_to is not None:
        params.append(filters.date_to)
        clauses.append(f"message_timestamp <= ${len(params)}")

    if before_id is not None:
        params.append(before_id)
        clauses.append(f"chat_log_entries.id < ${len(params)}")

    if after_id is not None:
        params.append(after_id)
        clauses.append(f"chat_log_entries.id > ${len(params)}")

    return " AND ".join(clauses)


_SEARCH_SELECT = """
    SELECT
        chat_log_entries.id,
        chat_log_entries.chat_name,
        chat_log_entries.chat_type,
        chat_log_entries.sender,
        chat_log_entries.rank,
        chat_log_entries.message,
        chat_log_entries.message_timestamp,
        chat_log_entries.member_id,
        ranks.name AS sender_rank_name
    FROM public.chat_log_entries
    LEFT JOIN public.members ON members.id = chat_log_entries.member_id
    LEFT JOIN public.ranks ON ranks.id = members.current_rank_id
"""


async def validate_search_filters(filters: ChatSearchFilters) -> None:
    """Runs the filters' WHERE clause with LIMIT 0 so Postgres validates the regex (if any) up
    front. Used before starting a StreamingResponse, which can't be turned into a clean error
    response once headers are already sent."""
    pool = await get_pool()
    params: list = []
    where = _build_search_where(filters, params)
    query = f"SELECT 1 FROM public.chat_log_entries WHERE {where} LIMIT 0"
    async with pool.acquire() as conn:
        await conn.fetch(query, *params)


async def search_entries(filters: ChatSearchFilters, before_id: int | None = None) -> list[asyncpg.Record]:
    """Returns up to SEARCH_PAGE_SIZE matching entries, newest first.

    `before_id` paginates backward in time (for infinite-scroll-up over older messages);
    omit it for the initial "most recent 100" load.
    """
    pool = await get_pool()
    params: list = []
    where = _build_search_where(filters, params, before_id=before_id)
    query = f"""
        {_SEARCH_SELECT}
        WHERE {where}
        ORDER BY chat_log_entries.id DESC
        LIMIT {SEARCH_PAGE_SIZE}
    """
    async with pool.acquire() as conn:
        return await conn.fetch(query, *params)


async def search_entries_since(filters: ChatSearchFilters, after_id: int) -> list[asyncpg.Record]:
    """Returns all matching entries newer than after_id, oldest first -- used by live mode polling."""
    pool = await get_pool()
    params: list = []
    where = _build_search_where(filters, params, after_id=after_id)
    query = f"""
        {_SEARCH_SELECT}
        WHERE {where}
        ORDER BY chat_log_entries.id ASC
    """
    async with pool.acquire() as conn:
        return await conn.fetch(query, *params)


async def search_entries_all(filters: ChatSearchFilters) -> AsyncIterator[asyncpg.Record]:
    """Streams every matching entry (oldest first), for /api/export -- no page limit.

    Uses a server-side cursor so a large matching set doesn't get materialized in memory at once.
    """
    pool = await get_pool()
    params: list = []
    where = _build_search_where(filters, params)
    query = f"""
        {_SEARCH_SELECT}
        WHERE {where}
        ORDER BY chat_log_entries.id ASC
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            async for record in conn.cursor(query, *params):
                yield record


async def search_members(q: str, limit: int = 20) -> list[asyncpg.Record]:
    """Typeahead: normalized substring match against member_rsns.rsn (current or past), deduped to
    one row per member using their current primary RSN for display."""
    pool = await get_pool()
    normalized_q = normalize_string(q)
    if not normalized_q:
        return []

    query = """
        SELECT DISTINCT ON (member_rsns.member_id)
            member_rsns.member_id,
            primary_rsn.rsn AS display_rsn
        FROM public.member_rsns
        JOIN public.member_rsns AS primary_rsn
            ON primary_rsn.member_id = member_rsns.member_id AND primary_rsn.is_primary = true
        WHERE lower(replace(replace(replace(replace(member_rsns.rsn, ' ', ''), '_', ''), '-', ''), '.', ''))
            LIKE '%' || $1 || '%'
        ORDER BY member_rsns.member_id, primary_rsn.rsn
        LIMIT $2
    """
    async with pool.acquire() as conn:
        return await conn.fetch(query, normalized_q, limit)
