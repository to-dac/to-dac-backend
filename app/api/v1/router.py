from fastapi import APIRouter

from app.api.v1.endpoints import agent, chat

router = APIRouter()

router.include_router(agent.router, prefix="/agent", tags=["agent"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
