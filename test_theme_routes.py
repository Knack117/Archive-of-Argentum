import pytest

from app import (
    _build_theme_route_candidates,
    _parse_theme_slugs_from_html,
    _resolve_theme_card_limit,
    _split_color_prefixed_theme_slug,
    _split_theme_slug,
    _validate_theme_slug_against_catalog,
    extract_theme_sections_from_json,
    normalize_theme_colors,
)
from fastapi import HTTPException


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


def test_build_theme_route_candidates_handles_color_suffix_slug():
    candidates = _build_theme_route_candidates("goblins-mono-red")
    assert candidates[0]["page_path"] == "tags/goblins/mono-red"
    assert any(candidate["page_path"] == "themes/goblins-mono-red" for candidate in candidates)


def test_split_theme_slug_detects_suffix_color():
    theme, color, position = _split_theme_slug("goblins-mono-red")
    assert theme == "goblins"
    assert color == "mono-red"
    assert position == "suffix"


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


def test_parse_theme_slugs_from_html_extracts_unique_theme_names():
    html = """
    <html>
        <body>
            <a href="/tags/spellslinger">Spellslinger</a>
            <a href="https://edhrec.com/tags/tokens">Tokens</a>
            <a href="/tags/tokens/azorius">Tokens Azorius</a>
            <a href="/tags/azorius">Azorius Colors</a>
        </body>
    </html>
    """

    slugs = _parse_theme_slugs_from_html(html)
    assert slugs == {"spellslinger", "tokens"}


def test_validate_theme_slug_against_catalog_allows_color_variants():
    catalog = {"spellslinger", "tokens"}
    _validate_theme_slug_against_catalog("temur-spellslinger", catalog)


def test_validate_theme_slug_against_catalog_rejects_unknown_theme():
    catalog = {"spellslinger"}
    with pytest.raises(HTTPException) as exc:
        _validate_theme_slug_against_catalog("orzhov-aristocrats", catalog)

    assert exc.value.status_code == 404
    assert "aristocrats" in exc.value.detail
