"""GET /img?u=<address>: an article image fetched by the service (see radar/media_proxy.py).

Refused requests (an address in no reader document, not an image, SVG, too large, private,
failed) get a 1x1 transparent image so page layouts do not break. A request a browser marks as
coming from another site is refused with 403.
"""

from fastapi import APIRouter, Depends, Query, Request, Response

from spyglass_service.radar import media_proxy
from spyglass_service.radar.api.same_site import refuse_cross_site

router = APIRouter()

_SERVED_HEADERS = {"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"}
_REFUSED_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


@router.get("/img", dependencies=[Depends(refuse_cross_site)])
def image(request: Request,
          u: str = Query(..., min_length=1, max_length=media_proxy.MAX_URL_CHARS)) -> Response:
    """Serve the image at `u` when it may be served; the transparent stand-in otherwise."""
    state = request.app.state
    got = media_proxy.serve(state.engine, state.settings.data_dir, u)
    if got is None:
        return Response(media_proxy.PIXEL, media_type="image/gif", headers=_REFUSED_HEADERS)
    body, kind = got
    return Response(body, media_type=kind, headers=_SERVED_HEADERS)
