"""
Social Agent — fetches public social media content for perception analysis.

Sources (all using existing Tavily API key — no extra credentials needed):
  1. Tavily targeted search  — searches Reddit, YouTube, Twitter/X content
  2. Reddit via PRAW         — if REDDIT_CLIENT_ID is set in .env
  3. YouTube Data API        — if YOUTUBE_API_KEY is set in .env

Output: list of SocialPost objects with platform, region hint, content, url.
These feed into the PerceptionService for regional sentiment aggregation.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from tavily import TavilyClient

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class SocialPost:
    platform: str        # reddit / youtube / twitter / web
    url: str
    title: str
    content: str         # post text / comment / description
    author: str
    region_hint: str     # country/region if detectable, else ""
    upvotes: int         # likes/upvotes (0 if unavailable)
    published_at: str    # ISO string or ""


# Subreddits relevant to geopolitics / news
GEOPOLITICS_SUBREDDITS = [
    "geopolitics", "worldnews", "news", "CredibleDefense",
    "MiddleEast", "iran", "worldpolitics", "GlobalAffairs",
]

# YouTube search terms appended to topic for relevant news videos
YOUTUBE_SEARCH_SUFFIX = "news analysis latest"


class SocialAgent:

    def __init__(self):
        self._tavily = TavilyClient(api_key=settings.tavily_api_key)
        self._http = httpx.AsyncClient(timeout=20, follow_redirects=True)
        self._has_reddit = bool(settings.reddit_client_id and settings.reddit_client_secret)
        self._has_youtube = bool(settings.youtube_api_key)

    async def close(self):
        await self._http.aclose()

    async def fetch(self, topic: str, max_posts: int = 60) -> list[SocialPost]:
        """Fetch social posts from all available sources in parallel."""
        logger.info(f"SocialAgent fetching for topic='{topic}'")

        tasks = [self._search_tavily_social(topic, max_posts // 3)]

        if self._has_reddit:
            tasks.append(self._fetch_reddit(topic, max_posts // 3))
        else:
            tasks.append(self._search_tavily_reddit(topic, max_posts // 4))

        if self._has_youtube:
            tasks.append(self._fetch_youtube(topic, max_posts // 4))
        else:
            tasks.append(self._search_tavily_youtube(topic, max_posts // 4))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        posts: list[SocialPost] = []
        labels = ["tavily-social", "reddit", "youtube"]
        for label, result in zip(labels, results):
            if isinstance(result, Exception):
                logger.warning(f"Social source '{label}' failed: {result}")
            else:
                posts.extend(result)
                logger.info(f"  {label}: {len(result)} posts")

        logger.info(f"Total social posts: {len(posts)}")
        return posts

    # ------------------------------------------------------------------
    # Tavily — general social search
    # ------------------------------------------------------------------

    async def _search_tavily_social(self, topic: str, limit: int) -> list[SocialPost]:
        loop = asyncio.get_event_loop()

        def _call():
            return self._tavily.search(
                query=f"{topic} site:reddit.com OR site:twitter.com OR site:youtube.com",
                search_depth="basic",
                max_results=min(limit, 10),
                topic="general",
            )

        try:
            resp = await loop.run_in_executor(None, _call)
        except Exception as e:
            logger.debug(f"Tavily social search failed: {e}")
            return []

        posts = []
        for r in resp.get("results", []):
            url = r.get("url", "")
            platform = _detect_platform(url)
            posts.append(SocialPost(
                platform=platform,
                url=url,
                title=r.get("title", ""),
                content=(r.get("content") or "")[:1500],
                author="",
                region_hint="",
                upvotes=0,
                published_at="",
            ))
        return posts

    async def _search_tavily_reddit(self, topic: str, limit: int) -> list[SocialPost]:
        """Fallback when no Reddit API — search Reddit via Tavily."""
        loop = asyncio.get_event_loop()

        posts = []
        for subreddit in ["worldnews", "geopolitics", "MiddleEast"]:
            def _call(sr=subreddit):
                return self._tavily.search(
                    query=f"{topic} site:reddit.com/r/{sr}",
                    search_depth="basic",
                    max_results=5,
                    topic="general",
                )
            try:
                resp = await loop.run_in_executor(None, _call)
                for r in resp.get("results", []):
                    posts.append(SocialPost(
                        platform="reddit",
                        url=r.get("url", ""),
                        title=r.get("title", ""),
                        content=(r.get("content") or "")[:1500],
                        author="",
                        region_hint="",
                        upvotes=0,
                        published_at="",
                    ))
            except Exception as e:
                logger.debug(f"Tavily Reddit search for r/{subreddit} failed: {e}")

        return posts[:limit]

    async def _search_tavily_youtube(self, topic: str, limit: int) -> list[SocialPost]:
        """Fallback when no YouTube API — search YouTube via Tavily."""
        loop = asyncio.get_event_loop()

        def _call():
            return self._tavily.search(
                query=f"{topic} {YOUTUBE_SEARCH_SUFFIX} site:youtube.com",
                search_depth="basic",
                max_results=min(limit, 10),
                topic="general",
            )

        try:
            resp = await loop.run_in_executor(None, _call)
        except Exception as e:
            logger.debug(f"Tavily YouTube search failed: {e}")
            return []

        posts = []
        for r in resp.get("results", []):
            posts.append(SocialPost(
                platform="youtube",
                url=r.get("url", ""),
                title=r.get("title", ""),
                content=(r.get("content") or "")[:1500],
                author="",
                region_hint="",
                upvotes=0,
                published_at="",
            ))
        return posts

    # ------------------------------------------------------------------
    # Reddit via PRAW (when credentials available)
    # ------------------------------------------------------------------

    async def _fetch_reddit(self, topic: str, limit: int) -> list[SocialPost]:
        loop = asyncio.get_event_loop()
        posts = await loop.run_in_executor(None, self._fetch_reddit_sync, topic, limit)
        return posts

    def _fetch_reddit_sync(self, topic: str, limit: int) -> list[SocialPost]:
        try:
            import praw
        except ImportError:
            logger.warning("praw not installed — pip install praw")
            return []

        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent="NewsIntelBot/1.0",
            check_for_async=False,
        )

        posts = []
        per_sub = max(1, limit // len(GEOPOLITICS_SUBREDDITS))

        for sr_name in GEOPOLITICS_SUBREDDITS:
            try:
                sr = reddit.subreddit(sr_name)
                for submission in sr.search(topic, sort="new", time_filter="week", limit=per_sub):
                    posts.append(SocialPost(
                        platform="reddit",
                        url=f"https://reddit.com{submission.permalink}",
                        title=submission.title,
                        content=submission.selftext[:1500] if submission.selftext else "",
                        author=str(submission.author) if submission.author else "",
                        region_hint=_reddit_region_hint(sr_name),
                        upvotes=submission.score,
                        published_at=datetime.fromtimestamp(
                            submission.created_utc, tz=timezone.utc
                        ).isoformat(),
                    ))
                    if len(posts) >= limit:
                        break
            except Exception as e:
                logger.debug(f"Reddit r/{sr_name} failed: {e}")

        return posts[:limit]

    # ------------------------------------------------------------------
    # YouTube Data API (when key available)
    # ------------------------------------------------------------------

    async def _fetch_youtube(self, topic: str, limit: int) -> list[SocialPost]:
        query = f"{topic} {YOUTUBE_SEARCH_SUFFIX}"
        url = (
            f"https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&q={query}&type=video&order=date"
            f"&maxResults={min(limit, 25)}&key={settings.youtube_api_key}"
        )
        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"YouTube API failed: {e}")
            return []

        posts = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            vid_id = item.get("id", {}).get("videoId", "")
            posts.append(SocialPost(
                platform="youtube",
                url=f"https://youtube.com/watch?v={vid_id}",
                title=snippet.get("title", ""),
                content=snippet.get("description", "")[:1500],
                author=snippet.get("channelTitle", ""),
                region_hint=snippet.get("channelCountry", ""),
                upvotes=0,
                published_at=snippet.get("publishedAt", ""),
            ))
        return posts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_platform(url: str) -> str:
    url = url.lower()
    if "reddit.com" in url:
        return "reddit"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "twitter.com" in url or "x.com" in url:
        return "twitter"
    return "web"


def _reddit_region_hint(subreddit: str) -> str:
    _MAP = {
        "iran": "Iran", "MiddleEast": "Middle East",
        "worldnews": "Global", "geopolitics": "Global",
        "news": "US", "CredibleDefense": "US",
    }
    return _MAP.get(subreddit, "")
