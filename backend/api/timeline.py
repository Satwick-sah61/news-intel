"""
Timeline events — /topics/{topic_name}/timeline
"""

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import Topic, Event, Article
from database.session import get_session
from schemas import EventOut, EventDetailOut, EventSourceOut

router = APIRouter(prefix="/topics/{topic_name}/timeline", tags=["timeline"])


def _load_json(val) -> list:
    if isinstance(val, list):
        return val
    try:
        return json.loads(val) if val else []
    except Exception:
        return []


def _event_to_dict(ev: Event) -> dict:
    return {
        "id": ev.id,
        "event_id": ev.event_id,
        "headline": ev.headline,
        "summary": ev.summary,
        "event_type": ev.event_type,
        "narrative_state": ev.narrative_state,
        "significance_score": ev.significance_score,
        "first_seen": ev.first_seen,
        "last_updated": ev.last_updated,
        "source_count": ev.source_count,
        "tier1_count": ev.tier1_count,
        "dominant_sentiment": ev.dominant_sentiment,
        "trust_label": ev.trust_label,
        "locations": _load_json(ev.locations),
        "people": _load_json(ev.people),
        "organizations": _load_json(ev.organizations),
    }


@router.get("", response_model=list[EventOut])
async def list_events(
    topic_name: str,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    result = await session.execute(
        select(Event)
        .where(Event.topic_id == topic.id)
        .order_by(Event.significance_score.desc(), Event.first_seen.desc())
    )
    return [_event_to_dict(ev) for ev in result.scalars()]


@router.get("/{event_id}", response_model=EventDetailOut)
async def get_event(
    topic_name: str,
    event_id: str,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    result = await session.execute(
        select(Event)
        .where(Event.topic_id == topic.id, Event.event_id == event_id)
    )
    ev = result.scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    # Load sources via EventSource join
    from database.models import EventSource
    src_result = await session.execute(
        select(Article)
        .join(EventSource, EventSource.article_id == Article.id)
        .where(EventSource.event_id_fk == ev.id)
    )
    articles = list(src_result.scalars())

    sources = [
        EventSourceOut(
            url=a.url,
            title=a.title,
            source=a.source,
            source_tier=a.source_tier,
            trust_label=a.trust_label,
            region=a.region,
            published_at=a.published_at,
            sentiment=a.sentiment,
        )
        for a in articles
    ]

    data = _event_to_dict(ev)
    data["sources"] = sources
    return data
