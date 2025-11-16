import pytest
from pydantic import ValidationError

from app import DeckValidationRequest, DeckValidator


def test_decklist_text_block_is_parsed():
    request = DeckValidationRequest(
        decklist_text="2x Plains\r\n1x Sol Ring\n;1x Swords to Plowshares",
        commander="Light-Paws, Emperor's Voice",
    )

    validator = DeckValidator()
    entries = validator._resolve_decklist_entries(request)

    assert entries == [
        "2x Plains",
        "1x Sol Ring",
        "1x Swords to Plowshares",
    ]


def test_decklist_chunks_are_combined():
    request = DeckValidationRequest(
        decklist_chunks=[
            "1x Sol Ring\n1x Plains",
            "1x Island\n1x Swords to Plowshares",
        ],
        target_bracket="optimized",
    )

    validator = DeckValidator()
    entries = validator._resolve_decklist_entries(request)

    assert len(entries) == 4
    assert entries[0] == "1x Sol Ring"
    assert entries[-1] == "1x Swords to Plowshares"


def test_missing_decklist_inputs_raise_error():
    with pytest.raises(ValidationError):
        DeckValidationRequest()
