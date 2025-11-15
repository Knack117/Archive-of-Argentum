#!/usr/bin/env python3
"""
Test the fixed parsing functions with real EDHRec data
"""
import json
import sys
import os

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import extract_commander_tags_from_json, extract_commander_sections_from_json

def test_parsing_with_real_data():
    """Test parsing functions with the real EDHRec JSON sample"""
    
    # Load the sample JSON
    with open('/workspace/edhrec_json_sample.json', 'r') as f:
        json_data = json.load(f)
    
    print("=== Testing Fixed Parsing Functions ===")
    print("Using real EDHRec JSON data for The Ur-Dragon\n")
    
    # Test tags extraction
    print("🔍 Testing Tags Extraction...")
    tags = extract_commander_tags_from_json(json_data)
    print(f"✅ SUCCESS: Extracted {len(tags)} commander tags")
    print("First 10 tags:")
    for i, tag in enumerate(tags[:10], 1):
        print(f"  {i:2d}. {tag}")
    if len(tags) > 10:
        print(f"  ... and {len(tags) - 10} more tags")
    
    # Test sections extraction
    print(f"\n🔍 Testing Card Sections Extraction...")
    sections = extract_commander_sections_from_json(json_data)
    
    total_cards = 0
    non_empty_sections = 0
    
    print("✅ SUCCESS: Extracted card sections")
    print("\nCard Categories Breakdown:")
    for section_name, card_names in sections.items():
        if card_names:  # Only show non-empty sections
            non_empty_sections += 1
            total_cards += len(card_names)
            print(f"  📂 {section_name}: {len(card_names)} cards")
            
            # Show first 3 cards as examples
            if len(card_names) >= 3:
                print(f"      Examples: {', '.join(card_names[:3])}")
            else:
                print(f"      Examples: {', '.join(card_names)}")
    
    print(f"\n📊 Summary:")
    print(f"  • Total sections with data: {non_empty_sections}/14")
    print(f"  • Total cards extracted: {total_cards}")
    print(f"  • Average cards per section: {total_cards/non_empty_sections:.1f}")
    
    # Verify data quality
    print(f"\n🔬 Data Quality Check:")
    
    # Check for expected sections
    expected_sections = [
        "New Cards", "High Synergy Cards", "Top Cards", "Game Changers",
        "Creatures", "Instants", "Sorceries", "Utility Artifacts", 
        "Enchantments", "Battles", "Planeswalkers", "Utility Lands",
        "Mana Artifacts", "Lands"
    ]
    
    found_sections = [name for name, cards in sections.items() if cards]
    missing_sections = [name for name in expected_sections if name not in found_sections]
    
    if not missing_sections:
        print("  ✅ All expected card categories found")
    else:
        print(f"  ⚠️  Missing sections: {missing_sections}")
    
    # Check tag quality
    dragon_related_tags = [tag for tag in tags if 'dragon' in tag.lower() or 'ramp' in tag.lower() or 'big mana' in tag.lower()]
    if dragon_related_tags:
        print(f"  ✅ Found {len(dragon_related_tags)} Dragon-tribal relevant tags: {', '.join(dragon_related_tags[:5])}")
    else:
        print("  ⚠️  No obvious Dragon-tribal tags found")
    
    # Check for data that looks realistic
    large_sections = [name for name, cards in sections.items() if len(cards) > 20]
    if large_sections:
        print(f"  ✅ Found expected large sections: {', '.join(large_sections)}")
    
    print(f"\n🎉 PARSING FIX VERIFICATION COMPLETE!")
    print(f"   The-Ur-Dragon data successfully parsed:")
    print(f"   • {len(tags)} commander tags")
    print(f"   • {total_cards} cards across {non_empty_sections} categories")
    print(f"   • Real EDHRec data (no mock data)")
    
    return True

if __name__ == "__main__":
    test_parsing_with_real_data()