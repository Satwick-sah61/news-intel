"""
Terminal interface for testing agents during backend development.

Commands:
    python cli.py run Iran War          # full pipeline + save to DB
    python cli.py start Iran War        # auto-scrape on schedule
    python cli.py changes Iran War      # show narrative changes
    python cli.py perception Iran War   # global perception analysis
    python cli.py chat Iran War         # interactive chat on stored data
    python cli.py timeline Iran War     # pipeline without saving
    python cli.py classify Iran War     # scrape + classify only
    python cli.py scrape Iran War       # scrape only
"""

import asyncio
import sys

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

# Windows asyncio fix
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

app = typer.Typer(help="News Intelligence — backend dev CLI")
console = Console()


@app.command()
def run(
    words: list[str] = typer.Argument(..., help="Topic words, e.g. Iran War"),
    days: int = typer.Option(2, "--days", "-d", help="Days back to search"),
    max_results: int = typer.Option(15, "--max", "-m", help="Max per source"),
):
    """Full pipeline: scrape -> classify -> timeline -> SAVE TO DATABASE."""
    topic = " ".join(words)
    asyncio.run(_run(topic, days, max_results))


async def _run(topic: str, days: int, max_results: int):
    from agents.scraping_agent import ScrapingAgent
    from agents.classification_agent import ClassificationAgent
    from agents.timeline_agent import TimelineAgent
    from database.session import init_db, AsyncSessionLocal
    from services.storage_service import (
        get_or_create_topic, save_articles, save_events, mark_topic_scraped
    )

    console.print(Panel(f"[bold cyan]Run Pipeline + Save:[/bold cyan] {topic}"))

    await init_db()

    # Scrape
    scraper = ScrapingAgent()
    try:
        raw = await scraper.scrape(topic, days_back=days, max_per_source=max_results)
    finally:
        await scraper.close()
    console.print(f"Scraped [yellow]{len(raw)}[/yellow] raw articles.")

    # Classify
    classified = await ClassificationAgent().classify(raw, topic)

    # Timeline
    events = await TimelineAgent().build(classified, topic)

    # Save to DB
    console.print(f"\n[bold]Saving to database...[/bold]", end=" ")
    async with AsyncSessionLocal() as session:
        db_topic = await get_or_create_topic(session, topic)
        url_map  = await save_articles(session, db_topic, classified)
        await save_events(session, db_topic, events, url_map)
        await mark_topic_scraped(session, db_topic)
        await session.commit()

    console.print(
        f"[green]done[/green] — "
        f"[yellow]{len(classified)}[/yellow] articles, "
        f"[yellow]{len(events)}[/yellow] events saved for topic '[cyan]{topic}[/cyan]'"
    )
    console.print(f"\nNow chat with this data:\n  [bold]python cli.py chat {topic}[/bold]\n")


@app.command()
def chat(
    words: list[str] = typer.Argument(..., help="Topic words, e.g. Iran War"),
    clear: bool = typer.Option(False, "--clear", help="Clear conversation history first"),
):
    """Interactive chat grounded in the stored timeline for a topic."""
    topic = " ".join(words)
    asyncio.run(_chat_loop(topic, clear))


async def _chat_loop(topic: str, clear_history: bool):
    from agents.chat_agent import ChatAgent
    from database.session import init_db, AsyncSessionLocal

    await init_db()

    console.print(Panel(
        f"[bold cyan]Chat:[/bold cyan] {topic}\n"
        f"[dim]Type your question. 'quit' or Ctrl+C to exit. '--clear' to reset history.[/dim]"
    ))

    agent = ChatAgent()

    async with AsyncSessionLocal() as session:
        if clear_history:
            await agent.clear_history(session, topic)
            console.print("[dim]Conversation history cleared.[/dim]\n")

        while True:
            try:
                question = input("You: ").strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Goodbye.[/dim]")
                break

            if not question:
                continue
            if question.lower() in ("quit", "exit", "q"):
                console.print("[dim]Goodbye.[/dim]")
                break

            console.print("[dim]Thinking...[/dim]")
            try:
                reply = await agent.chat(session, topic, question)
                console.print(Panel(reply, title="[bold green]Assistant[/bold green]", border_style="green"))
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")


@app.command()
def classify(
    words: list[str] = typer.Argument(..., help="Topic words, e.g. Iran War"),
    days: int = typer.Option(2, "--days", "-d", help="How many days back to search"),
    max_results: int = typer.Option(15, "--max", "-m", help="Max results per source"),
):
    """Scrape + classify articles: trust tier, relevance, entities, sentiment, summary."""
    topic = " ".join(words)
    asyncio.run(_classify(topic, days, max_results))


async def _classify(topic: str, days: int, max_results: int):
    from agents.scraping_agent import ScrapingAgent
    from agents.classification_agent import ClassificationAgent

    console.print(Panel(f"[bold cyan]Scrape + Classify:[/bold cyan] {topic}"))

    # Scrape
    scraper = ScrapingAgent()
    try:
        raw = await scraper.scrape(topic, days_back=days, max_per_source=max_results)
    finally:
        await scraper.close()

    console.print(f"Scraped [yellow]{len(raw)}[/yellow] raw articles. Classifying...")

    # Classify
    agent = ClassificationAgent()
    articles = await agent.classify(raw, topic)

    if not articles:
        console.print("[red]No relevant articles found.[/red]")
        return

    # Tier breakdown
    tier_counts = {1: 0, 2: 0, 3: 0}
    for a in articles:
        tier_counts[a.source_tier] += 1

    summary = Table(box=box.SIMPLE, show_header=False)
    summary.add_column("k", style="bold yellow")
    summary.add_column("v")
    summary.add_row("Relevant articles", str(len(articles)))
    summary.add_row("  Tier 1 — Major International", str(tier_counts[1]))
    summary.add_row("  Tier 2 — Regional / Established", str(tier_counts[2]))
    summary.add_row("  Tier 3 — Independent / Unknown", str(tier_counts[3]))
    console.print(summary)

    # Article table
    table = Table(
        "Title", "Source", "Tier", "Relevance", "Sentiment", "Region",
        box=box.MINIMAL_HEAVY_HEAD,
        show_lines=False,
    )
    TIER_COLOR = {1: "green", 2: "yellow", 3: "red"}
    SENT_COLOR = {"positive": "green", "negative": "red", "neutral": "white"}

    for a in articles[:40]:
        tier_str = f"[{TIER_COLOR[a.source_tier]}]T{a.source_tier}[/]"
        rel_str = f"{a.relevance_score:.2f}"
        sent_col = SENT_COLOR.get(a.sentiment, "white")
        sent_str = f"[{sent_col}]{a.sentiment}[/]"
        table.add_row(
            a.title[:60] + ("…" if len(a.title) > 60 else ""),
            a.source[:22],
            tier_str,
            rel_str,
            sent_str,
            a.region or "—",
        )
    console.print(table)

    # Show sample summaries + entities
    console.print("\n[bold]Sample article details (top 3):[/bold]")
    for a in articles[:3]:
        console.print(Panel(
            f"[bold]{a.title}[/bold]\n"
            f"[dim]{a.source} | {a.region} | Tier {a.source_tier} | relevance {a.relevance_score:.2f}[/dim]\n\n"
            f"[cyan]Summary:[/cyan] {a.summary}\n\n"
            f"[cyan]Key claims:[/cyan]\n" +
            "\n".join(f"  • {c}" for c in a.key_claims) + "\n\n"
            f"[cyan]Entities:[/cyan] "
            f"People: {', '.join(a.entities.get('people', [])) or '—'}  |  "
            f"Locations: {', '.join(a.entities.get('locations', [])) or '—'}  |  "
            f"Orgs: {', '.join(a.entities.get('organizations', [])) or '—'}",
        ))


@app.command()
def timeline(
    words: list[str] = typer.Argument(..., help="Topic words, e.g. Iran War"),
    days: int = typer.Option(2, "--days", "-d", help="Days back to search"),
    max_results: int = typer.Option(15, "--max", "-m", help="Max per source"),
):
    """Full pipeline: scrape -> classify -> build timeline."""
    topic = " ".join(words)
    asyncio.run(_timeline(topic, days, max_results))


async def _timeline(topic: str, days: int, max_results: int):
    from agents.scraping_agent import ScrapingAgent
    from agents.classification_agent import ClassificationAgent
    from agents.timeline_agent import TimelineAgent
    from rich import box

    console.print(Panel(f"[bold cyan]Full Pipeline:[/bold cyan] {topic}"))

    # Scrape
    scraper = ScrapingAgent()
    try:
        raw = await scraper.scrape(topic, days_back=days, max_per_source=max_results)
    finally:
        await scraper.close()
    console.print(f"Scraped [yellow]{len(raw)}[/yellow] raw articles.")

    # Classify
    classified = await ClassificationAgent().classify(raw, topic)

    # Timeline
    events = await TimelineAgent().build(classified, topic)

    if not events:
        console.print("[red]No events found.[/red]")
        return

    # Display
    console.print(f"\n[bold green]Timeline: {topic}[/bold green]  ({len(events)} events)\n")

    TYPE_COLOR = {
        "Military": "red", "Diplomatic": "blue", "Economic": "yellow",
        "Political": "magenta", "Social": "cyan",
    }
    STATE_COLOR = {
        "Breaking": "bold red", "Developing": "yellow",
        "Confirmed": "green", "Resolved": "dim",
    }

    for i, ev in enumerate(events, 1):
        tc = TYPE_COLOR.get(ev.event_type, "white")
        sc = STATE_COLOR.get(ev.narrative_state, "white")
        date = ev.first_seen[:10] if ev.first_seen else "unknown"

        console.print(
            f"[dim]{i:02d}[/dim]  [{tc}]{ev.event_type:<12}[/{tc}]  "
            f"[{sc}]{ev.narrative_state:<11}[/{sc}]  "
            f"[dim]{date}[/dim]  "
            f"[bold]{ev.headline}[/bold]"
        )
        console.print(
            f"      [dim]Sources: {ev.source_count} "
            f"(T1:{ev.tier1_count})  "
            f"Trust: {ev.trust_label}  "
            f"Significance: {ev.significance_score:.2f}  "
            f"Sentiment: {ev.dominant_sentiment}[/dim]"
        )
        console.print(f"      {ev.summary}")

        if ev.locations or ev.people:
            parts = []
            if ev.locations:
                parts.append(f"Locations: {', '.join(ev.locations[:4])}")
            if ev.people:
                parts.append(f"People: {', '.join(ev.people[:4])}")
            console.print(f"      [dim]{' | '.join(parts)}[/dim]")

        console.print()


@app.command()
def scrape(
    words: list[str] = typer.Argument(..., help="Topic words, e.g. Iran War"),
    days: int = typer.Option(2, "--days", "-d", help="How many days back to search"),
    max_results: int = typer.Option(15, "--max", "-m", help="Max results per source"),
):
    """Scrape news for a topic and display results in a table."""
    topic = " ".join(words)
    asyncio.run(_scrape(topic, days, max_results))


async def _scrape(topic: str, days: int, max_results: int):
    from agents.scraping_agent import ScrapingAgent

    console.print(Panel(f"[bold cyan]Scraping:[/bold cyan] {topic}  |  days_back={days}  |  max_per_source={max_results}"))

    agent = ScrapingAgent()
    try:
        articles = await agent.scrape(topic, days_back=days, max_per_source=max_results)
    finally:
        await agent.close()

    if not articles:
        console.print("[red]No articles found.[/red]")
        return

    # Summary by source type
    by_type: dict[str, int] = {}
    by_region: dict[str, int] = {}
    for a in articles:
        by_type[a.source_type] = by_type.get(a.source_type, 0) + 1
        region = a.region or "Unknown"
        by_region[region] = by_region.get(region, 0) + 1

    summary = Table(box=box.SIMPLE, show_header=False)
    summary.add_column("key", style="bold yellow")
    summary.add_column("val")
    summary.add_row("Total articles", str(len(articles)))
    for k, v in sorted(by_type.items()):
        summary.add_row(f"  {k}", str(v))
    console.print(summary)

    # Article table
    table = Table(
        "Title", "Source", "Region", "Published", "Type", "Content len",
        box=box.MINIMAL_HEAVY_HEAD,
        show_lines=False,
    )

    for a in articles[:50]:  # show up to 50
        pub = a.published_at.strftime("%Y-%m-%d %H:%M") if a.published_at else "unknown"
        content_preview = f"{len(a.content)} chars"
        table.add_row(
            a.title[:70] + ("…" if len(a.title) > 70 else ""),
            a.source[:25],
            a.region or "—",
            pub,
            a.source_type,
            content_preview,
        )

    console.print(table)

    # Region breakdown
    if by_region:
        console.print("\n[bold]Region coverage:[/bold]")
        for region, count in sorted(by_region.items(), key=lambda x: -x[1]):
            bar = "#" * count
            console.print(f"  {region:<20} {bar} ({count})")


@app.command()
def perception(
    words: list[str] = typer.Argument(..., help="Topic words, e.g. Iran War"),
    max_posts: int = typer.Option(60, "--max", "-m", help="Max social posts to fetch"),
):
    """Fetch social media posts and show how each region perceives the topic."""
    topic = " ".join(words)
    asyncio.run(_perception(topic, max_posts))


async def _perception(topic: str, max_posts: int):
    from agents.social_agent import SocialAgent
    from services.perception_service import analyse_perception

    console.print(Panel(f"[bold cyan]Global Perception:[/bold cyan] {topic}"))

    # Fetch social posts
    console.print("Fetching social media posts...", end=" ")
    agent = SocialAgent()
    try:
        posts = await agent.fetch(topic, max_posts=max_posts)
    finally:
        await agent.close()
    console.print(f"[green]done[/green] — {len(posts)} posts from "
                  f"{set(p.platform for p in posts)}")

    if not posts:
        console.print("[red]No social posts found.[/red]")
        return

    # Analyse perception per region
    console.print("Analysing regional sentiment via GPT-4o-mini...")
    perceptions = await analyse_perception(posts, topic)

    if not perceptions:
        console.print("[red]No regional perceptions generated.[/red]")
        return

    console.print(f"\n[bold]How the world sees: [cyan]{topic}[/cyan][/bold]\n")

    SENT_COLOR = {"positive": "green", "negative": "red", "neutral": "yellow"}
    SENT_BAR   = {"positive": "+", "negative": "-", "neutral": "="}

    for p in perceptions:
        col = SENT_COLOR.get(p.sentiment, "white")
        bar_char = SENT_BAR.get(p.sentiment, "=")
        bar = bar_char * min(p.post_count * 2, 30)
        score_str = f"{p.sentiment_score:+.2f}"

        console.print(
            f"[bold]{p.region:<22}[/bold] "
            f"[{col}]{p.sentiment:<10}[/{col}] "
            f"[dim]{score_str}[/dim]  "
            f"[{col}]{bar}[/{col}]  "
            f"[dim]({p.post_count} posts | {p.platform_breakdown})[/dim]"
        )
        console.print(f"  [italic]{p.dominant_narrative}[/italic]")

        if p.key_themes:
            console.print(f"  Themes: [dim]{', '.join(p.key_themes)}[/dim]")

        if p.sample_quotes:
            for q in p.sample_quotes[:2]:
                console.print(f"  [dim]> {q[:120]}[/dim]")

        console.print()


@app.command()
def start(
    words: list[str] = typer.Argument(..., help="Topic words, e.g. Iran War"),
    interval: int = typer.Option(30, "--interval", "-i", help="Scrape interval in minutes"),
):
    """Start auto-scraping a topic on a schedule (Ctrl+C to stop)."""
    topic = " ".join(words)
    asyncio.run(_start(topic, interval))


async def _start(topic: str, interval_min: int):
    import signal
    from database.session import init_db, AsyncSessionLocal
    from database.models import TopicSchedule
    from services.storage_service import get_or_create_topic
    from scheduler.jobs import scrape_and_update, register_topic_job, stop_scheduler
    from sqlalchemy import select

    console.print(Panel(
        f"[bold cyan]Auto-scrape:[/bold cyan] {topic}\n"
        f"[dim]Interval: every {interval_min} minute(s). Ctrl+C to stop.[/dim]"
    ))

    await init_db()

    # Persist / update a TopicSchedule row
    async with AsyncSessionLocal() as session:
        db_topic = await get_or_create_topic(session, topic)

        result = await session.execute(
            select(TopicSchedule).where(TopicSchedule.topic_id == db_topic.id)
        )
        sched_row = result.scalar_one_or_none()
        if sched_row is None:
            sched_row = TopicSchedule(
                topic_id=db_topic.id,
                interval_min=interval_min,
                active=True,
            )
            session.add(sched_row)
        else:
            sched_row.interval_min = interval_min
            sched_row.active = True

        await session.commit()

    # Run one immediate pipeline pass
    console.print("[bold]Running initial pipeline pass...[/bold]")
    try:
        await scrape_and_update(topic)
    except Exception as exc:
        console.print(f"[red]Initial pipeline error: {exc}[/red]")

    # Register the recurring interval job
    register_topic_job(topic, interval_min)
    console.print(
        f"[green]Scheduler running[/green] — next run in "
        f"[yellow]{interval_min}[/yellow] minute(s). "
        f"Press [bold]Ctrl+C[/bold] to stop."
    )

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _handle_sigint(*_):
        console.print("\n[dim]Shutting down scheduler...[/dim]")
        stop_scheduler()
        stop_event.set()

    # Windows SelectorEventLoop doesn't support add_signal_handler;
    # KeyboardInterrupt is caught in the except block instead.
    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
        loop.add_signal_handler(signal.SIGTERM, _handle_sigint)
    except (NotImplementedError, AttributeError):
        pass  # Windows — rely on KeyboardInterrupt below

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        _handle_sigint()

    console.print("[dim]Stopped.[/dim]")


@app.command()
def changes(
    words: list[str] = typer.Argument(..., help="Topic words, e.g. Iran War"),
):
    """Show detected narrative changes for a topic."""
    topic = " ".join(words)
    asyncio.run(_changes(topic))


async def _changes(topic: str):
    from database.session import init_db, AsyncSessionLocal
    from database.models import NarrativeChange, Topic
    from sqlalchemy import select

    await init_db()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Topic).where(Topic.name == topic))
        db_topic = result.scalar_one_or_none()

        if not db_topic:
            console.print(f"[red]Topic not found:[/red] {topic!r}")
            raise typer.Exit(1)

        result = await session.execute(
            select(NarrativeChange)
            .where(NarrativeChange.topic_id == db_topic.id)
            .order_by(NarrativeChange.detected_at.desc())
        )
        rows: list[NarrativeChange] = list(result.scalars())

    if not rows:
        console.print(
            f"[yellow]No narrative changes recorded for topic:[/yellow] {topic!r}"
        )
        return

    CHANGE_COLOR = {
        "new_event":    "bold green",
        "escalation":   "bold red",
        "confirmed":    "green",
        "state_change": "yellow",
    }

    table = Table(
        "Detected",
        "Type",
        "Significance",
        "Delivered",
        "Headline",
        box=box.MINIMAL_HEAVY_HEAD,
        show_lines=True,
        title=f"Narrative Changes — {topic}",
    )

    for row in rows:
        color = CHANGE_COLOR.get(row.change_type, "white")
        detected = (
            row.detected_at.strftime("%Y-%m-%d %H:%M")
            if row.detected_at else "—"
        )
        table.add_row(
            detected,
            f"[{color}]{row.change_type}[/{color}]",
            f"{row.significance:.2f}",
            "[green]yes[/green]" if row.delivered else "[dim]no[/dim]",
            (row.headline or "")[:80],
        )

    console.print(table)
    console.print()

    # Show description panels for the 10 most recent changes
    for row in rows[:10]:
        color = CHANGE_COLOR.get(row.change_type, "white")
        console.print(Panel(
            row.description or "—",
            title=(
                f"[{color}]{row.change_type.upper()}[/{color}]"
                f"  {row.headline or ''}"
            ),
            border_style=color.replace("bold ", ""),
        ))


if __name__ == "__main__":
    app()
