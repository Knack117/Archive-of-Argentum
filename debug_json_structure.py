#!/usr/bin/env python3
"""
Debug script to analyze the EDHRec JSON structure and test parsing functions
"""
import json
import os
import sys

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import extract_commander_tags_from_json, extract_commander_sections_from_json

def analyze_json_structure():
    """Analyze the actual JSON structure to understand the data layout"""
    
    # Load the sample JSON
    with open('/workspace/edhrec_json_sample.json', 'r') as f:
        json_data = json.load(f)
    
    print("=== JSON Structure Analysis ===")
    print(f"Top-level keys: {list(json_data.keys())}")
    
    # Analyze pageProps structure
    if 'pageProps' in json_data:
        page_props = json_data['pageProps']
        print(f"\npageProps keys: {list(page_props.keys())}")
        
        if 'data' in page_props:
            data = page_props['data']
            print(f"data keys: {list(data.keys())}")
            
            # Check for json_dict
            if 'json_dict' in data:
                json_dict = data['json_dict']
                print(f"json_dict keys: {list(json_dict.keys())}")
                
                # Check panels
                if 'panels' in json_dict:
                    panels = json_dict['panels']
                    print(f"panels keys: {list(panels.keys())}")
                    
                    if 'links' in panels:
                        links = panels['links']
                        print(f"links array length: {len(links)}")
                        print("First few link headers:")
                        for i, link in enumerate(links[:5]):
                            print(f"  {i}: header='{link.get('header', 'N/A')}', items_count={len(link.get('items', []))}")
            
            # Check for cardlists directly in data
            if 'cardlists' in data:
                cardlists = data['cardlists']
                print(f"\ncardlists found directly in data! Array length: {len(cardlists)}")
                print("Card section headers:")
                for i, section in enumerate(cardlists):
                    print(f"  {i}: header='{section.get('header', 'N/A')}', cardviews_count={len(section.get('cardviews', []))}")
            else:
                print("\ncardlists NOT found directly in data")
            
            # Search for any cardlists in the entire structure
            def find_cardlists(obj, path="root"):
                if isinstance(obj, dict):
                    if 'cardlists' in obj:
                        cardlists = obj['cardlists']
                        print(f"\nFound cardlists at {path}['cardlists']: {len(cardlists)} sections")
                        print("Headers:")
                        for i, section in enumerate(cardlists):
                            header = section.get('header', 'N/A')
                            cardviews_count = len(section.get('cardviews', []))
                            print(f"  {i}: '{header}' ({cardviews_count} cards)")
                        return True
                    for key, value in obj.items():
                        if find_cardlists(value, f"{path}['{key}']"):
                            return True
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        if find_cardlists(item, f"{path}[{i}]"):
                            return True
                return False
            
            print("\n=== Searching entire structure for cardlists ===")
            find_cardlists(data)

def test_current_parsing():
    """Test the current parsing functions with the sample JSON"""
    
    # Load the sample JSON
    with open('/workspace/edhrec_json_sample.json', 'r') as f:
        json_data = json.load(f)
    
    print("\n=== Testing Current Parsing Functions ===")
    
    # Test tags extraction
    print("\n--- Testing Tags Extraction ---")
    tags = extract_commander_tags_from_json(json_data)
    print(f"Extracted {len(tags)} tags: {tags[:10]}...")
    
    # Test sections extraction
    print("\n--- Testing Sections Extraction ---")
    sections = extract_commander_sections_from_json(json_data)
    print("Extracted sections:")
    for section_name, cards in sections.items():
        if cards:  # Only show non-empty sections
            print(f"  {section_name}: {len(cards)} cards")
            print(f"    First few: {cards[:3]}")

if __name__ == "__main__":
    analyze_json_structure()
    test_current_parsing()