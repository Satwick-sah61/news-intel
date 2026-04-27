"""
Articles feed — /topics/{topic_name}/articles
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Topic, Article
from database.session import get_session
from schemas import ArticleOut, PaginatedArticles

router = APIRouter(prefix="/topics/{topic_name}/articles", tags=["articles"])


def _deserialize_article(a: Article) -> dict:
    """Convert JSON-string fields to lists for the response schema."""
    return {
        "id": a.id,
        "url": a.url,
        "title": a.title,
        "summary": a.summary,
        "source": a.source,
        "source_tier": a.source_tier,
        "source_tier_label": a.source_tier_label,
        "trust_label": a.trust_label,
        "region": a.region,
        "published_at": a.published_at,
        "relevance_score": a.relevance_score,
        "sentiment": a.sentiment,
        "sentiment_score": a.sentiment_score,
        "key_claims": _load_json(a.key_claims),
        "entities_people": _load_json(a.entities_people),
        "entities_locations": _load_json(a.entities_locations),
        "entities_orgs": _load_json(a.entities_orgs),
        "source_type": a.source_type,
    }


def _load_json(val) -> list:
    if isinstance(val, list):
        return val
    try:
        return json.loads(val) if val else []
    except Exception:
        return []


@router.get("", response_model=PaginatedArticles)
async def list_articles(
    topic_name: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sentiment: str | None = None,
    min_relevance: float = Query(0.0, ge=0.0, le=1.0),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    q = select(Article).where(Article.topic_id == topic.id)

    if sentiment:
        q = q.where(Article.sentiment == sentiment)
    if min_relevance > 0:
        q = q.where(Article.relevance_score >= min_relevance)

    # Count
    count_result = await session.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = count_result.scalar_one()

    # Paginate
    q = (
        q.order_by(Article.relevance_score.desc(), Article.published_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = await session.execute(q)
    articles = [_deserialize_article(a) for a in rows.scalars()]

    return {"total": total, "page": page, "limit": limit, "items": articles}
