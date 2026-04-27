"""
Classification Agent — enriches raw articles with:
  1. Source trust tier   (rule-based, no LLM — instant)
  2. Relevance score     (keyword heuristic + GPT-4o-mini for borderline)
  3. Entity extraction   (people, locations, organizations)
  4. Sentiment           (positive / negative / neutral + score)
  5. Key claims          (up to 3 main factual claims per article)
  6. Summary             (2-sentence summary)

Articles are batched 10 per GPT-4o-mini call to minimise cost and latency.
Estimated cost: ~$0.04 per 250-article run.
"""

import asyncio
import json
import logging
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn

from openai import AsyncOpenAI
from pydantic import BaseModel

from agents.scraping_agent import RawArticle
from config import settings

logger = logging.getLogger(__name__)
console = Console()

client = AsyncOpenAI(api_key=settings.openai_api_key)

# ---------------------------------------------------------------------------
# Source trust tier registry
# ---------------------------------------------------------------------------

TIER1_SOURCES = {
    # Wire services / global reference
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk",
    # Major US
    "nytimes.com", "washingtonpost.com", "wsj.com", "bloomberg.com",
    "npr.org", "cnn.com", "cbsnews.com", "abcnews.go.com", "nbcnews.com",
    # Major UK
    "theguardian.com", "telegraph.co.uk", "independent.co.uk", "ft.com",
    "news.sky.com", "thetimes.co.uk",
    # Major international
    "france24.com", "dw.com", "euronews.com", "aljazeera.com",
    "scmp.com", "straitstimes.com", "japantimes.co.jp", "nhk.or.jp",
}

TIER2_SOURCES = {
    # Regional established
    "arabnews.com", "middleeasteye.net", "jpost.com", "haaretz.com",
    "timesofisrael.com", "thehindu.com", "timesofindia.com", "dawn.com",
    "tass.com", "sputnikglobe.com", "rt.com", "xinhua.net",
    "globaltimes.cn", "chinadaily.com.cn", "presstv.ir", "irna.ir",
    "dailysabah.com", "hurriyet.com.tr", "politico.com", "politico.eu",
    "cnbc.com", "foxnews.com", "axios.com", "theatlantic.com",
    "foreignpolicy.com", "foreignaffairs.com",
}

# Everything else = Tier 3


def _get_source_tier(domain: str) -> tuple[int, str]:
    d = domain.lower().removeprefix("www.")
    # strip subdomains for matching (e.g. feeds.reuters.com → reuters.com)
    parts = d.split(".")
    root = ".".join(parts[-2:]) if len(parts) >= 2 else d

    if root in TIER1_SOURCES or d in TIER1_SOURCES:
        return 1, "Major International"
    if root in TIER2_SOURCES or d in TIER2_SOURCES:
        return 2, "Regional / Established"
    return 3, "Independent / Unknown"


TIER_TRUST_LABEL = {
    1: "Widely Trusted",
    2: "Generally Reliable",
    3: "Unverified Source",
}

# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

class ClassifiedArticle(BaseModel):
    # Original article
    url: str
    title: str
    content: str
    source: str
    published_at: str | None
    region: str | None
    source_type: str
    query: str

    # Trust
    source_tier: int
    source_tier_label: str
    trust_label: str

    # Relevance
    relevance_score: float       # 0.0 – 1.0
    is_relevant: bool

    # LLM-enriched
    entities: dict               # {people, locations, organizations}
    sentiment: str               # positive / negative / neutral
    sentiment_score: float       # -1.0 to 1.0
    key_claims: list[str]
    summary: str

    @classmethod
    def from_raw(cls, raw: RawArticle, tier: int, tier_label: str) -> "ClassifiedArticle":
        return cls(
            url=raw.url,
            title=raw.title,
            content=raw.content,
            source=raw.source,
            published_at=raw.published_at.isoformat() if raw.published_at else None,
            region=raw.region,
            source_type=raw.source_type,
            query=raw.query,
            source_tier=tier,
            source_tier_label=tier_label,
            trust_label=TIER_TRUST_LABEL[tier],
            relevance_score=0.0,
            is_relevant=False,
            entities={"people": [], "locations": [], "organizations": []},
            sentiment="neutral",
            sentiment_score=0.0,
            key_claims=[],
            summary="",
        )


# ---------------------------------------------------------------------------
# Classification Agent
# ---------------------------------------------------------------------------

RELEVANCE_THRESHOLD = 0.35   # articles below this are dropped


class ClassificationAgent:

    async def classify(
        self,
        articles: list[RawArticle],
        topic: str,
        batch_size: int = 10,
    ) -> list[ClassifiedArticle]:
        """
        Classify all articles. Returns only relevant ones, sorted by
        relevance_score desc then published_at desc.
        """
        if not articles:
            return []

        console.print(f"\n[bold]Classification pipeline[/bold] — topic: [cyan]{topic}[/cyan]")

        # Step 1: source tier scoring (instant, rule-based)
        console.print(f"  [dim]Step 1/4[/dim] Scoring source tiers...", end=" ")
        classified = []
        for raw in articles:
            tier, tier_label = _get_source_tier(raw.source)
            classified.append(ClassifiedArticle.from_raw(raw, tier, tier_label))
        t1 = sum(1 for a in classified if a.source_tier == 1)
        t2 = sum(1 for a in classified if a.source_tier == 2)
        t3 = sum(1 for a in classified if a.source_tier == 3)
        console.print(f"[green]done[/green] — T1:{t1}  T2:{t2}  T3:{t3}")

        # Step 2: keyword pre-filter
        console.print(f"  [dim]Step 2/4[/dim] Keyword pre-filter...", end=" ")
        keywords = _build_keywords(topic)
        pre_filtered, dropped = [], []
        for art in classified:
            text = f"{art.title} {art.content[:300]}".lower()
            if any(kw in text for kw in keywords):
                pre_filtered.append(art)
            else:
                dropped.append(art)
        console.print(
            f"[green]done[/green] — "
            f"[yellow]{len(pre_filtered)} pass[/yellow]  "
            f"[red]{len(dropped)} dropped[/red] (no keyword match)"
        )

        # Step 3: GPT-4o-mini enrichment
        console.print(f"  [dim]Step 3/4[/dim] GPT-4o-mini enrichment ({len(pre_filtered)} articles, batch={batch_size})...")
        enriched = await self._enrich_batches(pre_filtered, topic, batch_size)

        # Step 4: relevance filter
        console.print(f"  [dim]Step 4/4[/dim] Relevance filter (threshold >= {RELEVANCE_THRESHOLD})...", end=" ")
        relevant = [a for a in enriched if a.is_relevant]
        relevant.sort(key=lambda a: (-a.relevance_score, a.published_at or ""))
        console.print(f"[green]done[/green] — [bold green]{len(relevant)} relevant articles[/bold green]\n")

        return relevant

    # ------------------------------------------------------------------
    # Batch enrichment
    # ------------------------------------------------------------------

    async def _enrich_batches(
        self,
        articles: list[ClassifiedArticle],
        topic: str,
        batch_size: int,
    ) -> list[ClassifiedArticle]:
        batches = [articles[i:i + batch_size] for i in range(0, len(articles), batch_size)]
        total_batches = len(batches)
        sem = asyncio.Semaphore(5)
        completed = {"n": 0}

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]Classifying[/bold cyan]"),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            TextColumn("{task.fields[status]}"),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task(
                "classifying",
                total=total_batches,
                status=f"0/{total_batches} batches · 0 articles done",
            )

            async def _process(i, batch):
                async with sem:
                    result = await self._enrich_batch(batch, topic)
                    completed["n"] += 1
                    articles_done = completed["n"] * batch_size
                    progress.update(
                        task,
                        advance=1,
                        status=(
                            f"{completed['n']}/{total_batches} batches · "
                            f"~{min(articles_done, len(articles))} articles · "
                            f"last: [green]{result[-1].title[:35]}…[/green]"
                            if result else ""
                        ),
                    )
                    return result

            results = await asyncio.gather(
                *[_process(i, b) for i, b in enumerate(batches)],
                return_exceptions=True,
            )

        enriched = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Batch {i} failed: {result}")
                enriched.extend(batches[i])
            else:
                enriched.extend(result)
        return enriched

    async def _enrich_batch(
        self,
        batch: list[ClassifiedArticle],
        topic: str,
    ) -> list[ClassifiedArticle]:
        articles_payload = [
            {
                "id": i,
                "title": a.title,
                "source": a.source,
                "content": a.content[:600],   # keep tokens low
            }
            for i, a in enumerate(batch)
        ]

        prompt = f"""You are classifying news articles for relevance to the topic: "{topic}"

For each article return a JSON object with exactly these fields:
- relevance_score: float 0.0-1.0 (how directly relevant to "{topic}")
- entities: object with keys "people" (list), "locations" (list), "organizations" (list)
- sentiment: one of "positive", "negative", "neutral" (toward the topic/situation)
- sentiment_score: float -1.0 (very negative) to 1.0 (very positive)
- key_claims: list of up to 3 short factual claims from the article
- summary: exactly 2 sentences summarising the article

Return a JSON array in the same order as the input. No markdown, no explanation.

Articles:
{json.dumps(articles_payload, ensure_ascii=False)}"""

        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        raw_json = resp.choices[0].message.content
        parsed = json.loads(raw_json)

        # model may return {"articles": [...]} or just [...]
        if isinstance(parsed, dict):
            results = next(iter(parsed.values()))
        else:
            results = parsed

        enriched = []
        for i, art in enumerate(batch):
            try:
                r = results[i] if i < len(results) else {}
                score = float(r.get("relevance_score", 0.0))
                sent_score = float(r.get("sentiment_score", 0.0))

                updated = art.model_copy(update={
                    "relevance_score": round(score, 3),
                    "is_relevant": score >= RELEVANCE_THRESHOLD,
                    "entities": r.get("entities", {"people": [], "locations": [], "organizations": []}),
                    "sentiment": r.get("sentiment", "neutral"),
                    "sentiment_score": round(sent_score, 3),
                    "key_claims": r.get("key_claims", [])[:3],
                    "summary": r.get("summary", ""),
                })
                enriched.append(updated)
            except Exception as e:
                logger.debug(f"Failed to parse result for article {i}: {e}")
                enriched.append(art)

        return enriched


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOPIC_EXPANSIONS: dict[str, set[str]] = {
    "iran": {"iranian", "tehran", "irgc", "khamenei", "rouhani", "raisi", "persian"},
    "war":  {"conflict", "military", "strike", "attack", "missile", "battle", "troops", "combat"},
    "oil":  {"crude", "brent", "opec", "petroleum", "barrel", "energy", "fuel"},
    "nuclear": {"uranium", "enrichment", "warhead", "bomb", "reactor", "isotope"},
    "israel": {"israeli", "idf", "tel aviv", "netanyahu", "gaza", "west bank"},
    "ukraine": {"ukrainian", "kyiv", "zelenskyy", "zelensky", "kiev", "donbas"},
    "russia": {"russian", "moscow", "kremlin", "putin", "lavrov"},
    "china": {"chinese", "beijing", "xi jinping", "pla"},
}


def _build_keywords(topic: str) -> set[str]:
    words = topic.lower().split()
    keywords = set(words) | {topic.lower()}
    for word in words:
        keywords |= _TOPIC_EXPANSIONS.get(word, set())
    return keywords
