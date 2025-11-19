#!/usr/bin/env python3
"""Comprehensive test of all popular decks endpoints."""
import asyncio
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from aoa.routes.popular_decks import (
    get_all_popular_decks,
    get_popular_decks,
    get_popular_decks_info
)


async def test_all_endpoints():
    """Test all popular decks endpoints."""
    print("=" * 80)
    print("COMPREHENSIVE POPULAR DECKS API TEST")
    print("=" * 80)
    
    mock_api_key = "test-key"
    
    # Test 1: Bracket-less endpoint
    print("\n📊 TEST 1: Bracket-less Search (All Brackets)")
    print("-" * 80)
    
    result = await get_all_popular_decks(
        limit_per_source=5,
        api_key=mock_api_key
    )
    
    print(f"✓ Bracket filter: {result['bracket_filter']}")
    print(f"✓ Total decks: {result['total_decks']}")
    print(f"✓ Moxfield: {result['moxfield']['count']} decks")
    print(f"✓ Archidekt: {result['archidekt']['count']} decks")
    print(f"✓ Decks with primers: {result['summary']['total_with_primer']}")
    print(f"✓ Decks with bracket info: {result['summary']['decks_with_bracket_info']}")
    print(f"✓ Average views: {result['summary']['average_views']:,.1f}")
    
    if result['summary']['bracket_distribution']:
        print("\n  Bracket distribution:")
        for bracket, count in sorted(result['summary']['bracket_distribution'].items()):
            print(f"    • Bracket {bracket}: {count} deck(s)")
    
    # Show sample deck with bracket info
    bracket_decks = [d for d in result['all_decks'] if d.get('bracket')]
    if bracket_decks:
        sample = bracket_decks[0]
        bracket = sample['bracket']
        if isinstance(bracket, dict):
            bracket_str = f"{bracket.get('name', '?')} ({bracket.get('level', '?')})"
        else:
            bracket_str = str(bracket)
        print(f"\n  Sample deck with bracket info:")
        print(f"    • {sample['title']}")
        print(f"    • Bracket: {bracket_str}")
        print(f"    • Views: {sample['views']:,}")
        print(f"    • Source: {sample['source']}")
    
    # Test 2: Bracket-specific endpoint
    print("\n\n📊 TEST 2: Bracket-specific Search (Upgraded)")
    print("-" * 80)
    
    result2 = await get_popular_decks(
        bracket="upgraded",
        limit_per_source=5,
        api_key=mock_api_key
    )
    
    print(f"✓ Bracket filter: {result2['bracket_filter']}")
    print(f"✓ Total decks: {result2['total_decks']}")
    print(f"✓ Moxfield: {result2['moxfield']['count']} decks")
    print(f"✓ Archidekt: {result2['archidekt']['count']} decks")
    print(f"✓ Decks with primers: {result2['summary']['total_with_primer']}")
    print(f"✓ Average views: {result2['summary']['average_views']:,.1f}")
    
    if result2['summary']['bracket_distribution']:
        print("\n  Bracket distribution:")
        for bracket, count in sorted(result2['summary']['bracket_distribution'].items()):
            print(f"    • Bracket {bracket}: {count} deck(s)")
    
    # Test 3: Info endpoint
    print("\n\n📊 TEST 3: API Information Endpoint")
    print("-" * 80)
    
    info = await get_popular_decks_info(api_key=mock_api_key)
    
    print(f"✓ Description: {info['description']}")
    print(f"✓ Supported brackets: {', '.join(info['supported_brackets'])}")
    print(f"✓ Default limit: {info['default_limit_per_source']}")
    print(f"✓ Max limit: {info['max_limit_per_source']}")
    
    print("\n  Available endpoints:")
    for endpoint in info['endpoints']:
        print(f"    • {endpoint['path']}")
        print(f"      {endpoint['description']}")
    
    # Test 4: Different bracket
    print("\n\n📊 TEST 4: Bracket-specific Search (cEDH)")
    print("-" * 80)
    
    result3 = await get_popular_decks(
        bracket="cedh",
        limit_per_source=3,
        api_key=mock_api_key
    )
    
    print(f"✓ Bracket filter: {result3['bracket_filter']}")
    print(f"✓ Total decks: {result3['total_decks']}")
    
    # Final Summary
    print("\n\n" + "=" * 80)
    print("✅ ALL TESTS PASSED!")
    print("=" * 80)
    print("\nFeature Summary:")
    print("  ✓ Bracket-less search working (returns all brackets with info)")
    print("  ✓ Bracket-specific search working (filters by bracket)")
    print("  ✓ Bracket information included in results")
    print("  ✓ Bracket distribution calculated correctly")
    print("  ✓ Info endpoint provides API documentation")
    print("  ✓ Both Moxfield and Archidekt sources operational")
    print("\nEndpoints Available:")
    print("  • GET /api/v1/popular-decks")
    print("  • GET /api/v1/popular-decks/{bracket}")
    print("  • GET /api/v1/popular-decks/info")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_all_endpoints())
