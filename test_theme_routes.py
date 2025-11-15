import pytest

from app import (
    _build_theme_route_candidates,
    _resolve_theme_card_limit,
    _split_color_prefixed_theme_slug,
    extract_theme_sections_from_json,
    normalize_theme_colors,
)


def test_split_color_prefixed_theme_slug_with_color_prefix():
    color, theme = _split_color_prefixed_theme_slug("temur-spellslinger")
    assert color == "temur"
    assert theme == "spellslinger"


def test_split_color_prefixed_theme_slug_without_color_prefix():
    color, theme = _split_color_prefixed_theme_slug("spellslinger")
    assert color is None
    assert theme is None


def test_build_theme_route_candidates_with_color_prefix():
    candidates = _build_theme_route_candidates("temur-spellslinger")
    assert candidates[0]["page_path"] == "tags/spellslinger/temur"
    assert candidates[0]["json_path"] == "tags/spellslinger/temur.json"
    assert any(candidate["page_path"] == "themes/temur-spellslinger" for candidate in candidates)


def test_build_theme_route_candidates_without_color_prefix():
    candidates = _build_theme_route_candidates("spellslinger")
    assert candidates[0] == {
        "page_path": "tags/spellslinger",
        "json_path": "tags/spellslinger.json",
    }
    assert candidates[1] == {
        "page_path": "themes/spellslinger",
        "json_path": "themes/spellslinger.json",
    }


def test_build_theme_route_candidates_handles_five_color_slug():
    candidates = _build_theme_route_candidates("five-color-gates")
    assert candidates[0]["page_path"] == "tags/gates/five-color"
    assert candidates[0]["json_path"] == "tags/gates/five-color.json"


def test_resolve_theme_card_limit_defaults_and_caps():
    assert _resolve_theme_card_limit(None) == 60
    assert _resolve_theme_card_limit("30") == 30
    assert _resolve_theme_card_limit(500) == 200


def test_resolve_theme_card_limit_zero_disables_limit():
    assert _resolve_theme_card_limit(0) == 0
    assert _resolve_theme_card_limit(-5) == 60


def test_extract_theme_sections_respects_limit():
    payload = {
        "pageProps": {
            "data": {
                "container": {
                    "json_dict": {
                        "cardlists": [
                            {
                                "header": "Instants",
                                "cardviews": [
                                    {
                                        "name": "Lightning Bolt",
                                        "url": "/card/lightning-bolt",
                                        "num_decks": 100,
                                        "potential_decks": 1000,
                                    },
                                    {
                                        "name": "Opt",
                                        "url": "/card/opt",
                                        "num_decks": 80,
                                        "potential_decks": 1000,
                                    },
                                    {
                                        "name": "Brainstorm",
                                        "url": "/card/brainstorm",
                                        "num_decks": 60,
                                        "potential_decks": 1000,
                                    },
                                ],
                            }
                        ]
                    }
                }
            }
        }
    }

    sections, summary_flag = extract_theme_sections_from_json(payload, max_cards_per_category=2)
    assert "instants" in sections
    instants = sections["instants"]
    assert instants["total_cards"] == 2
    assert instants["available_cards"] == 3
    assert instants["is_truncated"] is True
    assert [card["name"] for card in instants["cards"]] == [
        "Lightning Bolt",
        "Opt",
    ]
    assert summary_flag is False


def test_normalize_theme_colors_handles_aliases():
    profile = normalize_theme_colors(["red", "UG", "blue-green", "Azorius"])
    assert profile["codes"] == ["W", "U", "R", "G"]
    assert profile["slug"] == "sans-black"
    assert profile["symbol"] == "WURG"
