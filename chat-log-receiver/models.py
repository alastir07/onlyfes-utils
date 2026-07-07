from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChatEntry(BaseModel):
    id: int
    timestamp: datetime
    chatType: str
    chatName: str
    sender: str
    rank: int
    message: str = Field(max_length=2000)


class ChatSearchFilters(BaseModel):
    """Parsed/validated form of the query params accepted by /api/search and /api/export."""

    query: str | None = None
    regex: bool = False
    member_id: UUID | None = None
    exclude_broadcasts: bool = False
    date_from: datetime | None = None
    date_to: datetime | None = None


class ChatSearchResult(BaseModel):
    id: int
    chat_name: str
    chat_type: str
    sender: str
    rank: int
    message: str
    message_timestamp: datetime
    member_id: UUID | None
    sender_rank_name: str | None


class ChatSearchPage(BaseModel):
    results: list[ChatSearchResult]
    next_cursor: str | None


class MemberSearchResult(BaseModel):
    member_id: UUID
    display_rsn: str
