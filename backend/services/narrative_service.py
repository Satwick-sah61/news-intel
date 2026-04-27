"""
Narrative Change Detection Service.

Compares a fresh set of TimelineEvents against what is already stored in the
database for a topic and returns a list of NarrativeChange objects (unsaved)
describing what is new or different.

Change types
------------
new_event    — headline not seen before, significance >= 0.3
escalation   — existing event now has more Tier-1 sources or higher significance
confirmed    — event moved from Breaking/Developing to Confirmed
state_change — narrative_state changed to anything other than Confirmed
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Event, NarrativeChange, Topic
from agents.timeline_agent import TimelineEvent


# ---------------------------------------------------------------------------
# Keyword-overlap similarity
# ---------------------------------------------------------------------------

def _keywords(text: str) -> set[str]:
    """Return lowercase word-tokens longer than 3 chars."""
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split() if len(w) > 3}


def _similarity(a: str, b: str) -> float:
    """Jaccard similarity on word tokens."""
    kw_a = _keywords(a)
    kw_b = _keywords(b)
    if not kw_a or not kw_b:
        return 0.0
    intersection = len(kw_a & kw_b)
    union = len(kw_a | kw_b)
    return intersection / union if union else 0.0


_SIMILARITY_THRESHOLD = 0.30   # headlines above this are considered "same event"


def _find_match(new_headline: str, existing: list[Event]) -> Event | None:
    """Return the best-matching existing Event, or None if below threshold."""
    best_score = 0.0
    best_event = None
    for ev in existing:
        score = _similarity(new_headline, ev.headline)
        if score > best_score:
            best_score = score
            best_event = ev
    if best_score >= _SIMILARITY_THRESHOLD:
        return best_event
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def detect_changes(
    session: AsyncSession,
    topic_name: str,
    new_events: list[TimelineEvent],
) -> list[NarrativeChange]:
    """
    Compare *new_events* (from a fresh TimelineAgent run) against events already
    stored in the DB for *topic_name*.

    Returns a list of NarrativeChange objects that have NOT been added to the
    session yet — the caller is responsible for adding and committing them.
    """
    # ------------------------------------------------------------------ load
    result = await session.execute(select(Topic).where(Topic.name == topic_name))
    topic = result.scalar_one_or_none()
    if not topic:
        return []

    result = await session.execute(
        select(Event).where(Event.topic_id == topic.id)
    )
    existing_events: list[Event] = list(result.scalars())

    # ------------------------------------------------------------------ compare
    changes: list[NarrativeChange] = []
    now = datetime.now(timezone.utc)

    for new_ev in new_events:
        matched = _find_match(new_ev.headline, existing_events)

        if matched is None:
            # new_event: never seen before
            if new_ev.significance_score >= 0.3:
                changes.append(NarrativeChange(
                    topic_id=topic.id,
                    change_type="new_event",
                    headline=new_ev.headline,
                    description=(
                        f"New event detected: {new_ev.summary[:300]}"
                    ),
                    significance=new_ev.significance_score,
                    detected_at=now,
                    delivered=False,
                ))
        else:
            # --- escalation: more Tier-1 sources or materially higher significance
            sig_delta = new_ev.significance_score - (matched.significance_score or 0.0)
            t1_delta  = new_ev.tier1_count - (matched.tier1_count or 0)

            if t1_delta > 0 or sig_delta >= 0.15:
                changes.append(NarrativeChange(
                    topic_id=topic.id,
                    change_type="escalation",
                    headline=matched.headline,
                    description=(
                        f"Event escalated: Tier-1 sources +{t1_delta}, "
                        f"significance {matched.significance_score:.2f} → "
                        f"{new_ev.significance_score:.2f}. {new_ev.summary[:200]}"
                    ),
                    significance=new_ev.significance_score,
                    detected_at=now,
                    delivered=False,
                ))

            # --- confirmed: moved to Confirmed state
            elif (
                matched.narrative_state in ("Breaking", "Developing")
                and new_ev.narrative_state == "Confirmed"
            ):
                changes.append(NarrativeChange(
                    topic_id=topic.id,
                    change_type="confirmed",
                    headline=matched.headline,
                    description=(
                        f"Event confirmed: status changed from "
                        f"{matched.narrative_state} to Confirmed. "
                        f"{new_ev.summary[:200]}"
                    ),
                    significance=new_ev.significance_score,
                    detected_at=now,
                    delivered=False,
                ))

            # --- state_change: any other narrative_state shift
            elif (
                matched.narrative_state != new_ev.narrative_state
                and new_ev.narrative_state != "Confirmed"  # already handled above
            ):
                changes.append(NarrativeChange(
                    topic_id=topic.id,
                    change_type="state_change",
                    headline=matched.headline,
                    description=(
                        f"Narrative state changed: "
                        f"{matched.narrative_state} → {new_ev.narrative_state}. "
                        f"{new_ev.summary[:200]}"
                    ),
                    significance=new_ev.significance_score,
                    detected_at=now,
                    delivered=False,
                ))

    return changes
