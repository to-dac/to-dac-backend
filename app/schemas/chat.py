from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ChatSessionResponse(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ChatSessionDetailResponse(ChatSessionResponse):
    messages: list["MessageResponse"] = Field(default_factory=list)


class CreateChatSessionRequest(BaseModel):
    title: str = Field(default="새 채팅", max_length=255)


class MessageResponse(BaseModel):
    id: int
    session_id: int
    role: MessageRole
    content: Optional[str] = None
    status: MessageStatus
    created_at: datetime


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1)
