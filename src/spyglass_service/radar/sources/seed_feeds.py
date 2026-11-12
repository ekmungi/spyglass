"""A curated starter set of feeds, added through the engine's feed registry.

Every address here was fetched and parsed on the date noted in SEEDS_VERIFIED; a feed that could
not be verified is left out (see NOT_AVAILABLE for the notable ones and why). Feeds go through
`feed_registry.add_feed`, the same path as the Feeds screen, so the `Feed` table and the reader
library's own database stay consistent: the registry row is the source of truth, and the RSS
collector subscribes the reader library to every enabled row at the next collection.
"""

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from spyglass_service.config import Settings
from spyglass_service.feed_registry import NotAFeedError, add_feed
from spyglass_service.models import Feed

logger = logging.getLogger(__name__)

SEEDS_VERIFIED = "2026-11-12"

# (display name, feed address, group). The group is documentation only.
_ARXIV_AGENTS = (
    "https://export.arxiv.org/api/query?search_query="
    "(abs:%22coding+agent%22+OR+abs:%22agent+harness%22+OR+abs:%22model+context+protocol%22"
    "+OR+abs:%22LLM+agents%22+OR+abs:%22agentic+workflow%22)+AND+"
    "(cat:cs.AI+OR+cat:cs.SE+OR+cat:cs.CL)&sortBy=submittedDate&sortOrder=descending"
    "&max_results=30"
)
SEEDS: tuple[tuple[str, str, str], ...] = (
    # Research labs and company blogs
    ("OpenAI News", "https://openai.com/news/rss.xml", "labs"),
    ("Google Research", "https://research.google/blog/rss/", "labs"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "labs"),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/", "labs"),
    ("Engineering at Meta", "https://engineering.fb.com/feed/", "labs"),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml", "labs"),
    ("NVIDIA Blog", "https://blogs.nvidia.com/feed/", "labs"),
    ("Apple Machine Learning Research", "https://machinelearning.apple.com/rss.xml", "labs"),
    ("Amazon Science", "https://www.amazon.science/index.rss", "labs"),
    ("Mistral Blog", "https://mistral.ai/rss.xml", "labs"),
    # Anthropic publishes no official feed; these are community-maintained mirrors of its
    # site, so they can lag or disappear. The news search also covers the company.
    ("Anthropic News (mirror)",
     "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
     "labs"),
    ("Anthropic Engineering (mirror)",
     "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/"
     "feed_anthropic_engineering.xml", "labs"),
    # News
    ("Techmeme", "https://www.techmeme.com/feed.xml", "news"),
    ("MIT Technology Review - AI",
     "https://www.technologyreview.com/topic/artificial-intelligence/feed", "news"),
    ("The Verge - AI",
     "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "news"),
    ("Ars Technica - AI", "https://arstechnica.com/ai/feed/", "news"),
    ("STAT - Health Tech", "https://www.statnews.com/category/health-tech/feed/", "news"),
    ("Fierce Healthcare", "https://www.fiercehealthcare.com/rss/xml", "news"),
    ("MedTech Dive", "https://www.medtechdive.com/feeds/news/", "news"),
    ("Endpoints News", "https://endpts.com/feed/", "news"),
    # Practitioner writing
    ("Simon Willison's Weblog", "https://simonwillison.net/atom/everything/", "practitioner"),
    ("Latent Space", "https://www.latent.space/feed", "practitioner"),
    ("Import AI", "https://importai.substack.com/feed", "practitioner"),
    ("LangChain Blog", "https://blog.langchain.com/rss.xml", "practitioner"),
    ("The Pragmatic Engineer", "https://newsletter.pragmaticengineer.com/feed", "practitioner"),
    ("Ahead of AI", "https://magazine.sebastianraschka.com/feed", "practitioner"),
    ("Interconnects", "https://www.interconnects.ai/feed", "practitioner"),
    # Healthcare AI and regulation
    ("NEJM AI", "https://ai.nejm.org/action/showFeed?type=etoc&feed=rss&jc=ai", "health"),
    ("npj Digital Medicine", "https://www.nature.com/npjdigitalmed.rss", "health"),
    ("Nature Medicine", "https://www.nature.com/nm.rss", "health"),
    ("Hardian Health - Insights", "https://www.hardianhealth.com/insights/rss.xml", "health"),
    # Targeted papers
    ("arXiv: agent engineering", _ARXIV_AGENTS, "papers"),
)

# Feeds a person asked for that have no usable address, with the reason, for the sources screen
# and the maintainer. Covered by the news search instead where noted.
NOT_AVAILABLE: dict[str, str] = {
    "Anthropic (official)": "no official feed; mirrored above and covered by the news search",
    "Meta AI blog": "the site refuses automated clients (HTTP 400) and offers no feed",
    "DeepSeek": "no feed; its docs site serves HTML only; covered by the news search",
    "Fierce Biotech / Fierce MedTech": "the site blocks automated clients (HTTP 403)",
    "AINews": "its feed parses but has published nothing since early September",
    "FDA press releases": "the feed answers 404 to the browser-style agent the feed reader "
                          "sends (it works with a plain agent); covered by the news search",
    "FDA medical devices": "no device-specific feed address could be found",
}

AddFn = Callable[[Session, str, str, Path], Feed]


def _registry_add(session: Session, url: str, name: str, scratch: Path) -> Feed:
    """Add through the engine's registry (resolves, validates by fetching, de-duplicates)."""
    return add_feed(session, url, name=name, reader_db_path=scratch)


def apply_seed_feeds(
    engine: Engine,
    settings: Settings,
    *,
    add: AddFn | None = None,
    seeds: tuple[tuple[str, str, str], ...] | None = None,
) -> dict:
    """Add the curated feeds that are missing. Idempotent; never touches a feed already there.

    Args:
        engine: Database engine.
        settings: Runtime settings (unused; kept for the shared signature).
        add: Callable (session, url, name, scratch_db_path) -> Feed; the registry by default.
        seeds: Override of the curated list (tests).

    Returns:
        {"added": [names], "existing": [names], "failed": [{"name", "url", "error"}]}.
        A failing feed is reported and never stops the others.
    """
    add = add or _registry_add
    result: dict = {"added": [], "existing": [], "failed": []}
    with Session(engine) as session:
        known = set(session.exec(select(Feed.feed_url)).all())
    with tempfile.TemporaryDirectory(prefix="spyglass-seed-") as scratch_dir:
        scratch = Path(scratch_dir) / "validate_reader.db"
        for name, url, _group in seeds if seeds is not None else SEEDS:
            if url in known:
                result["existing"].append(name)
                continue
            with Session(engine) as session:
                try:
                    feed = add(session, url, name, scratch)
                except NotAFeedError as exc:
                    result["failed"].append({"name": name, "url": url, "error": exc.reason})
                    continue
                except Exception as exc:  # noqa: BLE001 -- one bad feed never stops the rest
                    logger.exception("seed feed failed: %s", name)
                    result["failed"].append({"name": name, "url": url, "error": str(exc)[:200]})
                    continue
                if feed.added_via == "manual":
                    feed.added_via = "seed"
                    session.add(feed)
                    session.commit()
                result["added"].append(name)
    return result
