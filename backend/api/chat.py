"""
Chat endpoints — /topics/{topic_name}/chat
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Topic, ChatMessage
from database.session import get_session
from schemas import ChatRequest, ChatResponse, ChatMessageOut, MessageOut
from agents.chat_agent import ChatAgent

router = APIRouter(prefix="/topics/{topic_name}/chat", tags=["chat"])
_agent = ChatAgent()


@router.post("", response_model=ChatResponse)
async def send_message(
    topic_name: str,
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Topic not found")

    reply = await _agent.chat(session, topic_name, body.message)
    return {"reply": reply, "topic": topic_name}


@router.get("/history", response_model=list[ChatMessageOut])
async def get_history(
    topic_name: str,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.topic_id == topic.id)
        .order_by(ChatMessage.created_at)
    )
    return list(result.scalars())


@router.delete("/history", response_model=MessageOut)
async def clear_history(
    topic_name: str,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Topic not found")

    await _agent.clear_history(session, topic_name)
    return {"message": "Chat history cleared"}
