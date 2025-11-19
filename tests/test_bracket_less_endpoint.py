#!/usr/bin/env python3
"""Test the bracket-less popular decks endpoint."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from aoa.routes.popular_decks import get_all_popular_decks


async def test_bracket_less_endpoint():
    """Test the bracket-less endpoint."""
    print("=" * 80)
    print("Testing Bracket-less Popular Decks Endpoint")
    print("=" * 80)
    
    # Mock API key verification
    mock_api_key = "test-key"
    
    # Test with default limit
    print("\n1. Testing with default limit (5 per source)...")
    print("-" * 80)
    
    result = await get_all_popular_decks(
        limit_per_source=5,
        api_key=mock_api_key
    )
    
    print(f"Bracket filter: {result['bracket_filter']}")
    print(f"Total decks: {result['total_decks']}")
    print(f"Moxfield count: {result['moxfield']['count']}")
    print(f"Archidekt count: {result['archidekt']['count']}")
    
    print("\nSummary:")
    print(f"  Total with primer: {result['summary']['total_with_primer']}")
    print(f"  Average views: {result['summary']['average_views']:,.1f}")
    print(f"  Decks with bracket info: {result['summary']['decks_with_bracket_info']}")
    
    if result['summary']['bracket_distribution']:
        print("\n  Bracket distribution:")
        for bracket, count in sorted(result['summary']['bracket_distribution'].items()):
            print(f"    {bracket}: {count} deck(s)")
    
    # Display some sample decks with bracket info
    print("\n2. Sample decks with bracket information:")
    print("-" * 80)
    
    decks_shown = 0
    for deck in result['all_decks']:
        if decks_shown >= 5:  # Show first 5 decks
            break
        
        bracket_info = deck.get('bracket')
        if isinstance(bracket_info, dict):
            bracket_display = f"{bracket_info.get('name', 'Unknown')} ({bracket_info.get('level', '?')})"
        elif bracket_info:
            bracket_display = str(bracket_info)
        else:
            bracket_display = 'Not specified'
        
        print(f"\nDeck {decks_shown + 1} [{deck['source'].upper()}]:")
        print(f"  Title: {deck['title']}")
        print(f"  URL: {deck['url']}")
        print(f"  Views: {deck['views']:,}")
        print(f"  Primer: {'Yes' if deck['has_primer'] else 'No'}")
        print(f"  Bracket: {bracket_display}")
        
        decks_shown += 1
    
    # Test with higher limit
    print("\n\n3. Testing with higher limit (10 per source)...")
    print("-" * 80)
    
    result_large = await get_all_popular_decks(
        limit_per_source=10,
        api_key=mock_api_key
    )
    
    print(f"Total decks: {result_large['total_decks']}")
    print(f"Moxfield count: {result_large['moxfield']['count']}")
    print(f"Archidekt count: {result_large['archidekt']['count']}")
    print(f"Decks with bracket info: {result_large['summary']['decks_with_bracket_info']}")
    
    print("\n" + "=" * 80)
    print("✓ Bracket-less endpoint test complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_bracket_less_endpoint())
