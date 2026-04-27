"""
Chat Agent — multi-turn Q&A grounded in the stored timeline + articles.

How it works:
  1. User asks a question about a topic
  2. Agent retrieves the most relevant events + articles from DB (RAG)
  3. Builds a context window from that retrieved content
  4. GPT-4o answers with citations, grounded only in retrieved data
  5. Conversation history is preserved for multi-turn dialogue

Model choice:
  - GPT-4o   for chat (reasoning + synthesis)
  - GPT-4o-mini for retrieval relevance scoring (cheap fast filter)
"""

import json
import logging
from datetime import datetime

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Event, Article, ChatMessage, Topic
from config import settings

# storage_service imported lazily inside methods to avoid circular import
# (storage_service → agents, agents/__init__ → chat_agent → storage_service)

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=settings.openai_api_key)

MAX_HISTORY = 12          # message pairs kept in context
MAX_CONTEXT_EVENTS = 15   # events fed to GPT-4o per turn
MAX_CONTEXT_ARTICLES = 20 # articles fed to GPT-4o per turn


class ChatAgent:

    async def chat(
        self,
        session: AsyncSession,
        topic_name: str,
        user_message: str,
    ) -> str:
        """
        Process one user turn. Saves both user message and assistant reply to DB.
        Returns the assistant's reply string.
        """
        # 1. Load stored context (lazy import avoids circular dependency)
        from services.storage_service import load_timeline, load_articles_for_topic
        events   = await load_timeline(session, topic_name)
        articles = await load_articles_for_topic(session, topic_name, limit=200)

        if not events and not articles:
            return (
                f"I don't have any stored news for the topic '{topic_name}' yet. "
                f"Run `python cli.py timeline {topic_name}` first to populate the database."
            )

        # 2. Retrieve relevant subset via keyword + recency scoring
        relevant_events   = _rank_events(events, user_message)[:MAX_CONTEXT_EVENTS]
        relevant_articles = _rank_articles(articles, user_message)[:MAX_CONTEXT_ARTICLES]

        # 3. Load conversation history for this topic
        history = await _load_history(session, topic_name)

        # 4. Build system prompt
        system_prompt = _build_system_prompt(topic_name, relevant_events, relevant_articles)

        # 5. Build messages list
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history[-MAX_HISTORY:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})

        # 6. Call GPT-4o
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.3,
            max_tokens=1200,
        )
        reply = resp.choices[0].message.content

        # 7. Persist both turns
        await _save_message(session, topic_name, "user", user_message)
        await _save_message(session, topic_name, "assistant", reply)
        await session.commit()

        return reply

    async def clear_history(self, session: AsyncSession, topic_name: str):
        from sqlalchemy import select, delete
        result = await session.execute(
            select(Topic).where(Topic.name == topic_name)
        )
        topic = result.scalar_one_or_none()
        if topic:
            from database.models import ChatMessage
            await session.execute(
                delete(ChatMessage).where(ChatMessage.topic_id == topic.id)
            )
            await session.commit()


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------

def _build_system_prompt(
    topic_name: str,
    events: list[Event],
    articles: list[Article],
) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    events_text = ""
    for ev in events:
        locs = _safe_json(ev.locations)
        people = _safe_json(ev.people)
        events_text += (
            f"[{ev.event_type} | {ev.narrative_state} | {ev.trust_label} | "
            f"Sources: {ev.source_count} (T1: {ev.tier1_count})]\n"
            f"Date: {str(ev.first_seen)[:10] if ev.first_seen else 'unknown'}\n"
            f"Headline: {ev.headline}\n"
            f"Summary: {ev.summary}\n"
            f"Locations: {', '.join(locs) or '—'}\n"
            f"People: {', '.join(people) or '—'}\n\n"
        )

    articles_text = ""
    for a in articles[:MAX_CONTEXT_ARTICLES]:
        articles_text += (
            f"[{a.source} | Tier {a.source_tier} | {a.region or '—'} | "
            f"Relevance: {a.relevance_score:.2f} | {a.sentiment}]\n"
            f"Title: {a.title}\n"
            f"Summary: {a.summary}\n"
            f"Key claims: {_safe_json(a.key_claims)}\n\n"
        )

    return f"""You are a news intelligence assistant specialising in the topic: "{topic_name}".
Current time: {now}

Your job: answer the user's questions accurately, grounded ONLY in the news data below.
- Cite sources by outlet name (e.g. "According to Reuters...")
- Distinguish between confirmed events (Tier 1, multiple sources) and unconfirmed ones (single source / Tier 3)
- If the data doesn't contain an answer, say so clearly — do not speculate or hallucinate
- Keep answers focused and factual
- When asked for a timeline or sequence of events, order them chronologically

=== TIMELINE EVENTS ({len(events)} most relevant) ===
{events_text or "No events available."}

=== ARTICLE DETAILS ({len(articles)} most relevant) ===
{articles_text or "No articles available."}"""


# ---------------------------------------------------------------------------
# Retrieval ranking (keyword + recency, no LLM cost)
# ---------------------------------------------------------------------------

def _rank_events(events: list[Event], query: str) -> list[Event]:
    keywords = set(query.lower().split())
    scored = []
    for ev in events:
        text = f"{ev.headline} {ev.summary}".lower()
        hits = sum(1 for kw in keywords if kw in text)
        recency = str(ev.first_seen or "")
        scored.append((-(hits * 2 + ev.significance_score), recency, ev))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in scored]


def _rank_articles(articles: list[Article], query: str) -> list[Article]:
    keywords = set(query.lower().split())
    scored = []
    for a in articles:
        text = f"{a.title} {a.summary}".lower()
        hits = sum(1 for kw in keywords if kw in text)
        recency = str(a.published_at or "")
        score = hits * 2 + a.relevance_score + (1 if a.source_tier == 1 else 0)
        scored.append((-score, recency, a))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in scored]


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

async def _load_history(session: AsyncSession, topic_name: str) -> list[ChatMessage]:
    from sqlalchemy import select
    result = await session.execute(
        select(Topic).where(Topic.name == topic_name)
    )
    topic = result.scalar_one_or_none()
    if not topic:
        return []
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.topic_id == topic.id)
        .order_by(ChatMessage.created_at)
    )
    return list(result.scalars())


async def _save_message(
    session: AsyncSession,
    topic_name: str,
    role: str,
    content: str,
):
    from sqlalchemy import select
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if topic:
        session.add(ChatMessage(topic_id=topic.id, role=role, content=content))


def _safe_json(val) -> list:
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val) if val else []
        except Exception:
            return []
    return []
