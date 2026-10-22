"""The public demo of the web UI over mock data (canopy.serve.demo, D122): its host names, and mock data only."""

from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from canopy.serve import demo, options
from canopy.serve.options import ServeOptions

DEMO = "canopy-git-main-acme.vercel.app"
VERCEL = {
    "VERCEL_URL": "canopy-a1b2c3-acme.vercel.app",
    "VERCEL_BRANCH_URL": DEMO,
    "VERCEL_PROJECT_PRODUCTION_URL": "canopy.example.com",
}


@pytest.fixture
def browser(tmp_path: Path) -> TestClient:
    """A visitor to the demo at DEMO, with Vercel's variables set."""
    ui = tmp_path / "dist"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><html><head></head><body></body></html>")
    with (
        mock.patch.object(demo, "ui_dir", autospec=True, return_value=ui),
        mock.patch.object(options, "STREAM_SECONDS", 0.2),
    ):
        app = demo.create(VERCEL, tmp_path / "demo")
    return TestClient(app, base_url=f"https://{DEMO}")


def test_the_demo_signs_every_visitor_in_and_takes_their_writes(browser: TestClient) -> None:
    assert browser.get("/tickets/ABC-102").status_code == 200
    assert browser.get("/api/session").json() == {"signed_in": True, "token": "open"}
    assert browser.get("/api/meta").json()["mock"] is True
    reply = {"body": "Looks good.", "submission": "abcdefgh"}
    response = browser.post("/api/tickets/ABC-102/replies", json=reply, headers={"origin": f"https://{DEMO}"})
    assert response.is_success, response.text


def test_the_demo_ends_each_event_stream_on_its_own(browser: TestClient) -> None:
    # TestClient reads a stream to its end, so an endless one would hang here.
    response = browser.get("/api/events")
    assert response.status_code == 200
    assert "runs.updated" in response.text
    assert response.text.rstrip().endswith('data: {"type":"stream.ending"}')


def test_the_demo_refuses_a_host_or_origin_vercel_did_not_name(browser: TestClient) -> None:
    assert browser.get("/api/meta", headers={"host": "evil.example"}).status_code == 403
    assert browser.get("/api/meta", headers={"origin": "https://evil.example"}).status_code == 403
    assert browser.get("/api/meta", headers={"host": "canopy.example.com"}).status_code == 200


def test_public_hosts_come_from_vercel_and_canopy_demo_hosts() -> None:
    extra = {"CANOPY_DEMO_HOSTS": " Demo.Example.org/, https://other.example ,"}
    assert demo.public_hosts({**VERCEL, **extra}) == {
        "canopy-a1b2c3-acme.vercel.app",
        DEMO,
        "canopy.example.com",
        "demo.example.org",
        "other.example",
    }
    assert demo.public_hosts({}) == frozenset()


def test_only_mock_data_is_served_under_a_public_name() -> None:
    with pytest.raises(ValidationError, match="only mock data"):
        ServeOptions(public_hosts=frozenset({DEMO}))
    with pytest.raises(ValidationError, match="host name"):
        ServeOptions(mock=True, public_hosts=frozenset({f"{DEMO}:443"}))
    assert DEMO in ServeOptions(mock=True, public_hosts=frozenset({DEMO})).hosts
