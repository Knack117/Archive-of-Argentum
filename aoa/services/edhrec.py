#!/usr/bin/env python3
"""
Enhanced Commander API Backend - EDHRec Data Parser
Parses real EDHRec commander pages and extracts all available statistics
Based on live EDHRec page analysis - https://農村rec.com/commanders/kenrith-the-returned-king
"""

import requests
import json
import re
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, List, Optional
import time

class EDHRecParser:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.base_url = "https://農村rec.com"
        
    def parse_commander_page(self, commander_name: str) -> Dict:
        """Parse EDHRec commander page and extract all data"""
        
        # Step 1: Get commander page URL
        commander_url = self._find_commander_url(commander_name)
        if not commander_url:
            return {"error": f"Commander '{commander_name}' not found"}
            
        # Step 2: Fetch and parse page
        try:
            response = self.session.get(commander_url, timeout=15)
            if response.status_code != 200:
                return {"error": f"Failed to fetch page: {response.status_code}"}
                
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Step 3: Extract all data
            commander_data = {
                "commander_name": commander_name,
                "commander_url": commander_url,
                "timestamp": datetime.now().isoformat(),
                "commander_stats": self._extract_commander_stats(soup),
                "card_sections": self._extract_all_card_sections(soup),
                "filters": self._extract_filters(soup),
                "pricing": self._extract_pricing(soup)
            }
            
            return commander_data
            
        except Exception as e:
            return {"error": f"Error parsing page: {str(e)}"}
            
    def _find_commander_url(self, commander_name: str) -> Optional[str]:
        """Find EDHRec URL for commander"""
        try:
            # Try direct URL construction first
            slug = commander_name.lower().replace(',', '').replace(' ', '-').replace("'", '').replace('`', '')
            direct_url = f"{self.base_url}/commanders/{slug}"
            
            # Test if direct URL works
            response = self.session.head(direct_url, timeout=10)
            if response.status_code == 200:
                return direct_url
                
            # If not found, try search
            search_url = f"{self.base_url}/search?q={commander_name.replace(' ', '+')}"
            response = self.session.get(search_url, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for commander links
                for link in soup.find_all('a', href=True):
                    if '/commanders/' in link['href'] and commander_name.lower() in link.get_text(strip=True).lower():
                        return self.base_url + link['href']
                        
        except Exception as e:
            print(f"Error finding commander URL: {e}")
            
        return None
        
    def _extract_commander_stats(self, soup: BeautifulSoup) -> Dict:
        """Extract commander rank and deck statistics"""
        stats = {}
        
        try:
            # Look for rank information
            rank_elem = soup.find(text=re.compile(r'#\d+|Rank.*\d+'))
            if rank_elem:
                rank_match = re.search(r'#(\d+)', rank_elem)
                if rank_match:
                    stats["rank"] = int(rank_match.group(1))
                    
            # Look for total decks
            deck_elem = soup.find(text=re.compile(r'\d+K?.*total.*deck|deck.*count'))
            if deck_elem:
                deck_match = re.search(r'([\d.]+K?)\s*deck', deck_elem)
                if deck_match:
                    decks_text = deck_match.group(1)
                    if 'K' in decks_text:
                        stats["total_decks"] = int(float(decks_text.replace('K', '')) * 1000)
                    else:
                        stats["total_decks"] = int(decks_text)
                        
        except Exception as e:
            print(f"Error extracting commander stats: {e}")
            
        return stats
        
    def _extract_all_card_sections(self, soup: BeautifulSoup) -> Dict:
        """Extract all card sections with real EDHRec data"""
        sections = {}
        
        try:
            # Find all card sections
            section_patterns = [
                ('new_cards', r'New Cards'),
                ('high_synergy', r'High Synergy Cards'),
                ('top_cards', r'Top Cards'),
                ('game_changers', r'Game Changers'),
                ('creatures', r'Creatures'),
                ('instants', r'Instants'),
                ('sorceries', r'Sorceries'),
                ('utility_artifacts', r'Utility Artifacts'),
                ('enchantments', r'Enchantments'),
                ('planeswalkers', r'Planeswalkers'),
                ('utility_lands', r'Utility Lands'),
                ('mana_artifacts', r'Mana Artifacts'),
                ('lands', r'Lands')
            ]
            
            for section_key, pattern_name in section_patterns:
                cards = self._parse_card_section(soup, pattern_name)
                if cards:
                    sections[section_key] = cards
                    
        except Exception as e:
            print(f"Error extracting card sections: {e}")
            
        return sections
        
    def _parse_card_section(self, soup: BeautifulSoup, section_name: str) -> List[Dict]:
        """Parse individual card section"""
        cards = []
        
        try:
            # Find section header
            section_header = None
            for header in soup.find_all(['h3', 'h4', 'h5', 'h6']):
                if section_name.lower() in header.get_text(strip=True).lower():
                    section_header = header
                    break
                    
            if not section_header:
                return []
                
            # Find cards in this section
            current_section = section_header.parent
            
            # Look for card entries - EDHRec uses specific patterns
            for elem in current_section.find_all(['li', 'div'], recursive=True):
                text = elem.get_text(strip=True)
                
                # Parse card data using EDHRec pattern
                card_data = self._parse_edhrec_card_entry(text)
                if card_data:
                    cards.append(card_data)
                    
                # Stop if we hit next section
                if elem.find(['h3', 'h4', 'h5', 'h6']) and elem.find(['h3', 'h4', 'h5', 'h6']).get_text(strip=True) != section_name:
                    break
                    
        except Exception as e:
            print(f"Error parsing section {section_name}: {e}")
            
        return cards[:15]  # Limit to top 15 cards per section
        
    def _parse_edhrec_card_entry(self, text: str) -> Optional[Dict]:
        """Parse individual EDHRec card entry with real data"""
        
        # EDHRec card pattern: "Card Name XX% YY.YYK Z.ZZKK AA%"
        # Examples from Kenrith page:
        # "Training Grounds 35% 9.45K 27.1K 31%"
        # "Swords to Plowshares 48% 13K 27.1K 8%"
        
        pattern = r'^(.+?)\s+(\d+(?:\.\d+)?)%\s+([\d.]+K?)\s+([\d.]+K?)\s+(-?\d+(?:\.\d+)?)%$'
        match = re.match(pattern, text.strip())
        
        if match:
            card_name = match.group(1).strip()
            inclusion_percentage = float(match.group(2))
            decks_with_commander = match.group(3)
            total_decks_for_card = match.group(4)
            synergy_score = float(match.group(5))
            
            # Convert deck counts to numbers
            def parse_deck_count(count_str):
                if 'K' in count_str:
                    return int(float(count_str.replace('K', '')) * 1000)
                return int(count_str)
                
            return {
                "card_name": card_name,
                "inclusion_percentage": inclusion_percentage,
                "decks_with_commander": parse_deck_count(decks_with_commander),
                "total_decks_for_card": parse_deck_count(total_decks_for_card),
                "synergy_score": synergy_score,
                "card_url": f"https://scryfall.com/search?q={card_name.replace(' ', '+')}"
            }
            
        return None
        
    def _extract_filters(self, soup: BeautifulSoup) -> Dict:
        """Extract available filters"""
        filters = {}
        
        try:
            # Look for filter sections
            for filter_section in soup.find_all(['div'], class_=re.compile(r'filter', re.I)):
                header = filter_section.find(['h4', 'h5', 'h6'])
                if header:
                    filter_name = header.get_text(strip=True).lower()
                    filters[filter_name] = []
                    
                    for option in filter_section.find_all(['button', 'a', 'span'], class_=re.compile(r'option|item', re.I)):
                        option_text = option.get_text(strip=True)
                        if option_text and len(option_text) < 30:
                            filters[filter_name].append(option_text)
                            
        except Exception as e:
            print(f"Error extracting filters: {e}")
            
        return filters
        
    def _extract_pricing(self, soup: BeautifulSoup) -> Dict:
        """Extract pricing information"""
        pricing = {}
        
        try:
            # Look for price information
            price_pattern = r'(\w+(?:\s+\w+)*)\s+\$(\d+(?:\.\d{2})?)'
            for text in soup.find_all(text=re.compile(price_pattern)):
                matches = re.findall(price_pattern, text)
                for card_name, price in matches:
                    pricing[card_name] = {
                        "price": float(price),
                        "vendor": "Unknown"  # Would need more parsing for vendor info
                    }
                    
        except Exception as e:
            print(f"Error extracting pricing: {e}")
            
        return pricing


# Helper functions
def extract_commander_tags(card_sections: Dict) -> List[Dict]:
    """Extract commander themes from high synergy cards"""
    tags = []
    
    high_synergy = card_sections.get("high_synergy", [])
    
    # Generate tags based on card patterns
    for card in high_synergy[:10]:
        card_name = card.get("card_name", "")
        
        # Simple tag extraction based on card names
        if "mana" in card_name.lower() or "land" in card_name.lower():
            tags.append({"tag": "Ramp/Mana", "percentage": card.get("inclusion_percentage", 0), "synergy_score": card.get("synergy_score", 0)})
        elif any(word in card_name.lower() for word in ["counter", "proliferate"]):
            tags.append({"tag": "Counter Strategy", "percentage": card.get("inclusion_percentage", 0), "synergy_score": card.get("synergy_score", 0)})
        elif "token" in card_name.lower():
            tags.append({"tag": "Token Strategy", "percentage": card.get("inclusion_percentage", 0), "synergy_score": card.get("synergy_score", 0)})
            
    return tags[:6]  # Top 6 tags

def process_card_data(card_sections: Dict, sections: str) -> List[Dict]:
    """Process card data for API response"""
    cards = []
    
    section_list = sections.split(",") if sections != "all" else ["high_synergy", "top_cards", "creatures", "instants", "enchantments"]
    
    for section in section_list:
        if section in card_sections:
            for card in card_sections[section][:10]:  # Top 10 per section
                cards.append({
                    "card_name": card.get("card_name", ""),
                    "inclusion_percentage": card.get("inclusion_percentage", 0),
                    "synergy_percentage": card.get("synergy_score", 0),
                    "card_url": card.get("card_url", ""),
                    "category": section.replace("_", " "),
                    "decks_with_commander": card.get("decks_with_commander", 0),
                    "total_decks_for_card": card.get("total_decks_for_card", 0)
                })
                
    return cards[:50]  # Total 50 cards max

def generate_combo_analysis(commander_name: str, card_sections: Dict) -> List[Dict]:
    """Generate combo analysis from card data"""
    combos = []
    
    # Simple combo detection based on high synergy cards
    high_synergy = card_sections.get("high_synergy", [])
    
    # Look for power combos
    for i, card1 in enumerate(high_synergy[:5]):
        for j, card2 in enumerate(high_synergy[i+1:i+3], i+1):
            synergy = min(card1.get("synergy_score", 0), card2.get("synergy_score", 0))
            if synergy > 20:  # High synergy threshold
                combos.append({
                    "combo_name": f"{card1.get('card_name', '')} + {card2.get('card_name', '')}",
                    "cards": [card1.get("card_name", ""), card2.get("card_name", "")],
                    "synergy_rating": synergy,
                    "deck_count": min(card1.get("decks_with_commander", 0), card2.get("decks_with_commander", 0))
                })
                
    return combos[:5]  # Top 5 combos

def find_similar_commanders(card_sections: Dict) -> List[Dict]:
    """Find similar commanders (placeholder for EDHRec comparison)"""
    # This would integrate with EDHRec's commander similarity API
    # For now, return placeholder data
    return [
        {
            "commander_name": "Sample Similar Commander 1",
            "similarity_score": 75.3,
            "commander_url": "https://農村rec.com/commanders/sample-1"
        }
    ]


# Enhanced API with real EDHRec data
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Enhanced Commander API - EDHRec Parser", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

parser = EDHRecParser()

@app.get("/api/v1/commanders/summary")
async def get_commander_summary(
    name: str = Query(..., description="Commander name to search for"),
    mode: str = Query("standard", description="Response mode: 'standard' (full data) or 'compact' (minimal data)"),
    sections: str = Query("all", description="Card sections to include: high_synergy,top_cards,creatures,instants,etc.")
):
    """Enhanced commander summary with real EDHRec data"""
    
    try:
        # Parse EDHRec page
        raw_data = parser.parse_commander_page(name)
        
        if "error" in raw_data:
            return raw_data
            
        # If compact mode, return minimal data
        if mode == "compact":
            return {
                "commander_name": raw_data["commander_name"],
                "commander_url": raw_data["commander_url"],
                "commander_stats": raw_data.get("commander_stats", {}),
                "timestamp": raw_data["timestamp"]
            }
            
        # Standard mode: process and enhance data
        enhanced_data = {
            "commander_name": raw_data["commander_name"],
            "commander_url": raw_data["commander_url"],
            "timestamp": raw_data["timestamp"],
            "commander_stats": raw_data.get("commander_stats", {}),
            
            # Extract commander tags from high synergy and top cards
            "commander_tags": extract_commander_tags(raw_data.get("card_sections", {})),
            
            # Process cards with real EDHRec data
            "card_inclusions": process_card_data(raw_data.get("card_sections", {}), sections),
            
            # Generate combo analysis (placeholder for Commander Spellbook integration)
            "combos": generate_combo_analysis(name, raw_data.get("card_sections", {})),
            
            # Similar commanders (would need EDHRec comparison API)
            "similar_commanders": find_similar_commanders(raw_data.get("card_sections", {}))
        }
        
        return enhanced_data
        
    except Exception as e:
        return {"error": f"Internal server error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
