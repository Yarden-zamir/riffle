"""Contract: the media route serves only GIFs that a card of the asking owner lists. It is no open proxy."""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from riffle import store
from riffle.api import create_app
from riffle.models import ChangeInput, SourceCreate, utc_now


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("RIFFLE_DB", str(tmp_path / "riffle.duckdb"))
    monkeypatch.setenv("RIFFLE_AUTO_REFRESH", "false")
    monkeypatch.setenv("RIFFLE_SEED_DEFAULT_SOURCES", "false")
    monkeypatch.setenv("RIFFLE_AUTH_ENABLED", "false")
    with TestClient(create_app()) as client:
        yield client


def owner_headers(client: TestClient) -> dict[str, str]:
    headers = {"X-Anonymous-Token": str(uuid4())}
    return {**headers, "X-Riffle-Owner": client.get("/me", headers=headers).json()["id"]}


def card_with_media(owner: str) -> int:
    source = store.add_source(SourceCreate(name="Releases", config={"profile": "dev", "url": "https://example.com/feed.xml"}), owner_id=owner)
    store.upsert_changes(source.id, [ChangeInput(
        external_id="one", title="Release", url="https://example.com/r", summary="", content="", published_at=utc_now(),
        metadata={"media": [{"url": "https://example.com/a.png", "kind": "image"}, {"url": "https://example.com/b.gif", "kind": "gif"}]},
    )], owner_id=owner)
    return store.list_changes(owner_id=owner)[0].id


def test_media_route_serves_only_listed_gifs_of_the_owner(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fetched: list[str] = []

    class Fetcher:
        def get(self, url: str, *, max_bytes: int):
            import httpx
            fetched.append(url)
            return httpx.Response(200, headers={"content-type": "image/gif"}, content=b"GIF89a")

    monkeypatch.setattr("riffle.api.PublicFetcher", Fetcher)
    owner = owner_headers(api_client)
    change_id = card_with_media(owner["X-Riffle-Owner"])

    gif = api_client.get(f"/changes/{change_id}/media/1", headers=owner)
    assert gif.status_code == 200 and gif.content == b"GIF89a" and gif.headers["content-type"] == "image/gif"
    assert api_client.get(f"/changes/{change_id}/media/0", headers=owner).status_code == 404, "only GIFs pass"
    assert api_client.get(f"/changes/{change_id}/media/2", headers=owner).status_code == 404
    assert api_client.get(f"/changes/{change_id}/media/1", headers=owner_headers(api_client)).status_code == 404, "another owner"
    assert fetched == ["https://example.com/b.gif"]
