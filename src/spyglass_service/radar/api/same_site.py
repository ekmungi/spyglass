"""A dependency that refuses browser requests marked as coming from another site.

`CrossSiteGuard` only looks at requests that change something. A few reads here are not free:
opening a reader document builds it (a network fetch plus a database write), and the PDF
endpoint downloads up to 40 MB. A page on another site could trigger either with an `<img>` tag.
Browsers describe where a request came from in the `Sec-Fetch-Site` header, which a page cannot
change, so these endpoints refuse `cross-site`. A request with no such header (a script, the
Obsidian plugin, an older browser) passes, as `CrossSiteGuard` also lets header-less clients through.

Attach it per route: `@router.get("/x", dependencies=[Depends(refuse_cross_site)])`.
"""

from fastapi import HTTPException, Request

REFUSAL = "cross-site request refused"


def refuse_cross_site(request: Request) -> None:
    """Raise 403 when the browser says the request was started by a page on another site."""
    if request.headers.get("sec-fetch-site", "").strip().lower() == "cross-site":
        raise HTTPException(status_code=403, detail=REFUSAL)
