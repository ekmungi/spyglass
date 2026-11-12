"""Shared helpers for the sources, capture and scheduler tests (no tests live here)."""

from email.message import EmailMessage
from types import SimpleNamespace

from sqlmodel import Session, select

from spyglass_service.db import create_db_engine, init_db
from spyglass_service.models import Item


def make_engine(tmp_path):
    """A fresh migrated database in tmp_path."""
    engine = create_db_engine(tmp_path / "t.db")
    init_db(engine)
    return engine


def make_settings(**overrides):
    """A settings stand-in with the fields the radar sources read."""
    base = {
        "gmail_address": None, "gmail_app_password": None,
        "gmail_newsletter_label": "Newsletters", "gmail_capture_label": "Spyglass",
        "slack_bot_token": None, "slack_capture_channel": "",
        "radar_brief_time": "06:30", "radar_timezone": "", "radar_collect_hours": 2.0,
        "data_dir": None,
    }
    return SimpleNamespace(**{**base, **overrides})


def all_items(engine, source: str | None = None) -> list[Item]:
    """Every stored item, optionally of one source."""
    with Session(engine) as session:
        query = select(Item)
        if source:
            query = query.where(Item.source == source)
        return list(session.exec(query).all())


def make_email(subject="Weekly digest", sender="The Digest <news@example.com>",
               html=None, text=None, message_id="<abc123@example.com>") -> EmailMessage:
    """A fixture email message with optional text and html bodies."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "me@example.com"
    msg["Subject"] = subject
    msg["Date"] = "Thu, 12 Nov 2026 06:00:00 +0000"
    if message_id:
        msg["Message-ID"] = message_id
    if text is not None:
        msg.set_content(text)
        if html is not None:
            msg.add_alternative(html, subtype="html")
    elif html is not None:
        msg.set_content(html, subtype="html")
    return msg
