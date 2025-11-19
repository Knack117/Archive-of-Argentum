#!/usr/bin/env python3
"""Test script for bracket-less popular decks search."""
import asyncio
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from aoa.routes.popular_decks import (
    scrape_moxfield_popular_decks,
    scrape_archidekt_popular_decks
)


async def test_bracket_less_search():
    """Test fetching popular decks without bracket filtering."""
    print("=" * 80)
    print("Testing Bracket-less Popular Decks Search")
    print("=" * 80)
    
    # Test Moxfield without bracket filter
    print("\n1. Testing Moxfield API (no bracket filter)...")
    print("-" * 80)
    moxfield_decks = await scrape_moxfield_popular_decks(bracket=None, limit=5)
    
    if moxfield_decks:
        print(f"✓ Successfully fetched {len(moxfield_decks)} decks from Moxfield")
        for i, deck in enumerate(moxfield_decks, 1):
            bracket_info = deck.get('bracket', 'Not specified')
            if isinstance(bracket_info, dict):
                bracket_display = f"{bracket_info.get('name', 'Unknown')} ({bracket_info.get('level', '?')})"
            else:
                bracket_display = str(bracket_info) if bracket_info else 'Not specified'
            
            print(f"\n  Deck {i}:")
            print(f"    Title: {deck['title']}")
            print(f"    URL: {deck['url']}")
            print(f"    Views: {deck['views']:,}")
            print(f"    Primer: {'Yes' if deck['has_primer'] else 'No'}")
            print(f"    Bracket: {bracket_display}")
            print(f"    Author: {deck.get('author', 'Unknown')}")
    else:
        print("✗ Failed to fetch decks from Moxfield")
    
    # Test Archidekt without bracket filter
    print("\n\n2. Testing Archidekt scraping (no bracket filter)...")
    print("-" * 80)
    archidekt_decks = await scrape_archidekt_popular_decks(bracket=None, limit=5)
    
    if archidekt_decks:
        print(f"✓ Successfully fetched {len(archidekt_decks)} decks from Archidekt")
        for i, deck in enumerate(archidekt_decks, 1):
            bracket_info = deck.get('bracket')
            if isinstance(bracket_info, dict):
                bracket_display = f"{bracket_info.get('name', 'Unknown')} ({bracket_info.get('level', '?')})"
            else:
                bracket_display = str(bracket_info) if bracket_info else 'Not specified'
            
            print(f"\n  Deck {i}:")
            print(f"    Title: {deck['title']}")
            print(f"    URL: {deck['url']}")
            print(f"    Views: {deck['views']:,}")
            print(f"    Primer: {'Yes' if deck['has_primer'] else 'No'}")
            print(f"    Bracket: {bracket_display}")
    else:
        print("✗ Failed to fetch decks from Archidekt")
    
    # Summary
    print("\n\n3. Summary")
    print("=" * 80)
    all_decks = moxfield_decks + archidekt_decks
    total_decks = len(all_decks)
    decks_with_primer = sum(1 for d in all_decks if d.get('has_primer', False))
    decks_with_bracket = sum(1 for d in all_decks if d.get('bracket') is not None)
    
    print(f"Total decks fetched: {total_decks}")
    print(f"Decks with primers: {decks_with_primer}")
    print(f"Decks with bracket info: {decks_with_bracket}")
    
    # Bracket distribution
    bracket_counts = {}
    for deck in all_decks:
        if deck.get('bracket'):
            if isinstance(deck['bracket'], dict):
                bracket_name = deck['bracket'].get('name', 'Unknown')
            else:
                bracket_name = str(deck['bracket'])
            bracket_counts[bracket_name] = bracket_counts.get(bracket_name, 0) + 1
    
    if bracket_counts:
        print("\nBracket distribution:")
        for bracket, count in sorted(bracket_counts.items()):
            print(f"  {bracket}: {count} deck(s)")
    
    if total_decks > 0:
        avg_views = sum(d.get('views', 0) for d in all_decks) / total_decks
        print(f"\nAverage views: {avg_views:,.1f}")
    
    print("\n" + "=" * 80)
    print("Test complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_bracket_less_search())
