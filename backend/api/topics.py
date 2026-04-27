"""
Topics CRUD — /topics
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Topic, TopicSchedule
from database.session import get_session
from schemas import TopicOut, TopicCreate, MessageOut
from scheduler.jobs import register_topic_job, scheduler

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("", response_model=list[TopicOut])
async def list_topics(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Topic).order_by(Topic.created_at.desc()))
    return list(result.scalars())


@router.post("", response_model=TopicOut, status_code=201)
async def create_topic(body: TopicCreate, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Topic).where(Topic.name == body.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Topic already exists")

    topic = Topic(name=body.name)
    session.add(topic)
    await session.flush()

    sched = TopicSchedule(topic_id=topic.id, interval_min=body.interval_min, active=True)
    session.add(sched)
    await session.commit()
    await session.refresh(topic)

    register_topic_job(topic.name, body.interval_min)
    return topic


@router.get("/{topic_name}", response_model=TopicOut)
async def get_topic(topic_name: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.delete("/{topic_name}", response_model=MessageOut)
async def delete_topic(topic_name: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    job_id = f"scrape_{topic_name.replace(' ', '_').lower()}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    await session.delete(topic)
    await session.commit()
    return {"message": f"Topic '{topic_name}' deleted"}
