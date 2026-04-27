"""
APScheduler job definitions for the news-intelligence backend.

Exports
-------
scheduler       — AsyncIOScheduler instance (UTC)
scrape_and_update(topic_name) — full pipeline job
start_scheduler(session)      — load DB schedules and register interval jobs
stop_scheduler()              — graceful shutdown
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import NarrativeChange, Topic, TopicSchedule
from database.session import AsyncSessionLocal
from services.narrative_service import detect_changes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Single shared scheduler instance
# ---------------------------------------------------------------------------

scheduler = AsyncIOScheduler(timezone="UTC")


# ---------------------------------------------------------------------------
# Core pipeline job
# ---------------------------------------------------------------------------

async def scrape_and_update(topic_name: str) -> None:
    """
    Full pipeline job: scrape → classify → timeline → detect changes → save.

    This function is called by APScheduler (no session argument — it opens its
    own session so the job is fully self-contained).
    """
    from agents.scraping_agent import ScrapingAgent
    from agents.classification_agent import ClassificationAgent
    from agents.timeline_agent import TimelineAgent
    from services.storage_service import (
        get_or_create_topic,
        save_articles,
        save_events,
        mark_topic_scraped,
    )

    run_start = datetime.now(timezone.utc)
    logger.info(f"[scheduler] Starting pipeline for '{topic_name}' at {run_start.isoformat()}")
    print(f"\n[{run_start.strftime('%H:%M:%S')} UTC] Running pipeline for topic: {topic_name!r}")

    # ------------------------------------------------------------------
    # 1. Scrape
    # ------------------------------------------------------------------
    scraper = ScrapingAgent()
    try:
        raw_articles = await scraper.scrape(topic_name)
    finally:
        await scraper.close()

    print(f"  Scraped {len(raw_articles)} raw articles")

    if not raw_articles:
        print("  No articles found — skipping rest of pipeline.")
        return

    # ------------------------------------------------------------------
    # 2. Classify
    # ------------------------------------------------------------------
    classified = await ClassificationAgent().classify(raw_articles, topic_name)
    print(f"  Classified: {len(classified)} relevant articles")

    if not classified:
        print("  No relevant articles after classification — skipping.")
        return

    # ------------------------------------------------------------------
    # 3. Build timeline
    # ------------------------------------------------------------------
    new_events = await TimelineAgent().build(classified, topic_name)
    print(f"  Timeline: {len(new_events)} events")

    # ------------------------------------------------------------------
    # 4. Detect narrative changes (compare to stored events)
    # ------------------------------------------------------------------
    async with AsyncSessionLocal() as session:
        changes = await detect_changes(session, topic_name, new_events)
        print(f"  Narrative changes detected: {len(changes)}")

        # ------------------------------------------------------------------
        # 5. Persist: articles, events, changes
        # ------------------------------------------------------------------
        db_topic = await get_or_create_topic(session, topic_name)
        url_map  = await save_articles(session, db_topic, classified)
        await save_events(session, db_topic, new_events, url_map)
        await mark_topic_scraped(session, db_topic)

        for change in changes:
            session.add(change)

        await session.commit()

    # ------------------------------------------------------------------
    # 6. Print summary
    # ------------------------------------------------------------------
    elapsed = (datetime.now(timezone.utc) - run_start).total_seconds()
    print(
        f"  Done in {elapsed:.1f}s — "
        f"{len(classified)} articles, "
        f"{len(new_events)} events, "
        f"{len(changes)} changes saved."
    )

    if changes:
        print("  Changes:")
        for ch in changes:
            print(f"    [{ch.change_type.upper()}] {ch.headline}")

    logger.info(
        f"[scheduler] Pipeline complete for '{topic_name}': "
        f"{len(classified)} articles, {len(new_events)} events, {len(changes)} changes "
        f"in {elapsed:.1f}s"
    )


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

async def start_scheduler(session: AsyncSession) -> None:
    """
    Load all active TopicSchedule rows from the DB and register an
    interval job for each topic. Starts the scheduler if not already running.
    """
    result = await session.execute(
        select(TopicSchedule).where(TopicSchedule.active == True)  # noqa: E712
    )
    schedules = list(result.scalars())

    for sched in schedules:
        # Resolve the topic name
        topic_result = await session.execute(
            select(Topic).where(Topic.id == sched.topic_id)
        )
        topic = topic_result.scalar_one_or_none()
        if not topic:
            continue

        _register_job(topic.name, sched.interval_min)
        logger.info(
            f"[scheduler] Registered job for '{topic.name}' "
            f"every {sched.interval_min} min"
        )

    if not scheduler.running:
        scheduler.start()
        logger.info("[scheduler] Scheduler started")


def register_topic_job(topic_name: str, interval_min: int) -> None:
    """
    Register (or replace) an interval job for a single topic.
    Safe to call before or after start_scheduler().
    """
    _register_job(topic_name, interval_min)


def _register_job(topic_name: str, interval_min: int) -> None:
    """Internal: add/replace job, starting scheduler if needed."""
    job_id = f"scrape_{topic_name.replace(' ', '_').lower()}"

    # Remove existing job for this topic if present
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        scrape_and_update,
        trigger="interval",
        minutes=interval_min,
        args=[topic_name],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=60,
    )
    logger.info(f"[scheduler] Job '{job_id}' registered (interval={interval_min}m)")

    if not scheduler.running:
        scheduler.start()


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler if it is running."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[scheduler] Scheduler stopped")
