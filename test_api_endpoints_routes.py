"""Integration-style tests for the FastAPI routes and scraping helpers."""
from __future__ import annotations

import json
from typing import Dict, List

import pytest
from fastapi.testclient import TestClient

from app import app
from aoa.models import ComboResult, PageTheme, ThemeCollection, ThemeContainer, ThemeItem
from aoa.routes.themes import fetch_theme_tag
from aoa.services.commanders import scrape_edhrec_commander_page

API_HEADERS = {"Authorization": "Bearer test-key"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def commander_payload() -> Dict[str, object]:
    return {
        "commander_name": "The Ur-Dragon",
        "commander_url": "https://edhrec.com/commanders/the-ur-dragon",
        "timestamp": "2024-01-01T00:00:00Z",
        "commander_tags": ["dragons"],
        "top_10_tags": ["dragons"],
        "all_tags": [{"tag": "dragons", "count": 100, "url": "/tags/dragons"}],
        "combos": [{"name": "Infinite Dragons", "url": "https://combo.example"}],
        "similar_commanders": [
            {"name": "Scion of the Ur-Dragon", "url": "https://example.com/scion"}
        ],
        "categories": {
            "Ramp": {
                "cards": [
                    {
                        "name": "Sol Ring",
                        "num_decks": 100,
                        "potential_decks": 200,
                        "inclusion_percentage": "50%",
                        "synergy_percentage": "10%",
                        "sanitized_name": "sol-ring",
                        "card_url": "https://example.com/sol-ring",
                    }
                ]
            }
        },
    }


def test_system_endpoints(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["success"] is True

    status = client.get("/api/v1/status")
    assert status.status_code == 200
    assert status.json()["status"] == "online"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"


def test_card_routes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sample_card = {
        "id": "sample-123",
        "name": "Lightning Bolt",
        "mana_cost": "{R}",
        "cmc": 1,
        "type_line": "Instant",
        "oracle_text": "Lightning Bolt deals 3 damage to any target.",
        "colors": ["R"],
        "color_identity": ["R"],
        "keywords": [],
        "legalities": {"commander": "legal"},
        "games": ["paper"],
        "reserved": False,
        "foil": True,
        "nonfoil": True,
        "oversized": False,
        "promo": False,
        "reprint": True,
        "variation": False,
        "set_id": "sample-set",
        "set": "SMP",
        "set_name": "Sample Set",
        "set_type": "core",
        "set_uri": "https://example.com/set",
        "set_search_uri": "https://example.com/set/search",
        "rulings_uri": "https://example.com/set/rulings",
        "prints_search_uri": "https://example.com/set/prints",
        "collector_number": "150",
        "digital": False,
        "rarity": "common",
        "artist": "John Doe",
        "artist_ids": ["artist-1"],
        "illustration_id": "illus-1",
        "border_color": "black",
        "frame": "1993",
        "full_art": False,
        "textless": False,
        "booster": True,
        "story_spotlight": False,
        "edhrec_rank": 1,
        "penny_rank": 1,
        "prices": {"usd": 1.0},
        "related_uris": {"edhrec": "https://edhrec.com/cards/lightning-bolt"},
    }

    class DummyResponse:
        def __init__(self, data: Dict[str, Any]) -> None:
            self.status_code = 200
            self._data = data

        def raise_for_status(self) -> None:  # pragma: no cover - behaviourally empty
            return None

        def json(self) -> Dict[str, Any]:  # pragma: no cover - deterministic
            return self._data

    class DummyClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self) -> "DummyClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, params=None) -> DummyResponse:
            if "cards/search" in url:
                return DummyResponse({"data": [sample_card]})
            return DummyResponse(sample_card)

    monkeypatch.setattr("aoa.routes.cards.httpx.AsyncClient", DummyClient)

    search = client.post(
        "/api/v1/cards/search",
        headers=API_HEADERS,
        json={"query": "Lightning"},
    )
    assert search.status_code == 200
    assert search.json()["total_cards"] >= 1

    autocomplete = client.get(
        "/api/v1/cards/autocomplete",
        headers=API_HEADERS,
        params={"q": "light"},
    )
    assert autocomplete.status_code == 200
    assert "Lightning" in " ".join(autocomplete.json()["data"])

    card = client.get("/api/v1/cards/mock1", headers=API_HEADERS)
    assert card.status_code == 200
    assert card.json()["name"] == "Lightning Bolt"




def test_commander_summary_endpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, commander_payload: Dict[str, object]
) -> None:
    async def fake_scrape(_: str) -> Dict[str, object]:  # pragma: no cover - used via patch
        return commander_payload

    monkeypatch.setattr(
        "aoa.routes.commanders.scrape_edhrec_commander_page",
        fake_scrape,
    )

    response = client.get(
        "/api/v1/commander/summary",
        headers=API_HEADERS,
        params={"name": "The Ur-Dragon"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["commander_name"] == "The Ur-Dragon"
    assert payload["categories"]["Ramp"][0]["name"] == "Sol Ring"


def test_average_deck_endpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, commander_payload: Dict[str, object]
) -> None:
    async def fake_scrape(_: str) -> Dict[str, object]:
        return commander_payload

    monkeypatch.setattr(
        "aoa.routes.commanders.scrape_edhrec_commander_page",
        fake_scrape,
    )

    response = client.get(
        "/api/v1/average_deck/summary",
        headers=API_HEADERS,
        params={"commander_slug": "the-ur-dragon", "bracket": "core"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["similar_commanders"][0]["name"] == "Scion of the Ur-Dragon"


def test_combo_endpoints(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample_combo = ComboResult(
        combo_id="123",
        combo_name="Sample Combo",
        color_identity=["R"],
        cards_in_combo=["Card A", "Card B"],
        results_in_combo=["Win"],
        decks_edhrec=120,
        variants=1,
        combo_url="https://commanderspellbook.com/combo/123",
        price_info={"usd": "3.00"},
    )

    async def fake_fetch(_: str, search_type: str = "commander") -> List[ComboResult]:
        return [sample_combo]

    monkeypatch.setattr("aoa.routes.combos.fetch_commander_combos", fake_fetch)

    commander_resp = client.get(
        "/api/v1/combos/commander/ur-dragon",
        headers=API_HEADERS,
    )
    assert commander_resp.status_code == 200
    assert commander_resp.json()["total_results"] == 1

    search_resp = client.get(
        "/api/v1/combos/search",
        headers=API_HEADERS,
        params={"card_name": "Sol Ring"},
    )
    assert search_resp.status_code == 200
    assert search_resp.json()["results"][0]["combo_id"] == "123"


def test_theme_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sample_theme = PageTheme(
        header="Dragons",
        description="Dragon tribal", 
        tags=["dragons"],
        container=ThemeContainer(
            collections=[
                ThemeCollection(
                    header="Top Cards",
                    items=[
                        ThemeItem(
                            card_name="Sol Ring",
                            inclusion_percentage="60%",
                            synergy_percentage="10%",
                        )
                    ],
                )
            ]
        ),
        source_url="https://edhrec.com/tags/dragons",
    )

    async def fake_fetch(theme_slug: str, color_identity: str | None = None) -> PageTheme:
        assert theme_slug == "dragons"
        assert color_identity is None
        return sample_theme

    monkeypatch.setattr("aoa.routes.themes.fetch_theme_tag", fake_fetch)

    response = client.get("/api/v1/themes/dragons", headers=API_HEADERS)
    assert response.status_code == 200
    assert response.json()["container"]["collections"][0]["items"][0]["card_name"] == "Sol Ring"


def test_available_tags_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "pageProps": {
            "data": {
                "container": {
                    "json_dict": {
                        "cardlists": [
                            {
                                "cardviews": [
                                    {"url": "/tags/dragons"},
                                    {"url": "/tags/spellslinger"},
                                ]
                            }
                        ]
                    }
                }
            }
        }
    }

    async def fake_fetch(_: str) -> Dict[str, object]:  # pragma: no cover - behaviourally simple
        return payload

    monkeypatch.setattr("aoa.routes.themes.fetch_edhrec_json", fake_fetch)

    response = client.get("/api/v1/tags/available", headers=API_HEADERS)
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2


def test_deck_validation_endpoints(client: TestClient) -> None:
    payload = {
        "decklist": ["1x Sol Ring", "1x Lightning Bolt", "1x Island"],
        "commander": "Jace, Wielder of Mysteries",
        "target_bracket": "core",
        "validate_bracket": True,
        "validate_legality": True,
    }

    response = client.post("/api/v1/deck/validate", headers=API_HEADERS, json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True

    sample = client.get("/api/v1/deck/validate/sample", headers=API_HEADERS)
    assert sample.status_code == 200
    assert sample.json()["validation_result"]["success"] is True

    brackets = client.get("/api/v1/brackets/info", headers=API_HEADERS)
    assert brackets.status_code == 200
    assert "core" in brackets.json()["brackets"]

    game_changers = client.get("/api/v1/brackets/game-changers/list", headers=API_HEADERS)
    assert game_changers.status_code == 200
    assert "current_game_changers" in game_changers.json()


@pytest.mark.asyncio
async def test_scrape_commander_page_bypasses_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "pageProps": {
            "data": {
                "panels": {
                    "taglinks": [{"tag": "dragons", "count": 10, "url": "/tags/dragons"}],
                    "combos": [{"name": "Combo", "url": "https://combo", "cards": [{"name": "Card"}]}],
                    "similarCommanders": [{"name": "Scion", "url": "https://example.com"}],
                    "jsonCardLists": [
                        {
                            "header": "Ramp",
                            "cards": [
                                {
                                    "name": "Sol Ring",
                                    "num_decks": 100,
                                    "potential_decks": 200,
                                    "inclusion_percentage": "50%",
                                    "synergy_percentage": "10%",
                                    "sanitized_name": "sol-ring",
                                    "card_url": "https://example.com/sol-ring",
                                }
                            ],
                        }
                    ],
                }
            }
        }
    }

    created_clients: List[Dict[str, object]] = []

    class DummyResponse:
        def __init__(self) -> None:
            self.status_code = 200

        def raise_for_status(self) -> None:  # pragma: no cover - simple passthrough
            return None

        def json(self) -> Dict[str, object]:  # pragma: no cover - deterministic
            return payload

    class DummyClient:
        def __init__(self, *_, **kwargs) -> None:
            created_clients.append(kwargs)

        async def __aenter__(self) -> "DummyClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, *_args, **_kwargs) -> DummyResponse:
            return DummyResponse()

    monkeypatch.setattr("aoa.services.edhrec.httpx.AsyncClient", DummyClient)

    data = await scrape_edhrec_commander_page("https://edhrec.com/commanders/test")
    assert created_clients and created_clients[0].get("trust_env") is False
    assert data["categories"]["Ramp"]["cards"][0]["name"] == "Sol Ring"


@pytest.mark.asyncio
async def test_fetch_theme_tag_bypasses_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "pageProps": {
            "data": {
                "header": "Dragons",
                "description": "Dragon theme",
                "container": {
                    "json_dict": {
                        "cardlists": [
                            {
                                "header": "Top Cards",
                                "cardviews": [
                                    {
                                        "cardname": "Sol Ring",
                                        "popularity": "60%",
                                        "synergy": "10%",
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        }
    }

    created_clients: List[Dict[str, object]] = []

    class DummyResponse:
        def __init__(self) -> None:
            self.status_code = 200

        def raise_for_status(self) -> None:  # pragma: no cover - simple passthrough
            return None

        def json(self) -> Dict[str, object]:  # pragma: no cover - deterministic
            return payload

    class DummyClient:
        def __init__(self, *_, **kwargs) -> None:
            created_clients.append(kwargs)

        async def __aenter__(self) -> "DummyClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, headers=None) -> DummyResponse:
            return DummyResponse()

    monkeypatch.setattr("aoa.services.edhrec.httpx.AsyncClient", DummyClient)

    page = await fetch_theme_tag("dragons")
    assert created_clients and created_clients[0].get("trust_env") is False
    assert page.container.collections[0].items[0].card_name == "Sol Ring"
