"""The same-site dependency: a browser request marked cross-site is refused; others pass."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from spyglass_service.radar.api.same_site import refuse_cross_site


def make_client() -> TestClient:
    """A tiny app with one guarded read endpoint."""
    app = FastAPI()

    @app.get("/thing", dependencies=[Depends(refuse_cross_site)])
    def thing() -> dict:
        """A side-effecting read, standing in for the reader and PDF endpoints."""
        return {"ok": True}

    return TestClient(app)


def test_cross_site_requests_are_refused() -> None:
    response = make_client().get("/thing", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403 and "cross-site" in response.json()["detail"]


def test_the_header_value_is_compared_case_insensitively() -> None:
    assert make_client().get("/thing", headers={"Sec-Fetch-Site": "Cross-Site"}).status_code == 403


@pytest.mark.parametrize("value", ["same-origin", "same-site", "none"])
def test_same_origin_same_site_and_typed_in_requests_pass(value: str) -> None:
    assert make_client().get("/thing", headers={"Sec-Fetch-Site": value}).status_code == 200


def test_a_request_without_the_header_passes_for_scripts_and_tools() -> None:
    assert make_client().get("/thing").status_code == 200
