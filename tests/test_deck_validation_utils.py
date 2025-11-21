from aoa.models import DeckCard
from aoa.routes.deck_validation import DeckValidator, check_early_game_combos_in_cards


def test_normalize_card_name_strips_export_suffixes():
    validator = DeckValidator()

    assert validator._normalize_card_name("Lightning Bolt (2ED) 123") == "Lightning Bolt"
    assert validator._normalize_card_name("Counterspell [MMQ] #12") == "Counterspell"
    assert validator._normalize_card_name("Ponder #7") == "Ponder"


def test_duplicate_detection_ignores_unlimited_cards():
    validator = DeckValidator()
    cards = [
        DeckCard(name="Island", quantity=15),
        DeckCard(name="Sol Ring", quantity=2),
    ]

    duplicates = validator._find_illegal_duplicates(cards)

    assert "Island" not in duplicates
    assert duplicates == {"Sol Ring": 2}


def test_early_game_combo_detection_requires_complete_pair():
    card_pool = [
        "Thassa's Oracle",
        "Laboratory Maniac",
        "Demonic Consultation",
        "Swift Reconfiguration",
        "Devoted Druid",
    ]

    combos_found = check_early_game_combos_in_cards(card_pool)
    combo_cards = {tuple(combo["cards"]) for combo in combos_found}

    expected = {
        ("Demonic Consultation", "Thassa's Oracle"),
        ("Demonic Consultation", "Laboratory Maniac"),
        ("Devoted Druid", "Swift Reconfiguration"),
    }

    assert combo_cards == expected
