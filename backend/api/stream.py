"""
SSE stream — GET /topics/{topic_name}/stream
Pushes narrative change notifications in real time.
"""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func
from database.models import Topic, NarrativeChange, Article
from database.session import AsyncSessionLocal, get_session

router = APIRouter(prefix="/topics/{topic_name}/stream", tags=["stream"])

POLL_INTERVAL = 10  # seconds between DB polls


async def _event_generator(topic_name: str):
    """Yield SSE-formatted strings. Polls DB for undelivered changes."""
    # Send a heartbeat immediately so the client knows the connection is alive
    yield "event: connected\ndata: {}\n\n"

    last_check = datetime.now(timezone.utc)

    while True:
        await asyncio.sleep(POLL_INTERVAL)

        async with AsyncSessionLocal() as session:
            topic_result = await session.execute(
                select(Topic).where(Topic.name == topic_name)
            )
            topic = topic_result.scalar_one_or_none()
            if not topic:
                yield "event: error\ndata: {\"detail\": \"topic not found\"}\n\n"
                return

            result = await session.execute(
                select(NarrativeChange)
                .where(
                    NarrativeChange.topic_id == topic.id,
                    NarrativeChange.delivered == False,  # noqa: E712
                    NarrativeChange.detected_at > last_check,
                )
                .order_by(NarrativeChange.detected_at)
            )
            changes = list(result.scalars())

            for ch in changes:
                payload = json.dumps({
                    "id": ch.id,
                    "change_type": ch.change_type,
                    "headline": ch.headline,
                    "description": ch.description,
                    "significance": ch.significance,
                    "detected_at": ch.detected_at.isoformat() if ch.detected_at else None,
                })
                yield f"event: narrative_change\ndata: {payload}\n\n"
                ch.delivered = True

            if changes:
                await session.commit()

            # Also emit article + event counts so the UI can show live stats
            art_count = await session.scalar(
                select(func.count()).select_from(Article).where(Article.topic_id == topic.id)
            )
            from database.models import Event
            evt_count = await session.scalar(
                select(func.count()).select_from(Event).where(Event.topic_id == topic.id)
            )
            yield f"event: stats\ndata: {json.dumps({'articles': art_count, 'events': evt_count})}\n\n"

        last_check = datetime.now(timezone.utc)
        yield ": heartbeat\n\n"


@router.get("")
async def stream_changes(topic_name: str):
    return StreamingResponse(
        _event_generator(topic_name),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
