import pytest

from app import DeckCard, DeckValidator


def test_extract_salt_scores_from_json_structure():
    validator = DeckValidator()
    sample_json = {
        "props": {
            "pageProps": {
                "data": {
                    "container": {
                        "json_dict": {
                            "cardlists": [
                                {
                                    "header": "Top Salt Cards",
                                    "cardviews": [
                                        {"name": "Stasis", "salt": 3.06},
                                        {"name": "Rhystic Study", "salt": 2.73},
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        }
    }

    salt_scores = validator._extract_salt_scores_from_json(sample_json)
    assert salt_scores["Stasis"] == pytest.approx(3.06)
    assert salt_scores["Rhystic Study"] == pytest.approx(2.73)
    assert len(salt_scores) == 2


@pytest.mark.asyncio
async def test_legality_allows_99_cards_plus_commander():
    validator = DeckValidator()
    cards = [DeckCard(name=f"Card {i}") for i in range(99)]

    result = await validator._validate_legality(cards, commander="Commander One")
    assert result["is_legal"], result["issues"]


@pytest.mark.asyncio
async def test_legality_allows_commander_list_included():
    validator = DeckValidator()
    cards = [DeckCard(name=f"Card {i}") for i in range(99)]
    cards.append(DeckCard(name="Commander One"))

    result = await validator._validate_legality(cards, commander="Commander One")
    assert result["is_legal"], result["issues"]
