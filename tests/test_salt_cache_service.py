import json

from aoa.services.salt_cache import SaltCacheService


def test_normalize_card_name_collapses_variations():
    assert SaltCacheService.normalize_card_name("Thassa's Oracle") == "thassa s oracle"
    assert SaltCacheService.normalize_card_name("Gaea's Cradle (Judge Foil)") == "gaea s cradle"
    assert SaltCacheService.normalize_card_name("Partner with // Sample") == "sample"


def test_cache_loads_data_and_injects_fallbacks(tmp_path):
    cache_file = tmp_path / "salt_cache.json"
    cache_file.write_text(
        json.dumps(
            {
                "cached_at": "2024-01-01T00:00:00Z",
                "cards": {SaltCacheService.normalize_card_name("Thassa's Oracle"): 2.5},
            }
        )
    )

    service = SaltCacheService(cache_file=str(cache_file))

    assert service.get_card_salt("Thassa's Oracle") == 2.5

    for commander, score in SaltCacheService.COMMANDER_SALT_FALLBACKS.items():
        assert service.salt_data[commander] == score


def test_variant_lookup_matches_split_names(tmp_path):
    cache_file = tmp_path / "salt_cache.json"
    cache_file.write_text(
        json.dumps(
            {
                "cached_at": "2024-01-01T00:00:00Z",
                "cards": {"uro titan of nature s wrath": 1.2},
            }
        )
    )

    service = SaltCacheService(cache_file=str(cache_file))

    variants = service.generate_name_variants("Kroxa, Titan of Death's Hunger // Uro, Titan of Nature's Wrath")
    assert "uro titan of nature s wrath" in variants
    assert "urotitanofnatureswrath" in variants

    score = service.get_card_salt_with_variants(
        "Kroxa, Titan of Death's Hunger // Uro, Titan of Nature's Wrath"
    )
    assert score == 1.2
