from datetime import datetime

from pydantic import BaseModel, Field


class ChatEntry(BaseModel):
    id: int
    timestamp: datetime
    chatType: str
    chatName: str
    sender: str
    rank: int
    message: str = Field(max_length=2000)
