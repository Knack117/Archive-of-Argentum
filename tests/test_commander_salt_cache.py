"""Tests for commander salt normalization and fallback logic."""
import json
from pathlib import Path

import pytest

from aoa.routes import deck_validation
from aoa.services.salt_cache import SaltCacheService


def _write_cache(tmp_path, cards):
    cache_file = tmp_path / "salt_cache.json"
    payload = {
        "cached_at": "2024-01-01T00:00:00",
        "card_count": len(cards),
        "cards": cards,
    }
    cache_file.write_text(json.dumps(payload))
    return cache_file


def test_normalize_card_name_handles_partner_and_punctuation():
    """Commander names should normalize by removing punctuation and partner syntax."""
    assert SaltCacheService.normalize_card_name("Urza, Lord High Artificer") == "urza lord high artificer"
    assert SaltCacheService.normalize_card_name(
        "Slicer, Hired Muscle // Slicer, High-Speed Antagonist"
    ) == "slicer hired muscle slicer high speed antagonist"


def test_variant_lookup_handles_partner_commander(tmp_path):
    """Variant lookup must match common partner/transform commander names."""
    cache_file = _write_cache(
        tmp_path,
        {
            "Slicer, Hired Muscle": 0.96,
            "Narset, Enlightened Exile": 1.95,
        },
    )

    service = SaltCacheService(cache_file=str(cache_file))

    assert service.get_card_salt_with_variants(
        "Slicer, Hired Muscle // Slicer, High-Speed Antagonist"
    ) == pytest.approx(0.96)
    assert service.get_card_salt("Narset, Enlightened Exile") == pytest.approx(1.95)


class _DummySaltCache:
    async def ensure_loaded(self):
        return None

    def get_card_salt_with_variants(self, _name: str) -> float:
        return 0.0

    def get_card_salt(self, _name: str) -> float:
        return 0.0


@pytest.mark.asyncio
async def test_commander_salt_uses_deck_average_fallback(monkeypatch):
    """When the cache misses, fall back to the deck's average salt score."""
    validator = deck_validation.DeckValidator()

    dummy_cache = _DummySaltCache()
    monkeypatch.setattr(deck_validation, "get_salt_cache", lambda: dummy_cache)

    class _DummyResponse:
        status_code = 404
        text = ""

    class _DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return _DummyResponse()

    monkeypatch.setattr(deck_validation.httpx, "AsyncClient", _DummyClient)

    result = await validator._get_commander_salt_score("Imaginary Commander", fallback_average=1.23)
    assert result == pytest.approx(1.23, rel=0, abs=0.01)
