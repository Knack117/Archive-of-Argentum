#!/usr/bin/env python3
"""Regression tests for theme response size safeguards."""

from app import (
    _create_categories_summary,
    _estimate_response_size,
    _generate_card_limit_plan,
    _resolve_theme_card_limit,
)


def test_theme_card_limit_resolution():
    assert _resolve_theme_card_limit(None) == 60
    assert _resolve_theme_card_limit(25) == 25
    assert _resolve_theme_card_limit(300) == 200
    assert _resolve_theme_card_limit(0) == 0
    assert _resolve_theme_card_limit(-5) == 60


def test_estimate_response_size_orders_by_payload():
    small_response = {"theme_name": "Test", "categories": {"cards": {"total": 10}}}
    large_response = {
        "theme_name": "Test",
        "categories": {
            f"cat_{i}": {"cards": list(range(100))}
            for i in range(20)
        },
    }

    assert _estimate_response_size(small_response) < _estimate_response_size(large_response)


def test_create_categories_summary_preserves_metadata():
    sample_sections = {
        "instants": {
            "category_name": "Instants",
            "total_cards": 45,
            "available_cards": 67,
            "is_truncated": True,
        },
        "sorceries": {
            "category_name": "Sorceries",
            "total_cards": 38,
            "is_truncated": True,
        },
    }

    summary = _create_categories_summary(sample_sections)

    assert summary["instants"]["category_name"] == "Instants"
    assert summary["instants"]["total_cards"] == 45
    assert summary["sorceries"]["is_truncated"] is True


def test_generate_card_limit_plan_scales_down():
    default_plan = _generate_card_limit_plan(60)
    assert default_plan[0] == 60
    assert default_plan[-1] == 1
    assert any(limit < 60 for limit in default_plan[1:])

    zero_plan = _generate_card_limit_plan(0)
    assert zero_plan == [0]

    large_plan = _generate_card_limit_plan(200)
    assert large_plan[0] == 200
    assert 100 in large_plan or 120 in large_plan
