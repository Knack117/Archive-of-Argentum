import pytest

from app import _build_theme_route_candidates, _split_color_prefixed_theme_slug


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
    assert candidates == [
        {
            "page_path": "themes/spellslinger",
            "json_path": "themes/spellslinger.json",
        }
    ]


def test_build_theme_route_candidates_handles_five_color_slug():
    candidates = _build_theme_route_candidates("five-color-gates")
    assert candidates[0]["page_path"] == "tags/gates/five-color"
    assert candidates[0]["json_path"] == "tags/gates/five-color.json"
