"""
Pydantic response schemas for all API endpoints.
Separate from DB models — controls exactly what the API exposes.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------------

class TopicOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    last_scraped: datetime | None
    active: bool

    class Config:
        from_attributes = True


class TopicCreate(BaseModel):
    name: str
    interval_min: int = 30   # auto-scrape interval (minutes)


# ---------------------------------------------------------------------------
# Article
# ---------------------------------------------------------------------------

class ArticleOut(BaseModel):
    id: int
    url: str
    title: str
    summary: str
    source: str
    source_tier: int
    source_tier_label: str
    trust_label: str
    region: str | None
    published_at: datetime | None
    relevance_score: float
    sentiment: str
    sentiment_score: float
    key_claims: list[str]
    entities_people: list[str]
    entities_locations: list[str]
    entities_orgs: list[str]
    source_type: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Event / Timeline
# ---------------------------------------------------------------------------

class EventSourceOut(BaseModel):
    url: str
    title: str
    source: str
    source_tier: int
    trust_label: str
    region: str | None
    published_at: datetime | None
    sentiment: str

    class Config:
        from_attributes = True


class EventOut(BaseModel):
    id: int
    event_id: str
    headline: str
    summary: str
    event_type: str
    narrative_state: str
    significance_score: float
    first_seen: datetime | None
    last_updated: datetime | None
    source_count: int
    tier1_count: int
    dominant_sentiment: str
    trust_label: str
    locations: list[str]
    people: list[str]
    organizations: list[str]

    class Config:
        from_attributes = True


class EventDetailOut(EventOut):
    sources: list[EventSourceOut] = []


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    topic: str


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Perception
# ---------------------------------------------------------------------------

class RegionalPerceptionOut(BaseModel):
    region: str
    sentiment: str
    sentiment_score: float
    dominant_narrative: str
    key_themes: list[str]
    post_count: int
    platform_breakdown: dict[str, int]
    sample_quotes: list[str]
    analysed_at: str


class PerceptionResponse(BaseModel):
    topic: str
    total_posts: int
    regions: list[RegionalPerceptionOut]


# ---------------------------------------------------------------------------
# Narrative changes
# ---------------------------------------------------------------------------

class NarrativeChangeOut(BaseModel):
    id: int
    change_type: str
    headline: str
    description: str
    significance: float
    detected_at: datetime
    delivered: bool

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Pipeline / scheduler
# ---------------------------------------------------------------------------

class PipelineStatus(BaseModel):
    topic: str
    status: str          # running / queued / idle
    articles_saved: int | None = None
    events_saved: int | None = None
    changes_detected: int | None = None
    message: str = ""


class ScheduleOut(BaseModel):
    topic: str
    interval_min: int
    active: bool


class SchedulerStatusOut(BaseModel):
    running: bool
    jobs: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------

class MessageOut(BaseModel):
    message: str


class PaginatedArticles(BaseModel):
    total: int
    page: int
    limit: int
    items: list[ArticleOut]
