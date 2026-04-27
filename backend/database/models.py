"""
SQLAlchemy models — single source of truth for all persisted data.

Tables:
  topics         — user-subscribed topics
  articles       — classified articles (one row per URL)
  events         — timeline events (one row per real-world occurrence)
  event_sources  — which articles support which event (many-to-many)
  chat_messages  — conversation history per topic
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text,
    DateTime, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
class Topic(Base):
    __tablename__ = "topics"

    id           = Column(Integer, primary_key=True)
    name         = Column(String(200), nullable=False, unique=True)
    created_at   = Column(DateTime, default=_now)
    last_scraped = Column(DateTime, nullable=True)
    active       = Column(Boolean, default=True)

    events            = relationship("Event",   back_populates="topic", cascade="all, delete-orphan")
    articles          = relationship("Article", back_populates="topic", cascade="all, delete-orphan")
    messages          = relationship("ChatMessage", back_populates="topic", cascade="all, delete-orphan")
    narrative_changes = relationship("NarrativeChange", back_populates="topic", cascade="all, delete-orphan")
    schedule          = relationship("TopicSchedule", back_populates="topic", uselist=False, cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("url", name="uq_article_url"),
        Index("ix_article_topic_published", "topic_id", "published_at"),
    )

    id             = Column(Integer, primary_key=True)
    topic_id       = Column(Integer, ForeignKey("topics.id"), nullable=False)
    url            = Column(Text, nullable=False)
    title          = Column(Text, nullable=False)
    content        = Column(Text, default="")
    source         = Column(String(100))
    source_type    = Column(String(20))          # tavily / gdelt / rss
    source_tier    = Column(Integer, default=3)
    source_tier_label = Column(String(50))
    trust_label    = Column(String(50))
    region         = Column(String(100), nullable=True)
    published_at   = Column(DateTime, nullable=True)
    scraped_at     = Column(DateTime, default=_now)

    # Classification
    relevance_score  = Column(Float, default=0.0)
    sentiment        = Column(String(20), default="neutral")
    sentiment_score  = Column(Float, default=0.0)
    summary          = Column(Text, default="")
    key_claims       = Column(Text, default="")   # JSON array stored as text
    entities_people  = Column(Text, default="")   # JSON array
    entities_locations = Column(Text, default="")
    entities_orgs    = Column(Text, default="")

    topic    = relationship("Topic",   back_populates="articles")
    sources  = relationship("EventSource", back_populates="article")


# ---------------------------------------------------------------------------
class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_event_topic_first_seen", "topic_id", "first_seen"),
    )

    id                 = Column(Integer, primary_key=True)
    topic_id           = Column(Integer, ForeignKey("topics.id"), nullable=False)
    event_id           = Column(String(100))          # slug
    headline           = Column(Text, nullable=False)
    summary            = Column(Text, default="")
    event_type         = Column(String(30))           # Military / Diplomatic / etc.
    narrative_state    = Column(String(20))           # Breaking / Developing / etc.
    significance_score = Column(Float, default=0.0)
    first_seen         = Column(DateTime, nullable=True)
    last_updated       = Column(DateTime, nullable=True)
    source_count       = Column(Integer, default=1)
    tier1_count        = Column(Integer, default=0)
    dominant_sentiment = Column(String(20), default="neutral")
    trust_label        = Column(String(50), default="Single Source")
    locations          = Column(Text, default="")     # JSON array
    people             = Column(Text, default="")
    organizations      = Column(Text, default="")
    created_at         = Column(DateTime, default=_now)

    topic   = relationship("Topic", back_populates="events")
    sources = relationship("EventSource", back_populates="event", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
class EventSource(Base):
    """Junction: which articles back which event."""
    __tablename__ = "event_sources"

    id         = Column(Integer, primary_key=True)
    event_id_fk = Column(Integer, ForeignKey("events.id"), nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)

    event   = relationship("Event",   back_populates="sources")
    article = relationship("Article", back_populates="sources")


# ---------------------------------------------------------------------------
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id         = Column(Integer, primary_key=True)
    topic_id   = Column(Integer, ForeignKey("topics.id"), nullable=False)
    role       = Column(String(20), nullable=False)   # user / assistant / system
    content    = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now)

    topic = relationship("Topic", back_populates="messages")


# ---------------------------------------------------------------------------
class NarrativeChange(Base):
    __tablename__ = "narrative_changes"

    id           = Column(Integer, primary_key=True)
    topic_id     = Column(Integer, ForeignKey("topics.id"), nullable=False)
    change_type  = Column(String(50))    # new_event / escalation / state_change / confirmed
    headline     = Column(Text)
    description  = Column(Text)
    significance = Column(Float, default=0.0)
    detected_at  = Column(DateTime, default=_now)
    delivered    = Column(Boolean, default=False)

    topic = relationship("Topic", back_populates="narrative_changes")


# ---------------------------------------------------------------------------
class TopicSchedule(Base):
    __tablename__ = "topic_schedules"

    id           = Column(Integer, primary_key=True)
    topic_id     = Column(Integer, ForeignKey("topics.id"), nullable=False, unique=True)
    interval_min = Column(Integer, default=30)   # scrape every N minutes
    active       = Column(Boolean, default=True)

    topic = relationship("Topic", back_populates="schedule")
