"""
Perception endpoints — /topics/{topic_name}/perception
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Topic
from database.session import get_session
from schemas import PerceptionResponse
from agents.social_agent import SocialAgent
from services.perception_service import analyse_perception

router = APIRouter(prefix="/topics/{topic_name}/perception", tags=["perception"])


@router.get("", response_model=PerceptionResponse)
async def get_perception(
    topic_name: str,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Topic not found")

    social_agent = SocialAgent()
    try:
        posts = await social_agent.fetch(topic_name)
    finally:
        await social_agent.close()

    if not posts:
        return PerceptionResponse(topic=topic_name, total_posts=0, regions=[])

    regions = await analyse_perception(posts, topic_name)

    return PerceptionResponse(
        topic=topic_name,
        total_posts=len(posts),
        regions=[
            {
                "region": r.region,
                "sentiment": r.sentiment,
                "sentiment_score": r.sentiment_score,
                "dominant_narrative": r.dominant_narrative,
                "key_themes": r.key_themes,
                "post_count": r.post_count,
                "platform_breakdown": r.platform_breakdown,
                "sample_quotes": r.sample_quotes,
                "analysed_at": r.analysed_at,
            }
            for r in regions
        ],
    )
