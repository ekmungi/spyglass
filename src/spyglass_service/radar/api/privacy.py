"""What Spyglass sends out, and to whom, as plain data for the settings page.

GET /privacy/outbound returns:
  model_provider   which AI provider judges items, its host and models
  profile_block    the exact profile text the judging model is sent right now (after the scrub),
                   produced by the same functions the judge uses
  example_titles   {"liked": [...], "disliked": [...]} sent as examples of taste
  removed_before_sending   what is taken out of every prompt
  standing_instruction     the sentence that tells the model web text is not instructions
  destinations     every outside service: name, host, purpose, what is sent, whether it carries
                   a secret, whether it is in use now
  switches         the privacy switches with their current value and a plain description
"""

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from spyglass_service.radar.api.same_site import refuse_cross_site
from spyglass_service.radar.egress import destinations_for
from spyglass_service.radar.llm import model_for, provider
from spyglass_service.radar.privacy import STANDING_INSTRUCTION, scrub
from spyglass_service.radar.profile import get_profile, profile_prompt_block, refresh_examples

router = APIRouter()

SWITCHES: dict[str, str] = {
    "privacy_send_examples": (
        "Sends the titles of items you saved or turned down, as examples of your taste, to the "
        "AI that judges new items. Only items the radar placed in one of your sections qualify, "
        "at most 25 of each."),
    "privacy_proxy_images": (
        "Spyglass fetches the images inside articles itself, so your browser never contacts the "
        "sites that host them (no cookies, no address, no tracking pixels reach them)."),
    "jina_enabled": (
        "Lets an outside rendering service (Jina Reader) fetch pages that refuse every local "
        "method. That service learns which pages you read."),
    "privacy_allow_bot_checks": (
        "Lets the built-in browser complete a site's automated check; sends that service "
        "technical details of the browser, never anything personal."),
}
REMOVED = ["every configured secret (API keys, tokens, passwords)", "your e-mail address",
           "file paths inside your home folder (shown as ~)",
           "this computer's user and machine names inside file paths"]
_PROVIDERS = {
    "openrouter": {"name": "OpenRouter", "host": "openrouter.ai"},
    "claude_code": {"name": "Claude Code on this computer",
                    "host": "Anthropic's servers, reached by the claude program"},
}


def _model_provider(settings: object) -> dict:
    """The judging provider, its host and the model for each job."""
    key = provider(settings)
    return {**_PROVIDERS[key], "key": key,
            "models": {role: model_for(settings, role) for role in ("triage", "digest", "writer")}}


def _engine_overrides(settings: object, session: Session) -> dict[str, bool]:
    """Assistant destinations whose use depends on the engines document or the keyring."""
    from spyglass_service.radar.assist import registry

    doc = registry.load_doc(session)
    servers = any(k.startswith(registry.CUSTOM_PREFIX) or k in ("ollama", "lmstudio")
                  for k, conf in doc["engines"].items() if conf.get("enabled", True))
    overrides = {"local_models": servers}
    for engine_id in ("openrouter", "anthropic", "openai", "gemini"):
        key, _source = registry.resolve_key(settings, engine_id)
        if key:
            overrides[engine_id] = True
    return overrides


@router.get("/privacy/outbound", dependencies=[Depends(refuse_cross_site)])
def outbound(request: Request) -> dict:
    """Exactly what is sent where, built from the code paths that send it."""
    settings = request.app.state.settings
    with Session(request.app.state.engine) as session:
        profile = get_profile(session)
        examples = refresh_examples(session, settings=settings)
        overrides = _engine_overrides(settings, session)
    return {
        "model_provider": _model_provider(settings),
        "profile_block": scrub(profile_prompt_block(profile, examples), settings),
        "example_titles": examples,
        "removed_before_sending": REMOVED,
        "standing_instruction": STANDING_INSTRUCTION,
        "destinations": destinations_for(settings, overrides),
        "switches": {name: {"on": bool(getattr(settings, name, False)), "description": text}
                     for name, text in SWITCHES.items()},
    }
