"""The starting profile: who the reader is, the sections items are sorted into, and topics.

The profile is one JSON document (RadarDoc key "profile"). It is sent to the model that
judges relevance, so it holds only public topics and never internal project detail.
"""

from sqlmodel import Session

from spyglass_service.radar.models import RadarDoc, loads

PROFILE_KEY = "profile"

# Section keys are stable identifiers stored on every assessment; labels are editable.
DEFAULT_SECTIONS: list[dict] = [
    {"key": "models", "label": "Models & platforms",
     "description": "Major model releases and platform or product updates from AI companies."},
    {"key": "labs", "label": "Labs & research",
     "description": "What the major AI research labs publish: blog posts, notable research, "
                    "technical reports."},
    {"key": "agents", "label": "Building with agents",
     "description": "Practical agent engineering: harnesses, MCP servers, coding agents, "
                    "skills, memory, how-to guides and useful repositories."},
    {"key": "health", "label": "Healthcare AI & medtech",
     "description": "AI in healthcare and medical imaging; validation and regulation of "
                    "AI systems used in clinical settings."},
    {"key": "industry", "label": "Industry & use cases",
     "description": "How companies in different industries put AI to use; adoption reports "
                    "and case studies."},
    {"key": "direction", "label": "Where AI is heading",
     "description": "Strategy, economics, policy and well-argued views on the direction of "
                    "the AI industry."},
]

DEFAULT_PROFILE: dict = {
    "version": 1,
    "statement": (
        "Someone who follows AI closely and builds with AI agents, and wants a short daily "
        "picture of AI and the fields they care about."
    ),
    "sections": DEFAULT_SECTIONS,
    "topics": [
        {"name": "New model releases", "section": "models"},
        {"name": "Open-weights models", "section": "models"},
        {"name": "Agent tooling and coding agents", "section": "agents"},
        {"name": "Evaluation methods for AI systems", "section": "labs"},
        {"name": "AI in medical imaging", "section": "health"},
        {"name": "AI regulation", "section": "health"},
        {"name": "AI in science", "section": "industry"},
        {"name": "Industry adoption of AI", "section": "industry"},
    ],
    "avoid": [
        "Consumer gadget deals and reviews", "Games, puzzles and entertainment",
        "Sports", "Celebrity and lifestyle", "Generic listicles with no new information",
    ],
}


def load_profile(session: Session) -> dict:
    """Return the stored profile, or the default when none has been saved yet."""
    row = session.get(RadarDoc, PROFILE_KEY)
    profile = loads(row.body if row else None, None)
    return profile if isinstance(profile, dict) and profile.get("sections") else DEFAULT_PROFILE


def section_label(session: Session, key: str) -> str:
    """Display label for a section key; the key itself when the profile does not define it."""
    for section in load_profile(session).get("sections", []):
        if section.get("key") == key:
            return str(section.get("label") or key)
    return key
