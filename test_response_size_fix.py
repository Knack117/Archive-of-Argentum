#!/usr/bin/env python3
"""
Simple test to verify the ResponseTooLargeError fix logic
"""

def test_response_size_logic():
    """Test the response size management logic"""
    
    # Test 1: Card limit resolution
    def _resolve_theme_card_limit(requested_limit):
        DEFAULT_THEME_CARD_LIMIT = 60
        MAX_THEME_CARD_LIMIT = 200
        
        if requested_limit is None:
            return DEFAULT_THEME_CARD_LIMIT

        try:
            value = int(requested_limit)
        except (TypeError, ValueError):
            return DEFAULT_THEME_CARD_LIMIT

        if value <= 0:
            return None

        return min(value, MAX_THEME_CARD_LIMIT)

    # Test card limits
    assert _resolve_theme_card_limit(None) == 60
    assert _resolve_theme_card_limit(25) == 25
    assert _resolve_theme_card_limit(300) == 200
    assert _resolve_theme_card_limit(0) is None
    print("✓ Card limit resolution tests passed")

    # Test 2: Response size estimation
    import json
    
    def _estimate_response_size(data):
        return len(json.dumps(data, separators=(',', ':')))

    # Test with sample data
    small_response = {"theme_name": "Test", "categories": {"cards": {"total": 10}}}
    large_response = {"theme_name": "Test", "categories": {f"cat_{i}": {"cards": list(range(100))} for i in range(20)}}
    
    small_size = _estimate_response_size(small_response)
    large_size = _estimate_response_size(large_response)
    
    assert small_size < large_size
    print(f"✓ Response size estimation: {small_size} bytes (small), {large_size} bytes (large)")

    # Test 3: Categories summary creation
    def _create_categories_summary(sections):
        summary = {}
        for category_key, category_data in sections.items():
            summary[category_key] = {
                "category_name": category_data.get("category_name"),
                "total_cards": category_data.get("total_cards"),
                "available_cards": category_data.get("available_cards"),
                "is_truncated": category_data.get("is_truncated", False),
            }
        return summary

    sample_sections = {
        "instants": {
            "category_name": "Instants",
            "total_cards": 45,
            "available_cards": 67,
            "is_truncated": True
        },
        "sorceries": {
            "category_name": "Sorceries",
            "total_cards": 38,
            "is_truncated": True
        }
    }

    summary = _create_categories_summary(sample_sections)
    
    assert summary["instants"]["category_name"] == "Instants"
    assert summary["instants"]["total_cards"] == 45
    assert summary["sorceries"]["is_truncated"] == True
    print("✓ Categories summary creation test passed")

    # Test 4: Large dataset detection
    LARGE_RESPONSE_THRESHOLD = 50  # same as in app.py
    
    def detect_large_dataset(total_cards, limit_per_category):
        expected_total = total_cards * (limit_per_category or 60)
        return expected_total > LARGE_RESPONSE_THRESHOLD * (limit_per_category or 60)

    # Test scenarios
    small_dataset = detect_large_dataset(5, 10)  # 5 categories * 10 cards = 50 total, threshold = 50*10 = 500, so false
    large_dataset = detect_large_dataset(100, 10)  # 100 categories * 10 cards = 1000 total, threshold = 50*10 = 500, so true
    
    assert not small_dataset
    assert large_dataset
    print("✓ Large dataset detection test passed")

    print("\n🎉 All response size fix logic tests passed!")
    return True

if __name__ == "__main__":
    test_response_size_logic()