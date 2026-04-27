"""
Pipeline management — /topics/{topic_name}/pipeline
"""

import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Topic, NarrativeChange, TopicSchedule
from database.session import get_session
from schemas import PipelineStatus, NarrativeChangeOut, ScheduleOut, MessageOut
from pydantic import BaseModel
from scheduler.jobs import scrape_and_update, register_topic_job, scheduler

router = APIRouter(prefix="/topics/{topic_name}", tags=["pipeline"])

# Track running topics to avoid double-trigger
_running: set[str] = set()


@router.post("/run", response_model=PipelineStatus)
async def trigger_pipeline(
    topic_name: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Topic not found")

    if topic_name in _running:
        return PipelineStatus(topic=topic_name, status="running", message="Pipeline already in progress")

    _running.add(topic_name)

    async def _run():
        try:
            await scrape_and_update(topic_name)
        finally:
            _running.discard(topic_name)

    background_tasks.add_task(_run)
    return PipelineStatus(topic=topic_name, status="queued", message="Pipeline queued")


@router.get("/pipeline/status", response_model=PipelineStatus)
async def pipeline_status(topic_name: str):
    status = "running" if topic_name in _running else "idle"
    return PipelineStatus(topic=topic_name, status=status)


@router.get("/changes", response_model=list[NarrativeChangeOut])
async def list_changes(
    topic_name: str,
    undelivered_only: bool = False,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    q = select(NarrativeChange).where(NarrativeChange.topic_id == topic.id)
    if undelivered_only:
        q = q.where(NarrativeChange.delivered == False)  # noqa: E712
    q = q.order_by(NarrativeChange.detected_at.desc()).limit(50)

    result = await session.execute(q)
    return list(result.scalars())


@router.post("/changes/mark-delivered", response_model=MessageOut)
async def mark_changes_delivered(
    topic_name: str,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    result = await session.execute(
        select(NarrativeChange)
        .where(NarrativeChange.topic_id == topic.id, NarrativeChange.delivered == False)  # noqa: E712
    )
    for ch in result.scalars():
        ch.delivered = True
    await session.commit()
    return {"message": "Changes marked as delivered"}


@router.get("/schedule", response_model=ScheduleOut)
async def get_schedule(
    topic_name: str,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    result = await session.execute(
        select(TopicSchedule).where(TopicSchedule.topic_id == topic.id)
    )
    sched = result.scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="No schedule for this topic")

    return ScheduleOut(topic=topic_name, interval_min=sched.interval_min, active=sched.active)


@router.patch("/schedule", response_model=ScheduleOut)
async def update_schedule(
    topic_name: str,
    interval_min: int,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    result = await session.execute(
        select(TopicSchedule).where(TopicSchedule.topic_id == topic.id)
    )
    sched = result.scalar_one_or_none()
    if not sched:
        sched = TopicSchedule(topic_id=topic.id, interval_min=interval_min, active=True)
        session.add(sched)
    else:
        sched.interval_min = interval_min
        sched.active = True

    await session.commit()
    register_topic_job(topic_name, interval_min)
    return ScheduleOut(topic=topic_name, interval_min=interval_min, active=True)


class MonitoringBody(BaseModel):
    active: bool


@router.post("/monitoring", response_model=ScheduleOut)
async def set_monitoring(
    topic_name: str,
    body: MonitoringBody,
    session: AsyncSession = Depends(get_session),
):
    """Start or stop live monitoring (scheduler job) for a topic."""
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    result = await session.execute(
        select(TopicSchedule).where(TopicSchedule.topic_id == topic.id)
    )
    sched = result.scalar_one_or_none()
    interval = sched.interval_min if sched else 30

    if body.active:
        register_topic_job(topic_name, interval)
        # Trigger an immediate run when monitoring starts
        import asyncio
        asyncio.create_task(scrape_and_update(topic_name))
    else:
        job_id = f"scrape_{topic_name.replace(' ', '_').lower()}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

    if sched:
        sched.active = body.active
    else:
        sched = TopicSchedule(topic_id=topic.id, interval_min=interval, active=body.active)
        session.add(sched)
    await session.commit()

    return ScheduleOut(topic=topic_name, interval_min=interval, active=body.active)
