from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.schemas.chat import (
    ChatSessionDetailResponse,
    ChatSessionResponse,
    CreateChatSessionRequest,
    CreateMessageRequest,
    MessageResponse,
    MessageRole,
    MessageStatus,
)

router = APIRouter()

_now = datetime(2026, 6, 13, 14, 30, tzinfo=timezone.utc)

_MOCK_SESSIONS: dict[int, ChatSessionResponse] = {
    1: ChatSessionResponse(id=1, title="새 채팅", created_at=_now, updated_at=_now),
}

_MOCK_MESSAGES: dict[int, list[MessageResponse]] = {
    1: [
        MessageResponse(
            id=1,
            session_id=1,
            role=MessageRole.USER,
            content="안녕하세요",
            status=MessageStatus.COMPLETED,
            created_at=_now,
        ),
    ],
}

_next_session_id = 2
_next_message_id = 2


def _get_session_or_404(session_id: int) -> ChatSessionResponse:
    session = _MOCK_SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    return session


@router.get("/sessions", response_model=list[ChatSessionResponse], summary="채팅 세션 목록")
async def list_chat_sessions() -> list[ChatSessionResponse]:
    return sorted(_MOCK_SESSIONS.values(), key=lambda s: s.updated_at, reverse=True)


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="채팅 세션 생성",
)
async def create_chat_session(body: CreateChatSessionRequest) -> ChatSessionResponse:
    global _next_session_id

    now = datetime.now(timezone.utc)
    session = ChatSessionResponse(
        id=_next_session_id,
        title=body.title,
        created_at=now,
        updated_at=now,
    )
    _MOCK_SESSIONS[_next_session_id] = session
    _MOCK_MESSAGES[_next_session_id] = []
    _next_session_id += 1
    return session


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetailResponse,
    summary="채팅 세션 상세",
)
async def get_chat_session(session_id: int) -> ChatSessionDetailResponse:
    session = _get_session_or_404(session_id)
    return ChatSessionDetailResponse(
        **session.model_dump(),
        messages=_MOCK_MESSAGES.get(session_id, []),
    )


@router.post(
    "/sessions/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="메시지 전송",
)
async def create_message(session_id: int, body: CreateMessageRequest) -> MessageResponse:
    global _next_message_id

    session = _get_session_or_404(session_id)
    now = datetime.now(timezone.utc)
    message = MessageResponse(
        id=_next_message_id,
        session_id=session_id,
        role=MessageRole.USER,
        content=body.content,
        status=MessageStatus.PENDING,
        created_at=now,
    )
    _MOCK_MESSAGES.setdefault(session_id, []).append(message)
    _MOCK_SESSIONS[session_id] = session.model_copy(update={"updated_at": now})
    _next_message_id += 1
    return message
