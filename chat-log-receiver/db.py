import asyncpg

from config import SUPABASE_DB_URL
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


async def insert_entries(entries: list[dict]) -> int:
    """Bulk inserts chat entries with member resolution and dedup. Returns count of rows actually inserted."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            senders = [e["sender"] for e in entries]
            member_map = await resolve_member_ids(conn, senders)

            rows = [
                (
                    e["id"],
                    e["chatName"],
                    e["chatType"],
                    e["sender"],
                    e["rank"],
                    e["message"],
                    e["timestamp"],
                    member_map.get(e["sender"]),
                )
                for e in entries
            ]

            await conn.executemany(
                """
                INSERT INTO public.chat_log_entries
                    (client_message_id, chat_name, chat_type, sender, rank, message, message_timestamp, member_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (chat_name, client_message_id, sender, message_timestamp) DO NOTHING
                """,
                rows,
            )
            return len(rows)
