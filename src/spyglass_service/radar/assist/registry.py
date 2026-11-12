"""Which assistant engines exist, which are usable now, and how the reader configures them.

Non-secret configuration is one JSON document (RadarDoc key "engines"):
  {"version": 1, "engines": {"<id>": {"enabled": bool, "models": [...], "default_model": str,
                                       "base_url": str, "label": str}}}
Custom OpenAI-compatible servers are entries whose id starts with "custom-".
API keys never go in that document. They come from the environment (through settings) first and
then from the OS keyring; `configure_engine` writes a typed-in key to the keyring only.
"""

import re
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session

from spyglass_service.config import Settings
from spyglass_service.radar.assist import secrets_store
from spyglass_service.radar.assist.engines.anthropic_api import DEFAULT_MODELS as ANTHROPIC_MODELS
from spyglass_service.radar.assist.engines.anthropic_api import AnthropicEngine
from spyglass_service.radar.assist.engines.antigravity import MODELS as AGY_MODELS
from spyglass_service.radar.assist.engines.antigravity import AntigravityEngine
from spyglass_service.radar.assist.engines.base import Engine
from spyglass_service.radar.assist.engines.claude_code import ClaudeCodeEngine
from spyglass_service.radar.assist.engines.codex_cli import MODELS as CODEX_MODELS
from spyglass_service.radar.assist.engines.codex_cli import CodexCliEngine
from spyglass_service.radar.assist.model_choice import AUTO, PAIRS, offers_auto
from spyglass_service.radar.assist.engines.openai_compat import (
    PRESETS,
    OpenAICompatEngine,
    clear_probe_cache,
)
from spyglass_service.radar.models import RadarDoc, dumps, loads, utcnow

DOC_KEY = "engines"
# Order used to choose the default engine when the reader has not chosen one.
ENGINE_ORDER = ("openrouter", "anthropic", "openai", "gemini", "claude_code", "antigravity",
                "codex_cli", "lmstudio", "ollama")
# Command-line engines: switched on by the reader (setting or switch), not by a key.
CLI_ENGINES = ("claude_code", "antigravity", "codex_cli")
CUSTOM_PREFIX = "custom-"

# Ids as OpenRouter lists them, checked against its public model catalogue.
OPENROUTER_MODELS: list[dict] = [
    {"id": "anthropic/claude-sonnet-5.5", "label": "Claude Sonnet 5.5"},
    {"id": "anthropic/claude-haiku-5.5", "label": "Claude Haiku 5.5 (fast)"},
    {"id": "openai/gpt-6.1-sol", "label": "GPT-6.1 Sol"},
    {"id": "google/gemini-4-carbon", "label": "Gemini 4 Carbon"},
    {"id": "google/gemini-3.8-flash", "label": "Gemini 3.8 Flash (fast)"},
    {"id": "deepseek/deepseek-v4.1-flash", "label": "DeepSeek V4.1 Flash"},
    {"id": "qwen/qwen3.8-27b", "label": "Qwen3.8 27B (open weights)"},
]
OPENAI_MODELS: list[dict] = [
    {"id": "gpt-6.1-sol", "label": "GPT-6.1 Sol"},
    {"id": "gpt-6.1-terra", "label": "GPT-6.1 Terra"},
]
# The address of an engine that is paired with a key from the environment or the keyring is fixed
# in code: if it could be changed through the API, any page or local program able to reach this
# service could point the key at its own server. Only local servers (which take no key) and
# "custom-*" servers (whose key is stored under their own id) have an address the reader sets.
LOCAL_ENGINES = ("ollama", "lmstudio")
# Ids as the Gemini API lists them: the strongest model, then a fast one.
GEMINI_MODELS: list[dict] = [
    {"id": "gemini-4-carbon", "label": "Gemini 4 Carbon"},
    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash (fast)"},
]
_CURATED = {"openrouter": OPENROUTER_MODELS, "openai": OPENAI_MODELS, "gemini": GEMINI_MODELS}
_SETTINGS_KEY = {"openrouter": "openrouter_api_key", "anthropic": "anthropic_api_key",
                 "openai": "openai_api_key", "gemini": "gemini_api_key"}


def address_is_editable(engine_id: str) -> bool:
    """Whether the reader may set this engine's address (see the note above LOCAL_ENGINES)."""
    return engine_id in LOCAL_ENGINES or engine_id.startswith(CUSTOM_PREFIX)


def valid_base_url(url: object) -> bool:
    """True for an http(s) address with a host; anything else (file:, ftp:, javascript:) is not."""
    if not isinstance(url, str) or re.search(r"\s", url):
        return False
    try:
        parts = urlsplit(url)
        return parts.scheme in ("http", "https") and bool(parts.hostname)
    except ValueError:
        return False


def effective_base_url(engine_id: str, conf: dict) -> str | None:
    """The address to use for an engine: the stored one only where the reader may set it.

    A stored address on an engine with a fixed address (a hostile or stale value) is ignored, and
    so is a stored address that is not a valid http(s) address.
    """
    stored = conf.get("base_url")
    if address_is_editable(engine_id) and valid_base_url(stored):
        return stored
    return (PRESETS.get(engine_id) or {}).get("base_url")


def known_engine_ids(session: Session | None) -> list[str]:
    """Every engine id the registry would list: the built-in ones, then the custom servers."""
    return _all_ids(load_doc(session))


def load_doc(session: Session | None) -> dict:
    """The stored engines document, or an empty one."""
    row = session.get(RadarDoc, DOC_KEY) if session is not None else None
    doc = loads(row.body if row else None, None)
    if not isinstance(doc, dict) or not isinstance(doc.get("engines"), dict):
        return {"version": 1, "engines": {}}
    return doc


def _save_doc(session: Session, doc: dict) -> None:
    """Write the engines document (never contains a key)."""
    row = session.get(RadarDoc, DOC_KEY)
    if row is None:
        row = RadarDoc(key=DOC_KEY, body=dumps(doc))
    row.body = dumps(doc)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()


def resolve_key(settings: Settings, engine_id: str) -> tuple[str | None, str | None]:
    """(key, source) where source is "env" or "keyring"; (None, None) when no key exists."""
    attr = _SETTINGS_KEY.get(engine_id)
    value = getattr(settings, attr, None) if attr else None
    if value:
        return value, "env"
    stored = secrets_store.get_secret(engine_id)
    return (stored, "keyring") if stored else (None, None)


def _model_dicts(raw: list) -> list[dict]:
    """Accept ["id", ...] or [{"id","label"}, ...] and return [{"id","label"}]."""
    out: list[dict] = []
    for entry in raw or []:
        if isinstance(entry, str) and entry.strip():
            out.append({"id": entry.strip(), "label": entry.strip()})
        elif isinstance(entry, dict) and entry.get("id"):
            out.append({"id": str(entry["id"]), "label": str(entry.get("label") or entry["id"])})
    return out


def _merge(*lists: list[dict]) -> list[dict]:
    """Concatenate model lists, keeping the first occurrence of each id."""
    seen: set[str] = set()
    merged: list[dict] = []
    for models in lists:
        for model in models:
            if model["id"] not in seen:
                seen.add(model["id"])
                merged.append(model)
    return merged


def _custom_ids(doc: dict) -> list[str]:
    """Ids of custom servers in the document."""
    return [k for k in doc["engines"] if k.startswith(CUSTOM_PREFIX)]


def build_engine(settings: Settings, engine_id: str, doc: dict,
                 transport: httpx.BaseTransport | None = None) -> Engine | None:
    """Construct the engine for an id, or None when the id is unknown."""
    conf = doc["engines"].get(engine_id, {})
    extra = _model_dicts(conf.get("models", []))
    key, _ = resolve_key(settings, engine_id)
    if engine_id in PRESETS:
        preset = PRESETS[engine_id]
        return OpenAICompatEngine(
            id=engine_id, label=preset["label"], kind=preset["kind"],
            base_url=effective_base_url(engine_id, conf) or preset["base_url"], api_key=key,
            key_required=preset["key_required"],
            models=_merge(_model_dicts(_CURATED.get(engine_id, [])), extra),
            live_models=preset["kind"] == "local", transport=transport)
    if engine_id == "anthropic":
        return AnthropicEngine(api_key=key, models=_merge(_model_dicts(ANTHROPIC_MODELS), extra),
                               transport=transport)
    if engine_id == "claude_code":
        return ClaudeCodeEngine(settings, enabled=conf.get("enabled"))
    if engine_id == "antigravity":
        return AntigravityEngine(settings, enabled=conf.get("enabled"),
                                 models=_merge(_model_dicts(AGY_MODELS), extra))
    if engine_id == "codex_cli":
        return CodexCliEngine(settings, enabled=conf.get("enabled"),
                              models=_merge(_model_dicts(CODEX_MODELS), extra))
    custom_url = effective_base_url(engine_id, conf)
    if engine_id in doc["engines"] and engine_id.startswith(CUSTOM_PREFIX) and custom_url:
        return OpenAICompatEngine(
            id=engine_id, label=str(conf.get("label") or engine_id[len(CUSTOM_PREFIX):]),
            kind="custom", base_url=custom_url, api_key=key, key_required=False,
            models=extra, live_models=not extra, transport=transport)
    return None


def _all_ids(doc: dict) -> list[str]:
    """Every engine id in display order: the built-in ones, then custom servers."""
    return [*ENGINE_ORDER, *_custom_ids(doc)]


def _describe(settings: Settings, engine_id: str, engine: Engine, doc: dict) -> dict:
    """The /engines row for one engine (no secret in it)."""
    conf = doc["engines"].get(engine_id, {})
    disabled = conf.get("enabled") is False and engine_id not in CLI_ENGINES
    ok, reason = (False, "Switched off") if disabled else engine.available()
    models = engine.models() if ok or engine.kind != "local" else []
    ids = {m["id"] for m in models}
    if offers_auto(engine_id) and set(PAIRS[engine_id]) <= ids:
        # Last, so it is never the default model.
        models = [*models, {"id": AUTO, "label": "Automatic (cheaper model for simple questions)"}]
    _, source = resolve_key(settings, engine_id)
    return {
        "id": engine_id, "label": engine.label, "kind": engine.kind, "available": bool(ok),
        "reason": None if ok else reason, "models": models,
        "default_model": conf.get("default_model") or (models[0]["id"] if models else ""),
        "enabled": not disabled if engine_id not in CLI_ENGINES else bool(
            getattr(engine, "enabled", False)),
        "needs_key": engine_id in ("openrouter", "anthropic", "openai", "gemini"),
        "has_key": source is not None, "key_source": source,
        "base_url": effective_base_url(engine_id, conf),
        "custom": engine_id.startswith(CUSTOM_PREFIX),
    }


def list_engines(settings: Settings, session: Session | None = None,
                 transport: httpx.BaseTransport | None = None) -> list[dict]:
    """Every engine with its availability, models and default model; exactly one has is_default."""
    doc = load_doc(session)
    rows: list[dict] = []
    for engine_id in _all_ids(doc):
        engine = build_engine(settings, engine_id, doc, transport)
        if engine is not None:
            rows.append(_describe(settings, engine_id, engine, doc))
    chosen = settings.assist_default_engine
    default = next((r["id"] for r in rows if r["id"] == chosen and r["available"]), None) or next(
        (r["id"] for r in rows if r["available"]), None)
    for row in rows:
        row["is_default"] = row["id"] == default
        wanted = settings.assist_default_model
        if row["is_default"] and wanted:
            if wanted not in {m["id"] for m in row["models"]}:
                row["models"] = [*row["models"], {"id": wanted, "label": wanted}]
            row["default_model"] = wanted
    return rows


def get_engine(settings: Settings, engine_id: str, session: Session | None = None,
               transport: httpx.BaseTransport | None = None) -> Engine | None:
    """The engine object for an id (even when unavailable), or None for an unknown id."""
    return build_engine(settings, engine_id, load_doc(session), transport)


class ConfigError(ValueError):
    """A configuration request that cannot be applied; the message is safe to show."""


class ForbiddenSetting(ConfigError):
    """A well-formed request for a setting this engine never allows (the API answers 422)."""


def configure_engine(settings: Settings, session: Session, engine_id: str, *,
                     enabled: bool | None = None, api_key: str | None = None,
                     base_url: str | None = None, models: list | None = None,
                     label: str | None = None, default_model: str | None = None,
                     transport: httpx.BaseTransport | None = None) -> dict:
    """Apply a configuration change and return the engine's new /engines row.

    `api_key` goes to the keyring only (an empty string removes the stored key). An unknown id
    that starts with "custom-" and comes with a base_url creates a custom server entry.
    """
    doc = load_doc(session)
    known = engine_id in ENGINE_ORDER or engine_id in doc["engines"]
    if not known and not (engine_id.startswith(CUSTOM_PREFIX) and base_url):
        raise ConfigError(f"Unknown engine: {engine_id}")
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", engine_id):
        raise ConfigError("Engine ids use lowercase letters, digits, dashes and underscores.")
    if base_url is not None and not address_is_editable(engine_id):
        raise ForbiddenSetting(
            f"The address of {engine_id} is fixed and cannot be changed. Only local servers and "
            "custom servers have an address you can set.")
    if base_url is not None and not valid_base_url(base_url):
        raise ConfigError("The address must start with http:// or https:// and name a host")
    conf = dict(doc["engines"].get(engine_id, {}))
    if base_url is not None and base_url != conf.get("base_url") and api_key is None:
        # A stored key was given for the old address; it must not follow the engine to a new one.
        secrets_store.delete_secret(engine_id)
    for name, value in (("enabled", enabled), ("base_url", base_url), ("label", label),
                        ("default_model", default_model)):
        if value is not None:
            conf[name] = value
    if models is not None:
        conf["models"] = _model_dicts(models)
    if api_key is not None:
        if api_key.strip():
            secrets_store.set_secret(engine_id, api_key.strip())
        else:
            secrets_store.delete_secret(engine_id)
    new_doc = {**doc, "engines": {**doc["engines"], engine_id: conf}}
    _save_doc(session, new_doc)
    clear_probe_cache()
    row = next((r for r in list_engines(settings, session, transport) if r["id"] == engine_id),
               None)
    if row is None:
        raise ConfigError(f"Engine {engine_id} is not usable yet: give it an address.")
    return row


def remove_custom(session: Session, engine_id: str) -> bool:
    """Delete a custom server entry and its stored key; False when it does not exist."""
    doc = load_doc(session)
    if not engine_id.startswith(CUSTOM_PREFIX) or engine_id not in doc["engines"]:
        return False
    secrets_store.delete_secret(engine_id)
    remaining = {k: v for k, v in doc["engines"].items() if k != engine_id}
    _save_doc(session, {**doc, "engines": remaining})
    return True
