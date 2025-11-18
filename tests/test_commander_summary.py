"""Regression tests for commander summary extraction."""
import json
from pathlib import Path

import pytest

from aoa.services.commanders import (
    extract_commander_json_data,
    extract_commander_sections_from_json,
    extract_commander_tags_from_json,
    scrape_edhrec_commander_page,
)


@pytest.fixture(scope="module")
def sample_payload() -> dict:
    """Load the static EDHRec payload used for regression tests."""
    payload_path = Path(__file__).resolve().parents[1] / "edhrec_json_sample.json"
    with payload_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def sample_data(sample_payload: dict) -> dict:
    """Return the nested data block used throughout the tests."""
    return sample_payload["pageProps"]["data"]


def test_extract_commander_json_data_from_standard_payload(sample_payload: dict) -> None:
    """The parser should return full commander details from legacy payloads."""
    result = extract_commander_json_data(sample_payload)

    assert result["all_tags"], "Expected commander tags to be extracted"
    assert result["all_tags"][0]["tag"] == "Dragons"
    assert "Dragons" in result["commander_tags"]
    assert "New Cards" in result["categories"]
    assert len(result["categories"]["New Cards"]["cards"]) >= 5
    assert len(result["combos"]) >= 3
    assert result["similar_commanders"], "Similar commanders should be populated"


def test_extract_commander_json_data_from_nested_props(sample_data: dict) -> None:
    """Support the current Next.js payload shape where data lives under props.pageProps."""
    wrapped_payload = {"props": {"pageProps": {"data": sample_data}}}

    result = extract_commander_json_data(wrapped_payload)

    assert any(tag["tag"] == "Dragons" for tag in result["all_tags"])
    assert "New Cards" in result["categories"]


def test_extract_commander_json_data_from_fallback_payload(sample_data: dict) -> None:
    """Support payloads where the data is nested inside a fallback dictionary."""
    fallback_payload = {
        "props": {
            "pageProps": {
                "fallback": {
                    "/commanders/the-ur-dragon": {"pageProps": {"data": sample_data}}
                }
            }
        }
    }

    result = extract_commander_json_data(fallback_payload)

    assert result["top_10_tags"], "Top tags should still be derived from fallback payloads"
    assert len(result["categories"]) >= 1


def test_extract_commander_sections_and_tags_support_nested_data(sample_data: dict) -> None:
    """Regression test for the helper utilities used by the FastAPI routes."""
    payload = {"props": {"pageProps": {"data": sample_data}}}

    tags = extract_commander_tags_from_json(payload)
    sections = extract_commander_sections_from_json(payload)

    assert "Dragons" in tags
    assert "New Cards" in sections
    assert sections["New Cards"][0] == "Great Divide Guide"


@pytest.mark.asyncio
async def test_scrape_edhrec_commander_page_returns_full_summary(
    sample_payload: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure the higher-level scraper bubbles up all sections for API consumers."""

    async def fake_fetch(_: str) -> dict:
        return sample_payload

    monkeypatch.setattr("aoa.services.commanders.fetch_edhrec_json", fake_fetch)

    result = await scrape_edhrec_commander_page("https://edhrec.com/commanders/the-ur-dragon")

    assert result["commander_name"] == "The Ur Dragon"
    assert len(result["all_tags"]) >= 10
    assert result["combos"][0]["name"].startswith("Dragon Tempest")
    assert "New Cards" in result["categories"]
    assert result["categories"]["New Cards"]["cards"][0]["name"] == "Great Divide Guide"
