#!/usr/bin/env python3
"""
Test script for the new deck validation endpoints
Tests the deck validation functionality with sample data
"""

import asyncio
import json
import sys
from typing import List, Dict, Any
from pydantic import BaseModel
import httpx


class DeckValidationRequest(BaseModel):
    """Request model for deck validation"""
    decklist: List[str]
    commander: str = None
    target_bracket: str = None
    source_urls: List[str] = []
    validate_bracket: bool = True
    validate_legality: bool = True


async def test_deck_validation():
    """Test the deck validation endpoint"""
    base_url = "http://localhost:8000"
    headers = {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient(base_url=base_url, headers=headers) as client:
        
        print("🧪 Testing Deck Validation Endpoints")
        print("=" * 50)
        
        # Test 1: Get brackets info
        print("\n1. Testing /api/v1/brackets/info endpoint...")
        try:
            response = await client.get("/api/v1/brackets/info")
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Brackets info retrieved successfully")
                print(f"   Available brackets: {list(data['brackets'].keys())}")
                print(f"   Game changers count: {data['game_changers']['current_list_size']}")
            else:
                print(f"❌ Failed to get brackets info: {response.status_code}")
        except Exception as e:
            print(f"❌ Error testing brackets info: {e}")
        
        # Test 2: Get game changers list
        print("\n2. Testing /api/v1/brackets/game-changers/list endpoint...")
        try:
            response = await client.get("/api/v1/brackets/game-changers/list")
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Game changers list retrieved successfully")
                print(f"   Current game changers: {len(data['current_game_changers'])}")
                print(f"   Recently removed: {len(data['recently_removed'])}")
                print(f"   Sample recent removals: {data['recently_removed'][:3]}")
            else:
                print(f"❌ Failed to get game changers: {response.status_code}")
        except Exception as e:
            print(f"❌ Error testing game changers list: {e}")
        
        # Test 3: Sample validation
        print("\n3. Testing /api/v1/deck/validate/sample endpoint...")
        try:
            response = await client.get("/api/v1/deck/validate/sample")
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Sample validation completed successfully")
                print(f"   Sample commander: {data['sample_request']['commander']}")
                print(f"   Target bracket: {data['sample_request']['target_bracket']}")
                print(f"   Total cards in sample: {len(data['sample_request']['decklist'])}")
                
                # Check validation results
                validation = data['validation_result']
                if validation['bracket_validation']:
                    bv = validation['bracket_validation']
                    print(f"   Bracket compliance: {bv['overall_compliance']}")
                    print(f"   Bracket score: {bv['bracket_score']}")
                    if bv['violations']:
                        print(f"   Violations: {len(bv['violations'])}")
                        for violation in bv['violations'][:2]:
                            print(f"     - {violation}")
                
                legality = validation['legality_validation']
                print(f"   Format legal: {legality['is_legal']}")
                
            else:
                print(f"❌ Failed sample validation: {response.status_code}")
        except Exception as e:
            print(f"❌ Error testing sample validation: {e}")
        
        # Test 4: Custom deck validation
        print("\n4. Testing custom deck validation...")
        try:
            custom_deck = DeckValidationRequest(
                decklist=[
                    "1x Jace, Wielder of Mysteries",  # Commander
                    "4x Island",
                    "1x Sol Ring",
                    "1x Demonic Consultation",
                    "1x Thassa's Oracle",
                    "1x Ponder",
                    "1x Brainstorm",
                    "1x Counterspell",
                    "1x Force of Will",
                    "1x Vampiric Tutor",
                    "1x Ad Nauseam",
                    "95x Island"
                ],
                commander="Jace, Wielder of Mysteries",
                target_bracket="optimized",
                source_urls=[
                    "https://archiveofargentum.com/reference/mass-land-denial",
                    "https://archiveofargentum.com/reference/game-changers",
                    "https://edhrec.com/combos/early-game-2-card-combos"
                ],
                validate_bracket=True,
                validate_legality=True
            )
            
            response = await client.post("/api/v1/deck/validate", json=custom_deck.dict())
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Custom deck validation completed successfully")
                print(f"   Success: {data['success']}")
                print(f"   Total cards: {data['deck_summary']['total_cards']}")
                
                if data['bracket_validation']:
                    bv = data['bracket_validation']
                    print(f"   Bracket validation:")
                    print(f"     - Target: {bv['target_bracket']}")
                    print(f"     - Compliance: {bv['overall_compliance']}")
                    print(f"     - Score: {bv['bracket_score']}/5")
                    
                    if bv['violations']:
                        print(f"     - Violations found:")
                        for violation in bv['violations']:
                            print(f"       * {violation}")
                    
                    if bv['recommendations']:
                        print(f"     - Recommendations:")
                        for rec in bv['recommendations'][:3]:
                            print(f"       * {rec}")
                
                print(f"   Legality validation: {data['legality_validation']['is_legal']}")
                if not data['legality_validation']['is_legal']:
                    print(f"   Legal issues: {data['legality_validation']['issues']}")
                
                print(f"   Source analysis:")
                source_analysis = data['source_analysis']
                print(f"     - Sources scraped: {source_analysis['sources_scraped']}")
                print(f"     - Reference categories: {source_analysis['reference_categories']}")
                
            else:
                print(f"❌ Failed custom deck validation: {response.status_code}")
                print(f"Response: {response.text}")
        except Exception as e:
            print(f"❌ Error testing custom deck validation: {e}")
        
        print("\n" + "=" * 50)
        print("🎉 Deck validation testing completed!")
        print("\n📋 Next steps:")
        print("1. Test the endpoint with your own deck lists")
        print("2. Experiment with different target brackets")
        print("3. Add source URLs for reference comparison")
        print("4. Deploy to your Render app for public access")


if __name__ == "__main__":
    print("Starting deck validation tests...")
    print("Make sure the FastAPI server is running on localhost:8000")
    print("Default API key: test-key")
    
    # Check if server is running
    asyncio.run(test_deck_validation())