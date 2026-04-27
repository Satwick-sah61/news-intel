"""
Persists scrape + classify + timeline output into the database.
Handles upserts so re-running a scrape doesn't duplicate data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Topic, Article, Event, EventSource

if TYPE_CHECKING:
    # Only imported for type hints — avoids circular import at runtime
    from agents.classification_agent import ClassifiedArticle
    from agents.timeline_agent import TimelineEvent


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ", "%Y%m%d%H%M%S"):
        try:
            dt = datetime.strptime(s[:19], fmt[:len(s[:19])])
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def get_or_create_topic(session: AsyncSession, name: str) -> Topic:
    result = await session.execute(select(Topic).where(Topic.name == name))
    topic = result.scalar_one_or_none()
    if not topic:
        topic = Topic(name=name)
        session.add(topic)
        await session.flush()
    return topic


async def save_articles(
    session: AsyncSession,
    topic: Topic,
    articles: list[ClassifiedArticle],
) -> dict[str, Article]:
    """
    Upsert articles. Returns {url: Article} map for event linking.
    Skips articles that already exist (same URL).
    """
    url_to_article: dict[str, Article] = {}

    # Fetch existing URLs for this topic in one query
    existing = await session.execute(
        select(Article).where(Article.topic_id == topic.id)
    )
    existing_map = {a.url: a for a in existing.scalars()}

    for ca in articles:
        if ca.url in existing_map:
            url_to_article[ca.url] = existing_map[ca.url]
            continue

        db_article = Article(
            topic_id=topic.id,
            url=ca.url,
            title=ca.title,
            content=ca.content,
            source=ca.source,
            source_type=ca.source_type,
            source_tier=ca.source_tier,
            source_tier_label=ca.source_tier_label,
            trust_label=ca.trust_label,
            region=ca.region,
            published_at=_parse_dt(ca.published_at),
            relevance_score=ca.relevance_score,
            sentiment=ca.sentiment,
            sentiment_score=ca.sentiment_score,
            summary=ca.summary,
            key_claims=json.dumps(ca.key_claims),
            entities_people=json.dumps(ca.entities.get("people", [])),
            entities_locations=json.dumps(ca.entities.get("locations", [])),
            entities_orgs=json.dumps(ca.entities.get("organizations", [])),
        )
        session.add(db_article)
        url_to_article[ca.url] = db_article

    await session.flush()
    return url_to_article


async def save_events(
    session: AsyncSession,
    topic: Topic,
    events: list[TimelineEvent],
    url_to_article: dict[str, Article],
) -> list[Event]:
    """
    Insert new events. Each TimelineEvent becomes one Event row with
    EventSource rows linking to the backing articles.
    """
    saved = []

    for ev in events:
        db_event = Event(
            topic_id=topic.id,
            event_id=ev.event_id,
            headline=ev.headline,
            summary=ev.summary,
            event_type=ev.event_type,
            narrative_state=ev.narrative_state,
            significance_score=ev.significance_score,
            first_seen=_parse_dt(ev.first_seen),
            last_updated=_parse_dt(ev.last_updated),
            source_count=ev.source_count,
            tier1_count=ev.tier1_count,
            dominant_sentiment=ev.dominant_sentiment,
            trust_label=ev.trust_label,
            locations=json.dumps(ev.locations),
            people=json.dumps(ev.people),
            organizations=json.dumps(ev.organizations),
        )
        session.add(db_event)
        await session.flush()

        for src in ev.sources:
            article = url_to_article.get(src.url)
            if article and article.id:
                session.add(EventSource(
                    event_id_fk=db_event.id,
                    article_id=article.id,
                ))

        saved.append(db_event)

    await session.flush()
    return saved


async def mark_topic_scraped(session: AsyncSession, topic: Topic):
    topic.last_scraped = datetime.now(timezone.utc)
    await session.flush()


async def load_timeline(
    session: AsyncSession,
    topic_name: str,
) -> list[Event]:
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        return []

    result = await session.execute(
        select(Event)
        .where(Event.topic_id == topic.id)
        .order_by(Event.first_seen)
    )
    return list(result.scalars())


async def load_articles_for_topic(
    session: AsyncSession,
    topic_name: str,
    limit: int = 200,
) -> list[Article]:
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        return []

    result = await session.execute(
        select(Article)
        .where(Article.topic_id == topic.id)
        .order_by(Article.relevance_score.desc(), Article.published_at.desc())
        .limit(limit)
    )
    return list(result.scalars())
