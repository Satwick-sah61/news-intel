"""
Scraping Agent — fetches raw articles from three sources in parallel:
  1. Tavily Search API    — broad web + news search
  2. GDELT Doc 2.0 API   — free real-time global event feed
  3. RSS feeds            — curated major international outlets

All three run concurrently. Results are deduplicated by URL.
Full article text is extracted via newspaper4k when Tavily doesn't provide it.
"""

import asyncio
import hashlib
import logging
import requests
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, quote_plus

import feedparser
import httpx
from newspaper import Article as NewspaperArticle
from pydantic import BaseModel, field_validator
from tavily import TavilyClient

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class RawArticle(BaseModel):
    url: str
    title: str
    content: str
    source: str           # domain (e.g. "bbc.com")
    published_at: datetime | None
    region: str | None    # detected from source origin
    source_type: str      # "tavily" | "gdelt" | "rss"
    query: str            # which query produced this result

    @field_validator("published_at", mode="before")
    @classmethod
    def parse_date(cls, v):
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return None

    @property
    def uid(self) -> str:
        return hashlib.md5(self.url.encode()).hexdigest()


# ---------------------------------------------------------------------------
# RSS feed registry — major international outlets with known regional origin
# ---------------------------------------------------------------------------

RSS_FEEDS: list[dict] = [
    # --- US Networks ---
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",                    "source": "bbc.com",          "region": "UK"},
    {"url": "https://feeds.reuters.com/reuters/topNews",                       "source": "reuters.com",      "region": "Global"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",         "source": "nytimes.com",      "region": "US"},
    {"url": "https://feeds.npr.org/1004/rss.xml",                              "source": "npr.org",          "region": "US"},
    {"url": "https://www.theguardian.com/world/rss",                           "source": "theguardian.com",  "region": "UK"},
    {"url": "https://apnews.com/rss/apf-topnews",                             "source": "apnews.com",       "region": "US"},
    {"url": "https://rss.cnn.com/rss/edition_world.rss",                      "source": "cnn.com",          "region": "US"},
    {"url": "https://moxie.foxnews.com/google-publisher/world.xml",           "source": "foxnews.com",      "region": "US"},
    {"url": "https://www.cbsnews.com/latest/rss/world",                       "source": "cbsnews.com",      "region": "US"},
    {"url": "https://feeds.abcnews.com/abcnews/internationalheadlines",       "source": "abcnews.go.com",   "region": "US"},
    {"url": "https://www.cnbc.com/id/100727362/device/rss/rss.html",         "source": "cnbc.com",         "region": "US"},
    {"url": "https://rss.politico.com/politics-news.xml",                     "source": "politico.com",     "region": "US"},
    # --- UK ---
    {"url": "https://feeds.skynews.com/feeds/rss/world.xml",                  "source": "news.sky.com",     "region": "UK"},
    {"url": "https://www.independent.co.uk/news/world/rss",                   "source": "independent.co.uk","region": "UK"},
    {"url": "https://www.telegraph.co.uk/news/world/?utm_source=rss",        "source": "telegraph.co.uk",  "region": "UK"},
    # --- Middle East ---
    {"url": "https://www.aljazeera.com/xml/rss/all.xml",                      "source": "aljazeera.com",    "region": "Qatar"},
    {"url": "https://www.arabnews.com/rss.xml",                               "source": "arabnews.com",     "region": "Saudi Arabia"},
    {"url": "https://www.middleeasteye.net/rss",                              "source": "middleeasteye.net","region": "Middle East"},
    {"url": "https://www.jpost.com/Rss/RssFeedsHeadlines.aspx",              "source": "jpost.com",        "region": "Israel"},
    {"url": "https://www.haaretz.com/cmlink/1.628765",                        "source": "haaretz.com",      "region": "Israel"},
    # --- Europe ---
    {"url": "https://www.dw.com/en/top-stories/rss/rdf/15826553",            "source": "dw.com",           "region": "Germany"},
    {"url": "https://www.france24.com/en/rss",                               "source": "france24.com",     "region": "France"},
    {"url": "https://www.euronews.com/rss?level=theme&name=news",            "source": "euronews.com",     "region": "Europe"},
    {"url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                   "source": "wsj.com",          "region": "US"},
    # --- Russia / CIS ---
    {"url": "https://tass.com/rss/v2.xml",                                    "source": "tass.com",         "region": "Russia"},
    {"url": "https://sputnikglobe.com/export/rss2/archive/index.xml",        "source": "sputnikglobe.com", "region": "Russia"},
    # --- Asia ---
    {"url": "https://www3.nhk.or.jp/rss/news/cat0.xml",                      "source": "nhk.or.jp",        "region": "Japan"},
    {"url": "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms",  "source": "timesofindia.com", "region": "India"},
    {"url": "https://www.scmp.com/rss/91/feed",                              "source": "scmp.com",         "region": "China"},
    {"url": "https://www.straitstimes.com/news/world/rss.xml",               "source": "straitstimes.com", "region": "Singapore"},
    # --- Financial / Markets ---
    {"url": "https://feeds.bloomberg.com/markets/news.rss",                  "source": "bloomberg.com",    "region": "US"},
    {"url": "https://feeds.reuters.com/reuters/businessNews",                "source": "reuters.com/biz",  "region": "Global"},
    # --- Latin America ---
    {"url": "https://rss.dw.com/rdf/rss-es-noticias",                        "source": "dw.com/es",        "region": "LatAm"},
]


# ---------------------------------------------------------------------------
# Source → region mapping for sources not in RSS registry
# ---------------------------------------------------------------------------

DOMAIN_REGION_MAP: dict[str, str] = {
    "bbc.com": "UK", "bbc.co.uk": "UK",
    "reuters.com": "Global", "apnews.com": "US",
    "nytimes.com": "US", "wsj.com": "US", "washingtonpost.com": "US",
    "cnn.com": "US", "foxnews.com": "US", "npr.org": "US",
    "theguardian.com": "UK", "telegraph.co.uk": "UK", "independent.co.uk": "UK",
    "aljazeera.com": "Qatar", "arabnews.com": "Saudi Arabia",
    "timesofisrael.com": "Israel", "haaretz.com": "Israel",
    "presstv.ir": "Iran", "irna.ir": "Iran",
    "tass.com": "Russia", "rt.com": "Russia",
    "xinhua.net": "China", "globaltimes.cn": "China", "chinadaily.com.cn": "China",
    "nhk.or.jp": "Japan", "japantimes.co.jp": "Japan",
    "thehindu.com": "India", "timesofindia.com": "India",
    "dw.com": "Germany", "france24.com": "France",
    "euronews.com": "Europe", "politico.eu": "Europe",
    "dawn.com": "Pakistan", "thedawn.com": "Pakistan",
    "dailysabah.com": "Turkey", "hurriyet.com.tr": "Turkey",
}


def _extract_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host.removeprefix("www.")
    except Exception:
        return url


def _detect_region(domain: str) -> str | None:
    return DOMAIN_REGION_MAP.get(domain)


# ---------------------------------------------------------------------------
# Scraping Agent
# ---------------------------------------------------------------------------

# Simple in-memory cache: query → (timestamp, articles)
# Prevents hammering GDELT when scraping same topic repeatedly
_GDELT_CACHE: dict[str, tuple[float, list]] = {}
_GDELT_CACHE_TTL = 600  # 10 minutes


class ScrapingAgent:
    def __init__(self):
        self._tavily = TavilyClient(api_key=settings.tavily_api_key)
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            headers={"User-Agent": "NewsIntelBot/1.0 (research aggregator)"},
            follow_redirects=True,
        )

    async def close(self):
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def scrape(
        self,
        topic: str,
        days_back: int = 2,
        max_per_source: int = 15,
    ) -> list[RawArticle]:
        """
        Scrape all three sources concurrently for the given topic.
        Returns deduplicated list of RawArticle sorted by published_at desc.
        """
        logger.info(f"Scraping topic='{topic}' days_back={days_back}")

        results = await asyncio.gather(
            self._search_tavily(topic, max_per_source),
            self._search_gdelt(topic, days_back, max_per_source),
            self._parse_rss(topic, days_back, max_per_source),
            return_exceptions=True,
        )

        articles: list[RawArticle] = []
        source_labels = ["tavily", "gdelt", "rss"]
        for label, batch in zip(source_labels, results):
            if isinstance(batch, Exception):
                logger.warning(f"Source '{label}' failed: {batch}")
            else:
                articles.extend(batch)
                logger.info(f"  {label}: {len(batch)} articles")

        deduped = self._deduplicate(articles)
        deduped.sort(key=lambda a: a.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        logger.info(f"Total after dedup: {len(deduped)} articles for '{topic}'")
        return deduped

    # ------------------------------------------------------------------
    # Source 1: Tavily
    # ------------------------------------------------------------------

    async def _search_tavily(self, query: str, max_results: int) -> list[RawArticle]:
        loop = asyncio.get_event_loop()

        def _call():
            return self._tavily.search(
                query=query,
                search_depth="advanced",
                topic="news",
                max_results=max_results,
                include_raw_content=True,
            )

        resp = await loop.run_in_executor(None, _call)
        articles = []

        for r in resp.get("results", []):
            url = r.get("url", "")
            domain = _extract_domain(url)
            content = r.get("raw_content") or r.get("content") or ""

            articles.append(RawArticle(
                url=url,
                title=r.get("title", ""),
                content=content[:8000],  # cap at 8k chars
                source=domain,
                published_at=r.get("published_date"),
                region=_detect_region(domain),
                source_type="tavily",
                query=query,
            ))

        return articles

    # ------------------------------------------------------------------
    # Source 2: GDELT Doc 2.0 API
    # ------------------------------------------------------------------

    async def _search_gdelt(self, query: str, days_back: int, max_results: int) -> list[RawArticle]:
        # Run synchronously in thread executor — httpx async SSL fails on Windows for this host
        loop = asyncio.get_event_loop()
        articles = await loop.run_in_executor(None, self._fetch_gdelt_sync, query, days_back, max_results)
        enriched = await self._enrich_batch(articles, concurrency=5)
        return enriched

    def _fetch_gdelt_sync(self, query: str, days_back: int, max_results: int) -> list[RawArticle]:
        cache_key = f"{query}:{days_back}"
        cached_at, cached_articles = _GDELT_CACHE.get(cache_key, (0.0, []))
        if time.time() - cached_at < _GDELT_CACHE_TTL:
            logger.info(f"GDELT cache hit for '{query}'")
            return cached_articles

        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y%m%d%H%M%S")
        url = (
            f"https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={quote_plus(query)}"
            f"&mode=artlist"
            f"&maxrecords={min(max_results, 75)}"
            f"&startdatetime={since}"
            f"&format=json"
        )

        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=25, headers={"User-Agent": "NewsIntelBot/1.0"})
                if resp.status_code == 429:
                    wait = 10 * (attempt + 1)
                    logger.warning(f"GDELT rate limited, waiting {wait}s (attempt {attempt+1}/3)")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.Timeout:
                logger.warning(f"GDELT timeout on attempt {attempt+1}/3")
                if attempt == 2:
                    raise
                time.sleep(5)
        else:
            return []

        articles = []
        for item in data.get("articles", []):
            raw_url = item.get("url", "")
            domain = _extract_domain(raw_url)
            articles.append(RawArticle(
                url=raw_url,
                title=item.get("title", ""),
                content="",
                source=domain,
                published_at=item.get("seendate"),
                region=_detect_region(domain) or item.get("sourcecountry"),
                source_type="gdelt",
                query=query,
            ))

        _GDELT_CACHE[cache_key] = (time.time(), articles)
        return articles

    # ------------------------------------------------------------------
    # Source 3: RSS feeds (filtered by topic keywords)
    # ------------------------------------------------------------------

    async def _parse_rss(self, topic: str, days_back: int, max_per_feed: int) -> list[RawArticle]:
        # Build keyword set: individual words + full phrase for loose matching
        words = topic.lower().split()
        keywords = set(words) | {topic.lower()}
        # Also add common related terms for well-known topics
        _TOPIC_EXPANSIONS = {
            "iran": {"tehran", "iranian", "persia", "irgc", "khamenei", "hormuz"},
            "war": {"conflict", "military", "battle", "strike", "attack", "troops"},
            "oil": {"crude", "brent", "opec", "petroleum", "barrel", "energy"},
        }
        for word in words:
            keywords |= _TOPIC_EXPANSIONS.get(word, set())

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, self._parse_single_feed, feed, keywords, cutoff, max_per_feed)
            for feed in RSS_FEEDS
        ]
        batches = await asyncio.gather(*tasks, return_exceptions=True)

        articles = []
        for batch in batches:
            if not isinstance(batch, Exception):
                articles.extend(batch)

        # Enrich RSS articles that only have summaries with full text
        articles = await self._enrich_batch(articles, concurrency=8)
        return articles

    def _parse_single_feed(
        self,
        feed_meta: dict,
        keywords: set[str],
        cutoff: datetime,
        limit: int,
    ) -> list[RawArticle]:
        try:
            parsed = feedparser.parse(feed_meta["url"])
        except Exception as e:
            logger.debug(f"RSS parse failed for {feed_meta['url']}: {e}")
            return []

        articles = []
        for entry in parsed.entries[:50]:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            text = f"{title} {summary}".lower()

            # at least one keyword must appear in title+summary
            if not any(kw in text for kw in keywords):
                continue

            pub = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if pub and pub < cutoff:
                continue

            url = entry.get("link", "")
            articles.append(RawArticle(
                url=url,
                title=title,
                content=summary[:2000],  # placeholder — enriched later
                source=feed_meta["source"],
                published_at=pub,
                region=feed_meta["region"],
                source_type="rss",
                query=" ".join(sorted(keywords)),
            ))

            if len(articles) >= limit:
                break

        return articles

    # ------------------------------------------------------------------
    # Full text extraction via newspaper4k
    # ------------------------------------------------------------------

    async def _enrich_batch(self, articles: list[RawArticle], concurrency: int = 5) -> list[RawArticle]:
        """Extract full text for articles that have no content (GDELT results)."""
        sem = asyncio.Semaphore(concurrency)
        loop = asyncio.get_event_loop()

        async def _enrich_one(article: RawArticle) -> RawArticle:
            if len(article.content) > 200:
                return article
            async with sem:
                text = await loop.run_in_executor(None, _extract_text, article.url)
                if text:
                    return article.model_copy(update={"content": text[:8000]})
                return article

        return list(await asyncio.gather(*[_enrich_one(a) for a in articles]))

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _deduplicate(self, articles: list[RawArticle]) -> list[RawArticle]:
        seen: set[str] = set()
        unique = []
        for a in articles:
            if a.url and a.uid not in seen:
                seen.add(a.uid)
                unique.append(a)
        return unique


# ---------------------------------------------------------------------------
# Newspaper4k text extraction (runs in thread executor — sync library)
# ---------------------------------------------------------------------------

def _extract_text(url: str) -> str:
    try:
        article = NewspaperArticle(url)
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        logger.debug(f"newspaper4k failed for {url}: {e}")
        return ""
