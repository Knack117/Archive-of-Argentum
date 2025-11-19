import pytest
from types import SimpleNamespace

from aoa.models import DeckCard, DeckValidationRequest
from aoa.routes.deck_validation import DeckValidator


class DummySaltCache:
    async def ensure_loaded(self):
        return None

    def calculate_deck_salt(self, card_names):
        return {
            "average_salt": 0.5,
            "salt_tier": "Casual",
            "top_offenders": [],
            "salty_card_count": len(card_names),
        }


def test_convert_parser_cards_detects_commander():
    validator = DeckValidator()
    commander_card = SimpleNamespace(name="Brudiclad, Telchor Engineer", quantity=1, tags={"Commander"})
    island_card = SimpleNamespace(name="Island", quantity=5, tags=None)

    entries, commander = validator._convert_parser_cards([commander_card, island_card])

    assert commander == "Brudiclad, Telchor Engineer"
    assert any(entry == "5 Island" for entry in entries)


@pytest.mark.asyncio
async def test_validate_deck_uses_detected_commander(monkeypatch):
    validator = DeckValidator()

    def fake_resolve(self, request):
        return ["1 Island"], "Brudiclad, Telchor Engineer"

    async def fake_build(self, deck_entries):
        return [DeckCard(name="Island", quantity=1)]

    def fake_duplicates(self, cards):
        return {}

    async def fake_authoritative(self):
        return {}

    async def fake_commander_salt(self, commander_name, fallback_average=None):
        fake_commander_salt.called_with = commander_name
        return 1.23

    fake_commander_salt.called_with = None

    monkeypatch.setattr(DeckValidator, "_resolve_decklist_entries", fake_resolve)
    monkeypatch.setattr(DeckValidator, "_build_deck_cards", fake_build)
    monkeypatch.setattr(DeckValidator, "_find_illegal_duplicates", fake_duplicates)
    monkeypatch.setattr(DeckValidator, "_load_authoritative_data", fake_authoritative)
    monkeypatch.setattr(DeckValidator, "_get_commander_salt_score", fake_commander_salt)

    def fake_get_salt_cache():
        return DummySaltCache()

    monkeypatch.setattr("aoa.routes.deck_validation.get_salt_cache", fake_get_salt_cache)

    request = DeckValidationRequest(
        decklist_url="https://moxfield.com/decks/test",
        validate_bracket=False,
        validate_legality=False,
    )

    response = await validator.validate_deck(request)

    assert fake_commander_salt.called_with == "Brudiclad, Telchor Engineer"
    assert response.deck_summary["commander"] == "Brudiclad, Telchor Engineer"
    assert response.salt_scores["commander_salt_score"] == 1.23
