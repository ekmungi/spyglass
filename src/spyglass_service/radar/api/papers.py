"""Paper search endpoint: type a topic, get the few papers that matter."""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from spyglass_service.radar.papers.search import find_papers

logger = logging.getLogger(__name__)

router = APIRouter()


class PaperSearch(BaseModel):
    """Body of POST /papers/search."""

    topic: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=8, ge=1, le=20)


@router.post("/papers/search")
async def search_papers(body: PaperSearch, request: Request) -> dict:
    """Find papers for a topic: `{papers, status: ok|degraded|empty, notice}`, a line on each paper's relevance."""
    state = request.app.state
    try:
        index = state.service_state.ensure_index()
    except Exception:
        logger.exception("Embedding index unavailable; searching without local papers")
        index = None
    try:
        result = await run_in_threadpool(
            find_papers, state.engine, state.settings, index, body.topic.strip(), body.limit
        )
    except Exception as exc:
        logger.exception("Paper search failed")
        raise HTTPException(status_code=502, detail="Paper search failed; try again later") from exc
    return result
