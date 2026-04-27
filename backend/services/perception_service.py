"""
Perception Service — aggregates social posts into regional sentiment snapshots.

For each topic, answers: "How does each region of the world see this story?"

Pipeline:
  1. Group posts by detected region (source region_hint + NLP region detection)
  2. GPT-4o-mini analyses each regional batch → sentiment + narrative framing
  3. Returns RegionalPerception objects ready for DB storage or display
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from openai import AsyncOpenAI

from agents.social_agent import SocialPost
from config import settings

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=settings.openai_api_key)

# Canonical regions we track
REGIONS = [
    "United States", "United Kingdom", "Europe",
    "Middle East", "Iran", "Israel",
    "Russia", "China", "India",
    "Pakistan", "Turkey", "Latin America",
    "Global / Other",
]

# Keywords that hint at a post's regional origin
_REGION_KEYWORDS: dict[str, list[str]] = {
    "United States":  ["american", "us ", "usa", "united states", "washington", "white house", "trump", "biden"],
    "United Kingdom": ["uk", "british", "britain", "england", "london", "bbc"],
    "Europe":         ["european", "eu ", "nato", "brussels", "berlin", "paris", "macron"],
    "Middle East":    ["arab", "gulf", "dubai", "saudi", "qatar", "kuwait", "bahrain", "oman"],
    "Iran":           ["iranian", "iran", "tehran", "irgc", "khamenei", "persian"],
    "Israel":         ["israeli", "israel", "tel aviv", "idf", "netanyahu", "jerusalem"],
    "Russia":         ["russian", "russia", "moscow", "kremlin", "putin", "tass"],
    "China":          ["chinese", "china", "beijing", "xi jinping", "pla", "ccp"],
    "India":          ["indian", "india", "new delhi", "modi"],
    "Pakistan":       ["pakistani", "pakistan", "islamabad", "imran"],
    "Turkey":         ["turkish", "turkey", "ankara", "erdogan"],
    "Latin America":  ["latin", "brazil", "mexico", "argentina", "colombia"],
}


@dataclass
class RegionalPerception:
    region: str
    sentiment: str              # positive / negative / neutral
    sentiment_score: float      # -1.0 to 1.0
    dominant_narrative: str     # how this region frames the story (1-2 sentences)
    key_themes: list[str]       # recurring themes in this region's posts
    post_count: int
    platform_breakdown: dict    # {reddit: N, youtube: N, twitter: N}
    sample_quotes: list[str]    # up to 3 representative snippets
    analysed_at: str


async def analyse_perception(
    posts: list[SocialPost],
    topic: str,
) -> list[RegionalPerception]:
    """
    Group posts by region, analyse each region's sentiment and narrative.
    Returns list of RegionalPerception sorted by post_count desc.
    """
    if not posts:
        return []

    # Group by region
    groups: dict[str, list[SocialPost]] = {r: [] for r in REGIONS}
    for post in posts:
        region = _detect_region(post)
        groups[region].append(post)

    # Filter empty regions
    active = {r: ps for r, ps in groups.items() if ps}

    # Analyse each region concurrently (GPT-4o-mini, max 6 parallel)
    sem = asyncio.Semaphore(6)

    async def _analyse_one(region: str, region_posts: list[SocialPost]):
        async with sem:
            return await _analyse_region(region, region_posts, topic)

    results = await asyncio.gather(
        *[_analyse_one(r, ps) for r, ps in active.items()],
        return_exceptions=True,
    )

    perceptions = []
    for result in results:
        if isinstance(result, RegionalPerception):
            perceptions.append(result)
        elif isinstance(result, Exception):
            logger.warning(f"Region analysis failed: {result}")

    perceptions.sort(key=lambda p: -p.post_count)
    return perceptions


async def _analyse_region(
    region: str,
    posts: list[SocialPost],
    topic: str,
) -> RegionalPerception:
    # Build platform breakdown
    platform_breakdown: dict[str, int] = {}
    for p in posts:
        platform_breakdown[p.platform] = platform_breakdown.get(p.platform, 0) + 1

    # Sample up to 10 posts for LLM (keep tokens low)
    sample = posts[:10]
    posts_text = "\n\n".join(
        f"[{p.platform.upper()}] {p.title}\n{p.content[:400]}"
        for p in sample
        if p.title or p.content
    )

    if not posts_text.strip():
        return RegionalPerception(
            region=region,
            sentiment="neutral",
            sentiment_score=0.0,
            dominant_narrative="Insufficient data to determine regional narrative.",
            key_themes=[],
            post_count=len(posts),
            platform_breakdown=platform_breakdown,
            sample_quotes=[],
            analysed_at=datetime.now(timezone.utc).isoformat(),
        )

    prompt = f"""Analyse how people in/from "{region}" are discussing the topic: "{topic}"

Based on these social media posts from {region}:

{posts_text}

Return JSON with exactly these fields:
- sentiment: "positive", "negative", or "neutral" (overall tone toward the topic/situation)
- sentiment_score: float -1.0 (very negative) to 1.0 (very positive)
- dominant_narrative: 1-2 sentences describing how this region frames/understands the story
- key_themes: list of 3-5 recurring themes or concerns in the posts
- sample_quotes: list of up to 3 short verbatim or paraphrased quotes that best represent the regional view

No markdown. JSON only."""

    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    data = json.loads(resp.choices[0].message.content)

    return RegionalPerception(
        region=region,
        sentiment=data.get("sentiment", "neutral"),
        sentiment_score=float(data.get("sentiment_score", 0.0)),
        dominant_narrative=data.get("dominant_narrative", ""),
        key_themes=data.get("key_themes", [])[:5],
        post_count=len(posts),
        platform_breakdown=platform_breakdown,
        sample_quotes=data.get("sample_quotes", [])[:3],
        analysed_at=datetime.now(timezone.utc).isoformat(),
    )


def _detect_region(post: SocialPost) -> str:
    """Assign a post to a region using region_hint and keyword matching."""
    # Use explicit hint if available
    if post.region_hint:
        for region, keywords in _REGION_KEYWORDS.items():
            if any(post.region_hint.lower() in kw or kw in post.region_hint.lower()
                   for kw in keywords):
                return region

    # Fall back to content matching
    text = f"{post.title} {post.content}".lower()
    scores: dict[str, int] = {}
    for region, keywords in _REGION_KEYWORDS.items():
        scores[region] = sum(1 for kw in keywords if kw in text)

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Global / Other"
