"""
Timeline Agent — takes classified articles and builds a structured event timeline.

What it does:
  1. Groups articles covering the same event (deduplication by story, not URL)
  2. Assigns each event a type tag: Military / Diplomatic / Economic / Political / Social
  3. Scores each event by significance (source tier weight x source count)
  4. Orders events chronologically
  5. Detects the narrative state of each event: Breaking / Developing / Confirmed / Resolved

One event = one real-world occurrence reported by 1-N articles.
Multiple articles about the same event are clustered as "sources" under that event.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn

from openai import AsyncOpenAI
from pydantic import BaseModel

from agents.classification_agent import ClassifiedArticle
from config import settings

logger = logging.getLogger(__name__)
console = Console()
client = AsyncOpenAI(api_key=settings.openai_api_key)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class EventSource(BaseModel):
    url: str
    title: str
    source: str
    source_tier: int
    trust_label: str
    region: str | None
    published_at: str | None
    sentiment: str
    relevance_score: float


class TimelineEvent(BaseModel):
    event_id: str                  # slug derived from headline
    headline: str                  # short headline for this event
    summary: str                   # 2-3 sentence description
    event_type: str                # Military / Diplomatic / Economic / Political / Social
    narrative_state: str           # Breaking / Developing / Confirmed / Resolved
    significance_score: float      # 0.0-1.0 based on source count + tier weight
    first_seen: str                # ISO timestamp of earliest source
    last_updated: str              # ISO timestamp of latest source
    locations: list[str]
    people: list[str]
    organizations: list[str]
    sources: list[EventSource]     # all articles covering this event
    source_count: int
    tier1_count: int               # number of Tier 1 sources
    dominant_sentiment: str        # most common sentiment across sources
    trust_label: str               # derived from tier1_count + source_count


# ---------------------------------------------------------------------------
# Timeline Agent
# ---------------------------------------------------------------------------

class TimelineAgent:

    async def build(
        self,
        articles: list[ClassifiedArticle],
        topic: str,
    ) -> list[TimelineEvent]:
        """
        Full pipeline: cluster → enrich → score → sort.
        Returns events sorted chronologically (oldest first).
        """
        if not articles:
            return []

        console.print(f"\n[bold]Timeline pipeline[/bold] — topic: [cyan]{topic}[/cyan]")

        # Step 1: cluster articles into events via GPT-4o-mini
        console.print("  [dim]Step 1/3[/dim] Clustering articles into events...")
        clusters = await self._cluster_articles(articles, topic)
        console.print(f"           [green]done[/green] — {len(clusters)} distinct events found")

        # Step 2: enrich each event cluster
        console.print("  [dim]Step 2/3[/dim] Enriching events...")
        events = await self._enrich_clusters(clusters, articles, topic)
        console.print(f"           [green]done[/green] — {len(events)} events enriched")

        # Step 3: score + sort
        console.print("  [dim]Step 3/3[/dim] Scoring and sorting timeline...", end=" ")
        events = _score_and_sort(events)
        console.print(f"[green]done[/green]\n")

        return events

    # ------------------------------------------------------------------
    # Step 1: Cluster articles → events
    # ------------------------------------------------------------------

    async def _cluster_articles(
        self,
        articles: list[ClassifiedArticle],
        topic: str,
    ) -> list[list[int]]:
        """
        Ask GPT-4o-mini to group article indices that cover the same event.
        Returns list of clusters, each cluster is a list of article indices.
        Processes in windows of 30 articles to stay within token limits.
        """
        all_clusters: list[list[int]] = []
        offset = 0
        window = 30

        total_windows = (len(articles) + window - 1) // window

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]Clustering[/bold cyan]"),
            BarColumn(bar_width=25),
            TaskProgressColumn(),
            TextColumn("{task.fields[status]}"),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("cluster", total=total_windows, status="")

            while offset < len(articles):
                window_articles = articles[offset:offset + window]
                payload = [
                    {"id": offset + i, "title": a.title, "published_at": a.published_at}
                    for i, a in enumerate(window_articles)
                ]

                prompt = f"""Group these news article titles about "{topic}" into clusters where each cluster = one real-world event.

Rules:
- Same event = same specific occurrence (e.g. "Iran seizes ship in Hormuz on April 23" is ONE event)
- Different events = different occurrences (ship seizure on April 23 vs April 24 = two events)
- Keep clusters tight — don't merge vague similarity
- An article can only belong to one cluster
- Articles with no clear match to others form their own single-article cluster

Return JSON: {{"clusters": [[id, id, ...], [id], ...]}}
Only include article IDs from the input. No explanation.

Articles:
{json.dumps(payload, ensure_ascii=False)}"""

                try:
                    resp = await client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.0,
                        response_format={"type": "json_object"},
                    )
                    data = json.loads(resp.choices[0].message.content)
                    clusters = data.get("clusters", [[offset + i] for i in range(len(window_articles))])
                    all_clusters.extend(clusters)
                except Exception as e:
                    logger.warning(f"Clustering window failed: {e} — each article becomes own event")
                    all_clusters.extend([[offset + i] for i in range(len(window_articles))])

                offset += window
                progress.update(task, advance=1, status=f"{len(all_clusters)} clusters so far")

        # Merge clusters that share articles across windows (overlap resolution)
        return _merge_overlapping(all_clusters)

    # ------------------------------------------------------------------
    # Step 2: Enrich each cluster into a TimelineEvent
    # ------------------------------------------------------------------

    async def _enrich_clusters(
        self,
        clusters: list[list[int]],
        articles: list[ClassifiedArticle],
        topic: str,
    ) -> list[TimelineEvent]:
        sem = asyncio.Semaphore(6)

        async def _enrich_one(cluster: list[int]) -> TimelineEvent | None:
            async with sem:
                cluster_articles = [articles[i] for i in cluster if i < len(articles)]
                if not cluster_articles:
                    return None
                return await self._enrich_single(cluster_articles, topic)

        results = await asyncio.gather(*[_enrich_one(c) for c in clusters], return_exceptions=True)
        return [r for r in results if isinstance(r, TimelineEvent)]

    async def _enrich_single(
        self,
        articles: list[ClassifiedArticle],
        topic: str,
    ) -> TimelineEvent:
        # Sort by tier then recency for best representative article
        articles_sorted = sorted(articles, key=lambda a: (a.source_tier, a.published_at or ""))
        best = articles_sorted[0]

        titles = [a.title for a in articles[:8]]
        summaries = [a.summary for a in articles[:5] if a.summary]

        prompt = f"""You are building a timeline for the topic: "{topic}"

These articles all cover the same event. Generate a structured event summary.

Article titles: {json.dumps(titles, ensure_ascii=False)}
Article summaries: {json.dumps(summaries, ensure_ascii=False)}

Return JSON with exactly these fields:
- headline: short punchy headline for this event (max 12 words)
- summary: 2-3 sentence factual description of what happened
- event_type: one of "Military", "Diplomatic", "Economic", "Political", "Social"
- narrative_state: one of "Breaking" (single source <2h), "Developing" (multiple sources, ongoing), "Confirmed" (Tier 1 sources corroborate), "Resolved" (outcome known)
- locations: list of place names mentioned
- people: list of person names mentioned
- organizations: list of organization names mentioned

No markdown, no explanation. JSON only."""

        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)

        # Build source list
        sources = [
            EventSource(
                url=a.url,
                title=a.title,
                source=a.source,
                source_tier=a.source_tier,
                trust_label=a.trust_label,
                region=a.region,
                published_at=a.published_at,
                sentiment=a.sentiment,
                relevance_score=a.relevance_score,
            )
            for a in articles
        ]

        # Timestamps
        timestamps = [a.published_at for a in articles if a.published_at]
        first_seen = min(timestamps) if timestamps else datetime.now(timezone.utc).isoformat()
        last_updated = max(timestamps) if timestamps else first_seen

        # Tier counts
        tier1 = sum(1 for a in articles if a.source_tier == 1)

        # Dominant sentiment
        sentiments = [a.sentiment for a in articles]
        dominant = max(set(sentiments), key=sentiments.count)

        # Trust label
        trust = _derive_trust_label(tier1, len(articles))

        headline = data.get("headline", best.title[:80])
        event_id = _slugify(headline)

        return TimelineEvent(
            event_id=event_id,
            headline=headline,
            summary=data.get("summary", best.summary),
            event_type=data.get("event_type", "Political"),
            narrative_state=data.get("narrative_state", "Developing"),
            significance_score=0.0,   # filled by _score_and_sort
            first_seen=first_seen,
            last_updated=last_updated,
            locations=data.get("locations", [])[:8],
            people=data.get("people", [])[:8],
            organizations=data.get("organizations", [])[:8],
            sources=sources,
            source_count=len(sources),
            tier1_count=tier1,
            dominant_sentiment=dominant,
            trust_label=trust,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_and_sort(events: list[TimelineEvent]) -> list[TimelineEvent]:
    """Compute significance score and sort chronologically."""
    if not events:
        return events

    max_sources = max(e.source_count for e in events) or 1
    max_t1 = max(e.tier1_count for e in events) or 1

    for e in events:
        source_weight = e.source_count / max_sources
        tier_weight = e.tier1_count / max_t1
        score = round(0.5 * source_weight + 0.5 * tier_weight, 3)
        object.__setattr__(e, "significance_score", score)

    events.sort(key=lambda e: e.first_seen)
    return events


def _derive_trust_label(tier1_count: int, total: int) -> str:
    if tier1_count >= 3:
        return "Widely Reported"
    if tier1_count >= 1:
        return "Few Major Sources"
    if total >= 3:
        return "Multiple Sources"
    return "Single Source"


def _merge_overlapping(clusters: list[list[int]]) -> list[list[int]]:
    """Union-find merge for clusters sharing article IDs across windows."""
    parent: dict[int, int] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        parent[find(x)] = find(y)

    for cluster in clusters:
        for idx in cluster[1:]:
            union(cluster[0], idx)

    groups: dict[int, list[int]] = {}
    for cluster in clusters:
        for idx in cluster:
            root = find(idx)
            groups.setdefault(root, [])
            if idx not in groups[root]:
                groups[root].append(idx)

    return list(groups.values())


def _slugify(text: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60]
