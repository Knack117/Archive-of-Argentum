#!/usr/bin/env python3
"""
Test the complete EDHRec scraping workflow with The Ur-Dragon
"""
import asyncio
import sys
import os
import logging

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import scrape_edhrec_commander_page, extract_commander_name_from_url

# Configure logging to see the debug info
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

async def test_ur_dragon_scraping():
    """Test scraping The Ur-Dragon commander page"""
    
    # Test URL for The Ur-Dragon
    test_url = "https://edhrec.com/commanders/the-ur-dragon"
    
    print("=== Testing Complete EDHRec Scraping Workflow ===")
    print(f"Testing URL: {test_url}")
    
    try:
        # Extract commander name
        commander_name = extract_commander_name_from_url(test_url)
        print(f"Extracted commander name: {commander_name}")
        
        # Run the complete scraping workflow
        print("\n=== Starting Scraping Process ===")
        result = await scrape_edhrec_commander_page(test_url)
        
        print("\n=== Scraping Results ===")
        print(f"Commander: {result['commander_name']}")
        print(f"Commander URL: {result['commander_url']}")
        print(f"Timestamp: {result['timestamp']}")
        
        # Check tags
        print(f"\nCommander Tags ({len(result['commander_tags'])} total):")
        for i, tag in enumerate(result['commander_tags'][:10]):
            print(f"  {i+1:2d}. {tag}")
        if len(result['commander_tags']) > 10:
            print(f"  ... and {len(result['commander_tags']) - 10} more tags")
        
        # Check top 10 tags with percentages
        print(f"\nTop 10 Tags with Percentages:")
        for tag_info in result['top_10_tags']:
            print(f"  {tag_info['rank']:2d}. {tag_info['tag']} ({tag_info['percentage']})")
        
        # Check card categories
        print(f"\nCard Categories ({len(result['categories'])} total):")
        total_cards = 0
        for category_key, category_data in result['categories'].items():
            category_name = category_data['category_name']
            card_count = category_data['total_cards']
            total_cards += card_count
            print(f"  {category_name}: {card_count} cards")
            
            # Show first few cards in each category
            if category_data['cards']:
                print(f"    First few cards:")
                for i, card in enumerate(category_data['cards'][:3]):
                    print(f"      {i+1}. {card['name']} ({card['inclusion_percentage']} inclusion, {card['synergy_percentage']} synergy)")
                if len(category_data['cards']) > 3:
                    print(f"      ... and {len(category_data['cards']) - 3} more cards")
        
        print(f"\nTotal cards across all categories: {total_cards}")
        
        print("\n✅ SUCCESS: Complete scraping workflow working with real EDHRec data!")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_ur_dragon_scraping())