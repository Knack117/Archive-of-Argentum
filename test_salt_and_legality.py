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


def test_extract_salt_score_from_label_text():
    validator = DeckValidator()
    card_data = {
        "name": "Stasis",
        "label": "Salt Score: 3.06\n14259 decks",
    }

    salt_score = validator._extract_salt_score_from_card(card_data)
    assert salt_score == pytest.approx(3.06)


@pytest.mark.asyncio
async def test_legality_allows_99_cards_plus_commander():
    validator = DeckValidator()
    cards = [DeckCard(name=f"Card {i}") for i in range(99)]

    result = await validator._validate_legality(cards, commander="Commander One")
    assert result["is_legal"], result["issues"]


def test_duplicate_detection_counts_quantities():
    validator = DeckValidator()
    cards = [DeckCard(name="Sol Ring", quantity=2)]

    assert validator._check_duplicates(cards)
    assert validator._find_illegal_duplicates(cards) == {"Sol Ring": 2}


def test_duplicate_detection_allows_basic_lands():
    validator = DeckValidator()
    cards = [DeckCard(name="Forest", quantity=12), DeckCard(name="Mountain", quantity=5)]

    assert not validator._check_duplicates(cards)
    assert validator._find_illegal_duplicates(cards) == {}


@pytest.mark.asyncio
async def test_legality_blocks_non_basic_duplicates():
    validator = DeckValidator()
    cards = [DeckCard(name="Sol Ring", quantity=2)]

    result = await validator._validate_legality(cards, commander=None)
    assert not result["is_legal"]
    assert "Sol Ring" in result["illegal_duplicates"]


@pytest.mark.asyncio
async def test_legality_allows_basic_land_duplicates_only():
    validator = DeckValidator()
    cards = [DeckCard(name="Forest", quantity=20), DeckCard(name="Plains", quantity=10)]

    result = await validator._validate_legality(cards, commander=None)
    assert result["is_legal"]
    assert result["illegal_duplicates"] == {}


@pytest.mark.asyncio
async def test_legality_allows_commander_list_included():
    validator = DeckValidator()
    cards = [DeckCard(name=f"Card {i}") for i in range(99)]
    cards.append(DeckCard(name="Commander One"))

    result = await validator._validate_legality(cards, commander="Commander One")
    assert result["is_legal"], result["issues"]
