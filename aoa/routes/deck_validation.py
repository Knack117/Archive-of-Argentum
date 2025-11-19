"""Deck validation routes and validation logic."""
from collections import defaultdict
from datetime import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from bs4 import BeautifulSoup, Tag
from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException

from aoa.constants import (
    CARD_BRACKET_SUFFIX_RE,
    CARD_HASH_SUFFIX_RE,
    CARD_SET_SUFFIX_RE,
    EDHREC_BASE_URL,
    SALT_LABEL_RE,
)
from aoa.models import (
    BracketValidation,
    DeckCard,
    DeckValidationRequest,
    DeckValidationResponse,
)
from aoa.security import verify_api_key
from aoa.services.salt_cache import get_salt_cache, refresh_salt_cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["deck-validation"])

COMMANDER_BRACKETS = {
    "exhibition": {
        "level": 1,
        "name": "Exhibition",
        "expectations": {
            "focus": "Theme over power",
            "win_conditions": "Highly thematic or substandard",
            "gameplay": "At least 9 turns before win/loss",
            "complexity": "Opportunity to show off creations",
            "mindset": "Casual Mindset - Heavy Theme Focus"
        },
        "restrictions": {
            "game_changers": "NO Game Changers",
            "mass_land_denial": "NO Mass Land Denial", 
            "extra_turns": "NO Extra Turns",
            "combos": "NO 2-Card Combos (exceptions for highly thematic cards)"
        }
    },
    "core": {
        "level": 2,
        "name": "Core",
        "expectations": {
            "focus": "Mechanically focused with creativity and entertainment",
            "win_conditions": "Incremental, telegraphed, disruptible",
            "gameplay": "At least 8 turns before win/loss",
            "complexity": "Low pressure, proactive, considerate",
            "mindset": "Casual Mindset - Mechanical Focus"
        },
        "restrictions": {
            "game_changers": "NO Game Changers",
            "mass_land_denial": "NO Mass Land Denial",
            "extra_turns": "NO Chaining Extra Turns", 
            "combos": "NO 2-Card Combos"
        }
    },
    "upgraded": {
        "level": 3,
        "name": "Upgraded", 
        "expectations": {
            "focus": "Powered up with strong synergy and high card quality",
            "win_conditions": "Can be played from hand in one turn",
            "gameplay": "At least 6 turns before win/loss",
            "complexity": "Many proactive and reactive plays",
            "mindset": "Moving Towards Competitive - Synergy & Quality"
        },
        "restrictions": {
            "game_changers": "0-3 Game Changers",
            "mass_land_denial": "NO Mass Land Denial",
            "extra_turns": "NO Chaining Extra Turns",
            "combos": "NO 2-Card Combos (before turn 6)"
        }
    },
    "optimized": {
        "level": 4,
        "name": "Optimized",
        "expectations": {
            "focus": "Lethal, consistent, fast - designed to take people down as fast as possible",
            "win_conditions": "Vary from archetype to archetype, can end game quickly and suddenly",
            "gameplay": "At least 4 turns before win/loss",
            "complexity": "Explosive and powerful, huge threats and efficient disruption",
            "mindset": "Competitive Mindset - Speed & Lethality (not cEDH metagame)"
        },
        "restrictions": {
            "game_changers": "NO DECK RESTRICTIONS",
            "mass_land_denial": "NO DECK RESTRICTIONS",
            "extra_turns": "NO DECK RESTRICTIONS",
            "combos": "NO DECK RESTRICTIONS"
        }
    },
    "cedh": {
        "level": 5,
        "name": "cEDH",
        "expectations": {
            "focus": "Meticulously designed to battle in the cEDH metagame",
            "win_conditions": "Optimized for efficiency and consistency",
            "gameplay": "Games could end on any turn",
            "complexity": "Intricate and advanced, razor-thin margins for error",
            "mindset": "Competitive Mindset - Metagame Mastery"
        },
        "restrictions": {
            "game_changers": "NO DECK RESTRICTIONS",
            "mass_land_denial": "NO DECK RESTRICTIONS",
            "extra_turns": "NO DECK RESTRICTIONS", 
            "combos": "NO DECK RESTRICTIONS"
        }
    }
}

# Game Changers list (October 2025 update)
GAME_CHANGERS = {
    "removed_2025": [
        "Expropriate", "Jin-Gitaxias, Core Augur", "Sway of the Stars", "Vorinclex, Voice of Hunger",
        "Kinnan, Bonder Prodigy", "Urza, Lord High Artificer", "Winota, Joiner of Forces", 
        "Yuriko, the Tiger's Shadow", "Deflecting Swat", "Food Chain"
    ],
    "current_list": [
        # High-impact cards that warp games
        "Ad Nauseam", "Demonic Consultation", "Thassa's Oracle", "Tainted Pact",
        "Exquisite Blood", "Sanguine Bond", "Consecrated Sphinx", "Coalition Victory",
        "Panoptic Mirror", "Time Walk", "Ancestral Recall", "Black Lotus",
        "Mox Sapphire", "Mox Jet", "Mox Pearl", "Mox Ruby", "Mox Emerald",
        "Fastbond", "Lion's Eye Diamond", "Mana Vault", "Sol Ring", "Mana Crypt",
        "Chrome Mox", "Mox Opal", "Lotus Petal", "Dark Ritual", "Cabal Ritual",
        "Necropotence", "Yawgmoth's Will", "Timetwister", "Wheel of Fortune",
        "Mystical Tutor", "Vampiric Tutor", "Demonic Tutor", "Imperial Seal",
        "Grim Tutor", "Beseech the Mirror", "Wish", "Cunning Wish", "Ritual Wish",
        "Biorhythm", "Enter the Infinite", "Laboratory Maniac", "Jace, Wielder of Mysteries",
        "Laboratory Maniac", "Neurok Transmuter", "Split Decision", "Brainstorm", "Ponder",
        "Preordain", "Spell Pierce", "Force of Will", "Force of Negation", "Mana Drain",
        "Counterspell", "Misdirection", "Pact of Negation", "Snapback", "Cyclonic Rift",
        "Vandalblast", "Armageddon", "Ravages of War", "Cataclysm", "Balance",
        "Life from the Loam", "The Tabernacle at Pendrell Vale", "Back to Basics",
        "Winter Orb", "Static Orb", "Tangle Wire", "Smokestack", "Crucible of Worlds",
        "Land Tax", "Scroll Rack", "Miren's Oracle Engine", "Sensei's Divining Top",
        "The One Ring", "Ring of Maiev", "Shaharazad", "Panoptic Mirror"
    ]
}

# Mass Land Denial cards curated from Commander resources
MASS_LAND_DENIAL = [
    "Acidic Slime", "Acid Rain", "Aloe Alchemist", "Arboreal Grazer", "Avenger of Zendikar",
    "Bane of Progress", "Bojuka Bog", "Brago's Representative", "Brago, King Eternal",
    "Casualties of War", "City of Brass", "Crystal Vein", "Dampening Wave", "Deserted Temple",
    "Destroy All Artifacts", "Dust Bowl", "Elixir of Immortality", "Ezuri, Renegade Leader",
    "Fierce Guardianship", "Force of Vigor", "From the Dust", "Gaea's Cradle", "Glacial Chasm",
    "Grazing Gladehart", "Hallowed Fountain", "Harmonic Sliver", "Heartbeat of Spring",
    "Hurricane", "Krosan Grip", "Living Plane", "Lotus Field", "Mana Confluence",
    "Manifold Insights", "Maze of Ith", "Mishra's Factory", "Mycosynth Lattice", "Necromentia",
    "Omen of the Sea", "Overgrown Estate", "Path to Exile", "Perplexing Chimera", "Pithing Needle",
    "Polymorphist's Jest", "Ponder", "Primal Command", "Prophet of Kruphix", "Rite of the Raging Storm",
    "Sea Gate Restoration", "Shatterstorm", "Silence", "Sol Ring", "Stifle", "Summer Bloom",
    "Survival of the Fittest", "Swords to Plowshares", "Swiftfoot Boots", "Telepathy",
    "Terror of the Peaks", "The Great Aurora", "Thran Quarry", "Timetwister", "Trickery Charm",
    "Ulcerate", "Unravel the Aether", "Vandalblast", "Venser, the Soaring Blade",
    "Vesuva", "Vinethorn Gatherer", "Volrath's Laboratory", "Walking Ballista", "White Sun's Zenith",
    "Winter Orb", "World Breaker", "Zuran Orb"
]

# Early game 2-card combos from EDHRec
EARLY_GAME_COMBOS = [
    {
        "cards": ["Demonic Consultation", "Thassa's Oracle"],
        "effects": ["Exile your library", "Win the game"],
        "brackets": ["1", "2", "3", "4", "5"]
    },
    {
        "cards": ["Exquisite Blood", "Sanguine Bond"],
        "effects": ["Infinite lifegain triggers", "Infinite lifeloss", "Infinite lifegain"],
        "brackets": ["1", "2", "3", "4", "5"]
    },
    {
        "cards": ["Tainted Pact", "Thassa's Oracle"],
        "effects": ["Win the game"],
        "brackets": ["1", "2", "3", "4", "5"]
    }
]


# Cards that are allowed to break the traditional singleton rule.
# Includes all basic lands, their snow-covered variants, and cards that
# explicitly allow any number of copies in a deck under Commander rules.
UNLIMITED_DUPLICATE_CARDS = {
    # Basic lands
    "plains",
    "island",
    "swamp",
    "mountain",
    "forest",
    "wastes",
    # Snow-covered basics
    "snow-covered plains",
    "snow-covered island",
    "snow-covered swamp",
    "snow-covered mountain",
    "snow-covered forest",
    "snow-covered wastes",
    # Non-basic cards with explicit rules text
    "relentless rats",
    "shadowborn apostle",
    "rat colony",
    "dragon's approach",
    "persistent petitioners",
    "seven dwarves",
}


# Extra Turn cards from Scryfall's oracle tag - fallback list if API is unavailable
EXTRA_TURN_CARDS_FALLBACK = [
    "A-Alrund's Epiphany", "Alchemist's Gambit", "Alrund's Epiphany", "Beacon of Tomorrows", 
    "Capture of Jingzhou", "Chance for Glory", "Emrakul, the Aeons Torn", "Emrakul, the Promised End",
    "Eon Frolicker", "Expropriate", "Final Fortune", "Gonti's Aether Heart", "Ichormoon Gauntlet",
    "Karn's Temporal Sundering", "Last Chance", "Lighthouse Chronologist", "Lost Isle Calling",
    "Magistrate's Scepter", "Magosi, the Waterveil", "Medomai the Ageless", "Mu Yanling",
    "Nexus of Fate", "Notorious Throng", "Part the Waterveil", "Phone a Friend", "Piece It Together",
    "Plea for Power", "Ral Zarek", "Regenerations Restored", "Rise of the Eldrazi", "Sage of Hours",
    "Savor the Moment", "Search the City", "Second Chance", "Seedtime", "Stitch in Time",
    "Teferi, Master of Time", "Teferi, Timebender", "Temporal Extortion", "Temporal Manipulation",
    "Temporal Mastery", "Temporal Trespass", "The Legend of Kuruk // Avatar Kuruk", "Time Sieve",
    "Timesifter", "Timestream Navigator", "Time Stretch", "Time Vault", "Time Walk", "Time Warp",
    "Twice Upon a Time // Unlikely Meeting", "Ugin's Nexus", "Ultimecia, Time Sorceress // Ultimecia, Omnipotent",
    "Walk the Aeons", "Wanderwine Prophets", "Warrior's Oath", "Wormfang Manta"
]


class DeckValidator:
    """Main deck validation class"""
    
    def __init__(self):
        self.cache = TTLCache(maxsize=1000, ttl=3600)  # 1 hour cache

    @staticmethod
    def build_request_signature(request: DeckValidationRequest) -> str:
        """Create a stable signature for caching deck validation results."""
        parts: List[str] = []

        if request.decklist:
            parts.extend(request.decklist)
        if request.decklist_text:
            parts.append(request.decklist_text)
        if request.decklist_chunks:
            parts.extend(request.decklist_chunks)

        parts.append(request.commander or "")
        parts.append(request.target_bracket or "")

        signature_source = "||".join(parts)
        return str(hash(signature_source))

    async def _get_extra_turn_cards(self) -> Dict[str, str]:
        """
        Fetch extra turn cards from Scryfall API using oracle tag.
        Returns dict mapping card names to Scryfall URLs.
        Falls back to hard-set list if API fails.
        """
        cache_key = "extra_turn_cards"
        
        # Check cache first
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            # Query Scryfall API for extra turn cards using oracle tag
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://api.scryfall.com/cards/search",
                    params={"q": "oracletag:extra-turn", "format": "json"}
                )
                response.raise_for_status()
                data = response.json()
                
                extra_turn_cards = {}
                if "data" in data:
                    for card in data["data"]:
                        card_name = card.get("name", "").strip()
                        scryfall_url = card.get("scryfall_uri", "")
                        if card_name and scryfall_url:
                            extra_turn_cards[card_name] = scryfall_url
                
                # Cache the results
                self.cache[cache_key] = extra_turn_cards
                logger.info(f"Fetched {len(extra_turn_cards)} extra turn cards from Scryfall API")
                return extra_turn_cards
                
        except Exception as e:
            logger.warning(f"Failed to fetch extra turn cards from Scryfall API: {e}. Using fallback list.")
            # Fall back to hard-set list
            extra_turn_cards = {}
            for card_name in EXTRA_TURN_CARDS_FALLBACK:
                # Generate a Scryfall search URL for each card
                search_query = card_name.replace(" ", "%20").replace("//", "%2F%2F")
                scryfall_url = f"https://scryfall.com/search?q=name%3A%22{search_query}%22"
                extra_turn_cards[card_name] = scryfall_url
            
            # Cache the fallback results too
            self.cache[cache_key] = extra_turn_cards
            logger.info(f"Using fallback list with {len(extra_turn_cards)} extra turn cards")
            return extra_turn_cards

    async def validate_deck(self, request: DeckValidationRequest) -> DeckValidationResponse:
        """Main validation method"""
        try:
            deck_entries = self._resolve_decklist_entries(request)
            # Parse and normalize decklist
            cards = await self._build_deck_cards(deck_entries)

            illegal_duplicates = self._find_illegal_duplicates(cards)

            # Load data for salt scoring
            data = await self._load_authoritative_data()
            
            # Get commander salt score
            commander_salt_score = await self._get_commander_salt_score(request.commander) if request.commander else 0.0
            
            # Calculate deck salt score using cache service
            salt_cache = get_salt_cache()
            await salt_cache.ensure_loaded()
            
            card_names = [card.name for card in cards for _ in range(card.quantity)]
            salt_result = salt_cache.calculate_deck_salt(card_names)
            
            # Use average salt score (per card) instead of total for proper scaling
            deck_salt_score = salt_result['average_salt']
            
            # Calculate combined salt score (weighted average)
            combined_salt_score = round((commander_salt_score + deck_salt_score) / 2, 2)
            
            # Build salt scores summary
            salt_scores = {
                "commander_salt_score": commander_salt_score,
                "deck_salt_score": deck_salt_score,
                "combined_salt_score": combined_salt_score,
                "salt_tier": salt_result['salt_tier'],
                "commander_salt_description": self._get_salt_level_description(commander_salt_score),
                "deck_salt_description": self._get_salt_level_description(deck_salt_score),
                "combined_salt_description": self._get_salt_level_description(combined_salt_score),
                "salt_level": salt_result['salt_tier'],  # Use actual tier from calculation
                "top_offenders": salt_result['top_offenders'],
                "salty_card_count": salt_result['salty_card_count'],
                "average_salt_per_card": salt_result['average_salt']
            }
            
            # Validate legality
            legality_results = {}
            if request.validate_legality:
                legality_results = await self._validate_legality(
                    cards, request.commander, duplicate_cards=illegal_duplicates
                )
            
            # Validate bracket
            bracket_validation = None
            bracket_inferred = False
            if request.validate_bracket:
                # If no target bracket specified, automatically infer the appropriate bracket
                if request.target_bracket:
                    target_bracket = request.target_bracket
                else:
                    target_bracket = await self._infer_bracket(cards)
                    bracket_inferred = True
                bracket_validation = await self._validate_bracket(cards, target_bracket, bracket_inferred)
            
            # Create response
            return DeckValidationResponse(
                success=True,
                deck_summary={
                    "total_cards": self._calculate_total_card_count(cards),
                    "commander": request.commander,
                    "target_bracket": request.target_bracket,
                    "has_duplicates": bool(illegal_duplicates),
                    "illegal_duplicates": illegal_duplicates,
                },
                cards=cards,
                bracket_validation=bracket_validation,
                legality_validation=legality_results,
                validation_timestamp=datetime.utcnow().isoformat(),
                errors=[],
                warnings=[],
                salt_scores=salt_scores
            )
            
        except Exception as exc:
            logger.error(f"Error validating deck: {exc}")
            return DeckValidationResponse(
                success=False,
                deck_summary={},
                cards=[],
                bracket_validation=None,
                legality_validation={},
                validation_timestamp=datetime.utcnow().isoformat(),
                errors=[str(exc)],
                warnings=[],
                salt_scores={}
            )
    
    def _resolve_decklist_entries(self, request: DeckValidationRequest) -> List[str]:
        """Combine decklist inputs (list, text blob, chunks, URL) into a normalized list."""
        entries: List[str] = []

        if request.decklist:
            entries.extend([line.strip() for line in request.decklist if line and line.strip()])

        if request.decklist_text:
            entries.extend(self._parse_decklist_block(request.decklist_text))

        if request.decklist_chunks:
            for chunk in request.decklist_chunks:
                entries.extend(self._parse_decklist_block(chunk))

        if request.decklist_url:
            url_entries = self._extract_decklist_from_url(request.decklist_url)
            entries.extend(url_entries)

        entries = [line for line in entries if line]

        if not entries:
            raise ValueError("Decklist cannot be empty after processing input.")

        return entries

    def _extract_decklist_from_url(self, deck_url: str) -> List[str]:
        """
        Extract decklist from supported platform URLs (Moxfield, Archidekt).
        
        Args:
            deck_url: URL to a deck on a supported platform
            
        Returns:
            List of decklist entries
            
        Raises:
            ValueError: If URL is not supported or extraction fails
        """
        import httpx
        import mtg_parser
        import os
        
        # Detect platform
        deck_url = deck_url.strip()
        if not deck_url.startswith(('http://', 'https://')):
            raise ValueError("URL must start with http:// or https://")
        
        if 'moxfield.com/decks/' in deck_url.lower():
            return self._extract_from_moxfield(deck_url)
        elif 'archidekt.com/decks/' in deck_url.lower():
            return self._extract_from_archidekt(deck_url)
        else:
            supported_platforms = ["moxfield.com", "archidekt.com"]
            raise ValueError(f"URL must be from a supported platform: {', '.join(supported_platforms)}")

    def _extract_from_moxfield(self, deck_url: str) -> List[str]:
        """Extract decklist from Moxfield URL."""
        import httpx
        import mtg_parser
        import os
        
        # Moxfield requires custom User-Agent to be respectful
        # Set a generic user agent for the library
        custom_headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; MagicDeckValidator/1.0; +https://github.com/magic/deck-validator)'
        }
        
        try:
            with httpx.Client(headers=custom_headers, timeout=30.0) as http_client:
                cards = mtg_parser.parse_deck(deck_url, http_client)
                # Convert generator to list since mtg_parser returns a generator
                cards = list(cards)
                
            if not cards:
                raise ValueError("No cards found in the Moxfield deck")
                
            # Convert Card objects to list format
            decklist_entries = []
            for card in cards:
                if card.quantity and card.quantity > 0:
                    if card.quantity == 1:
                        decklist_entries.append(card.name)
                    else:
                        decklist_entries.append(f"{card.quantity} {card.name}")
            
            logger.info(f"Successfully extracted {len(decklist_entries)} cards from Moxfield deck: {deck_url}")
            return decklist_entries
            
        except Exception as exc:
            logger.error(f"Failed to extract deck from Moxfield {deck_url}: {exc}")
            raise ValueError(f"Failed to extract decklist from Moxfield URL: {str(exc)}")

    def _extract_from_archidekt(self, deck_url: str) -> List[str]:
        """Extract decklist from Archidekt URL."""
        import mtg_parser
        
        # Archidekt requires custom User-Agent to be respectful
        custom_headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; MagicDeckValidator/1.0; +https://github.com/magic/deck-validator)'
        }
        
        try:
            with httpx.Client(headers=custom_headers, timeout=30.0) as http_client:
                cards = mtg_parser.parse_deck(deck_url, http_client)
                # Convert generator to list since mtg_parser returns a generator
                cards = list(cards)
            
            if not cards:
                raise ValueError("No cards found in the Archidekt deck")
                
            # Convert Card objects to list format
            decklist_entries = []
            for card in cards:
                if card.quantity and card.quantity > 0:
                    if card.quantity == 1:
                        decklist_entries.append(card.name)
                    else:
                        decklist_entries.append(f"{card.quantity} {card.name}")
            
            logger.info(f"Successfully extracted {len(decklist_entries)} cards from Archidekt deck: {deck_url}")
            return decklist_entries
            
        except Exception as exc:
            logger.error(f"Failed to extract deck from Archidekt {deck_url}: {exc}")
            raise ValueError(f"Failed to extract decklist from Archidekt URL: {str(exc)}")

    def _parse_decklist_block(self, block: Optional[str]) -> List[str]:
        """Parse a block of text into decklist entries."""
        if not block:
            return []

        normalized = block.replace("\r", "\n")
        parsed: List[str] = []

        for raw_line in normalized.split("\n"):
            stripped = (raw_line or "").strip()
            if not stripped:
                continue

            # First try semicolon separation (only if semicolons actually exist)
            if ";" in stripped:
                segments = [segment.strip() for segment in stripped.split(";") if segment.strip()]
                if len(segments) > 1:  # Only if we found multiple segments
                    parsed.extend(segments)
                    continue

            # Check if this line contains potential deck entries
            # Look for "number + card name" patterns
            card_pattern_matches = len(re.findall(r'\d+\s*x?\s+[A-Za-z]', stripped))
            
            if card_pattern_matches > 0:
                # This line has card entries
                if card_pattern_matches == 1:
                    # Single card - append as-is
                    parsed.append(stripped)
                else:
                    # Multiple cards - use split function
                    cards = self._split_continuous_deck_text(stripped)
                    parsed.extend(cards)
            else:
                # No card patterns - might be text description
                parsed.append(stripped)

        return parsed
    
    def _split_continuous_deck_text(self, text: str) -> List[str]:
        """
        Split continuous deck text like '1 Card1 1 Card2 1 Card3' into individual entries.
        
        Uses a greedy approach that finds all number+card patterns and extracts the full names.
        
        Args:
            text: Continuous text that may contain multiple card entries
            
        Returns:
            List of individual card entries
        """
        import re
        
        # Find all number+word patterns to locate card boundaries
        number_pattern = r'(\d+)\s*x?\s+([A-Za-z])'
        number_matches = list(re.finditer(number_pattern, text, re.IGNORECASE))
        
        if len(number_matches) <= 1:
            return [text]
        
        cards = []
        
        for i, match in enumerate(number_matches):
            quantity = match.group(1)
            start_pos = match.start(2)  # Start of card name
            
            # Find end position - either next number or end of text
            if i < len(number_matches) - 1:
                # End is just before the next quantity starts (group 1, not group 2)
                end_pos = number_matches[i + 1].start(1)  # Start of next quantity
            else:
                # Last card - go to end
                end_pos = len(text)
            
            # Extract card name
            card_name = text[start_pos:end_pos].strip()
            
            # Clean up: remove trailing punctuation and extra whitespace
            while card_name and card_name[-1] in '.,;:':
                card_name = card_name[:-1].strip()
            
            # Remove any trailing numbers that might be from incomplete parsing
            card_name = re.sub(r'\s*\d+\s*$', '', card_name).strip()
            
            if card_name:
                cards.append(f"{quantity} {card_name}")
        
        return cards if len(cards) >= 2 else [text]

    async def _build_deck_cards(self, decklist: List[str]) -> List[DeckCard]:
        """Parse decklist and classify each card using authoritative scraped data."""
        data = await self._load_authoritative_data()
        cards: List[DeckCard] = []

        for line in decklist:
            line = line.strip()
            if not line:
                continue

            quantity = 1
            card_name = line

            match = re.match(r"^(\d+)\s*x?\s*(.+)$", line, re.IGNORECASE)
            if match:
                quantity = int(match.group(1))
                card_name = match.group(2).strip()

            card_name = self._normalize_card_name(card_name)

            card = await self._classify_card(card_name, quantity, data)
            cards.append(card)

        return cards

    def _normalize_card_name(self, card_name: str) -> str:
        """Strip common set/collector suffixes from exported decklists."""
        if not card_name:
            return ""

        cleaned = card_name.strip()

        # Remove Arena/exporter style "(SET) 123" suffixes first
        cleaned = CARD_SET_SUFFIX_RE.sub("", cleaned)
        # Remove bracketed set codes like "[BRO] #270"
        cleaned = CARD_BRACKET_SUFFIX_RE.sub("", cleaned)
        # Remove lingering "#123" style markers if present
        cleaned = CARD_HASH_SUFFIX_RE.sub("", cleaned)

        return cleaned.strip()

    
    async def _load_authoritative_data(self) -> Dict[str, Set[str]]:
        """Load authoritative bracket card lists and cache them."""
        if "authoritative_data" in self.cache:
            return self.cache["authoritative_data"]

        # Authoritative Game Changers list maintained from Wizards/RC guidance
        game_changers = {
            "Ad Nauseam", "Ancient Tomb", "Aura Shards", "Bolas's Citadel", 
            "Braids, Cabal Minion", "Chrome Mox", "Coalition Victory", 
            "Consecrated Sphinx", "Crop Rotation", "Cyclonic Rift", 
            "Demonic Tutor", "Drannith Magistrate", "Enlightened Tutor", 
            "Field of the Dead", "Fierce Guardianship", "Force of Will", 
            "Gaea's Cradle", "Gamble", "Gifts Ungiven", "Glacial Chasm", 
            "Grand Arbiter Augustin IV", "Grim Monolith", "Humility", 
            "Imperial Seal", "Intuition", "Jeska's Will", "Lion's Eye Diamond", 
            "Mana Vault", "Mishra's Workshop", "Mox Diamond", "Mystical Tutor", 
            "Narset, Parter of Veils", "Natural Order", "Necropotence", 
            "Notion Thief", "Opposition Agent", "Orcish Bowmasters", 
            "Panoptic Mirror", "Rhystic Study", "Seedborn Muse", "Serra's Sanctum", 
            "Smothering Tithe", "Survival of the Fittest", "Teferi's Protection", 
            "Tergrid, God of Fright // Tergrid's Lantern", "Tergrid, God of Fright",
            "Thassa's Oracle", "The One Ring", "The Tabernacle at Pendrell Vale", 
            "Underworld Breach", "Vampiric Tutor", "Worldly Tutor"
        }

        # Mass Land Denial list curated from Wizards/RC resources
        mass_land_denial = {
            "Acid Rain", "Apocalypse", "Armageddon", "Back to Basics", 
            "Bearer of the Heavens", "Bend or Break", "Blood Moon", "Boil", 
            "Boiling Seas", "Boom // Bust", "Break the Ice", "Burning of Xinye", 
            "Cataclysm", "Catastrophe", "Choke", "Cleansing", "Contamination", 
            "Conversion", "Curse of Marit Lage", "Death Cloud", 
            "Decree of Annihilation", "Desolation Angel", "Destructive Force", 
            "Devastating Dreams", "Devastation", "Dimensional Breach", 
            "Disciple of Caelus Nin", "Epicenter", "Fall of the Thran", 
            "Flashfires", "Gilt-Leaf Archdruid", "Glaciers", "Global Ruin", 
            "Hall of Gemstone", "Harbinger of the Seas", "Hokori, Dust Drinker", 
            "Impending Disaster", "Infernal Darkness", "Jokulhaups", 
            "Keldon Firebombers", "Land Equilibrium", "Magus of the Balance", 
            "Magus of the Moon", "Myojin of Infinite Rage", "Naked Singularity", 
            "Natural Balance", "Obliterate", "Omen of Fire", "Raiding Party", 
            "Ravages of War", "Razia's Purification", "Reality Twist", 
            "Realm Razer", "Restore Balance", "Rising Waters", "Ritual of Subdual", 
            "Ruination", "Soulscour", "Stasis", "Static Orb", "Storm Cauldron", 
            "Sunder", "Sway of the Stars", "Tectonic Break", "Thoughts of Ruin", 
            "Tsunami", "Wake of Destruction", "Wildfire", "Winter Moon", 
            "Winter Orb", "Worldfire", "Worldpurge", "Worldslayer"
        }

        # Early game 2-card combo pairs from EDHRec
        # Source: https://edhrec.com/combos/early-game-2-card-combos
        # Format: List of tuples (card1, card2) - both pieces must be present to flag as combo
        early_game_combo_pairs = [
            ("Demonic Consultation", "Thassa's Oracle"),
            ("Tainted Pact", "Thassa's Oracle"),
            ("Tainted Pact", "Laboratory Maniac"),
            ("Demonic Consultation", "Laboratory Maniac"),
            ("Exquisite Blood", "Sanguine Bond"),
            ("Exquisite Blood", "Vito, Thorn of the Dusk Rose"),
            ("Dramatic Reversal", "Isochron Scepter"),
            ("Dualcaster Mage", "Twinflame"),
            ("Dualcaster Mage", "Heat Shimmer"),
            ("Niv-Mizzet, Parun", "Curiosity"),
            ("Niv-Mizzet, Parun", "Ophidian Eye"),
            ("Niv-Mizzet, Parun", "Tandem Lookout"),
            ("Niv-Mizzet, the Firemind", "Curiosity"),
            ("Niv-Mizzet, the Firemind", "Ophidian Eye"),
            ("Niv-Mizzet, the Firemind", "Tandem Lookout"),
            ("Gravecrawler", "Phyrexian Altar"),
            ("Gravecrawler", "Pitiless Plunderer"),
            ("Exquisite Blood", "Bloodthirsty Conqueror"),
            ("Sanguine Bond", "Bloodthirsty Conqueror"),
            ("Chatterfang, Squirrel General", "Pitiless Plunderer"),
            ("Bloodchief Ascension", "Mindcrank"),
            ("Basalt Monolith", "Rings of Brighthearth"),
            ("Basalt Monolith", "Forsaken Monument"),
            ("Exquisite Blood", "Marauding Blight-Priest"),
            ("Heliod, Sun-Crowned", "Walking Ballista"),
            ("Maddening Cacophony", "Bruvac the Grandiloquent"),
            ("Maddening Cacophony", "Fraying Sanity"),
            ("Enduring Tenacity", "Peregrin Took"),
            ("Nuka-Cola Vending Machine", "Kinnan, Bonder Prodigy"),
            ("Dualcaster Mage", "Molten Duplication"),
            ("Felidar Guardian", "Restoration Angel"),
            ("Peregrine Drake", "Deadeye Navigator"),
            ("The Gitrog Monster", "Dakmor Salvage"),
            ("Squee, the Immortal", "Food Chain"),
            ("Eternal Scourge", "Food Chain"),
            ("Blasphemous Act", "Repercussion"),
            ("Experimental Confectioner", "The Reaver Cleaver"),
            ("Aggravated Assault", "Sword of Feast and Famine"),
            ("Aggravated Assault", "Bear Umbra"),
            ("Aggravated Assault", "Savage Ventmaw"),
            ("Aggravated Assault", "Neheb, the Eternal"),
            ("Kiki-Jiki, Mirror Breaker", "Zealous Conscripts"),
            ("Kiki-Jiki, Mirror Breaker", "Felidar Guardian"),
            ("Kiki-Jiki, Mirror Breaker", "Restoration Angel"),
            ("Kiki-Jiki, Mirror Breaker", "Village Bell-Ringer"),
            ("Kiki-Jiki, Mirror Breaker", "Combat Celebrant"),
            ("Staff of Domination", "Priest of Titania"),
            ("Staff of Domination", "Elvish Archdruid"),
            ("Staff of Domination", "Circle of Dreams Druid"),
            ("Staff of Domination", "Bloom Tender"),
            ("Umbral Mantle", "Priest of Titania"),
            ("Umbral Mantle", "Elvish Archdruid"),
            ("Umbral Mantle", "Circle of Dreams Druid"),
            ("Umbral Mantle", "Bloom Tender"),
            ("Umbral Mantle", "Selvala, Heart of the Wilds"),
            ("Dualcaster Mage", "Saw in Half"),
            ("Godo, Bandit Warlord", "Helm of the Host"),
            ("Scurry Oak", "Ivy Lane Denizen"),
            ("Ashaya, Soul of the Wild", "Quirion Ranger"),
            ("Ashaya, Soul of the Wild", "Scryb Ranger"),
            ("Marwyn, the Nurturer", "Umbral Mantle"),
            ("Malcolm, Keen-Eyed Navigator", "Glint-Horn Buccaneer"),
            ("Storm-Kiln Artist", "Haze of Rage"),
            ("Karn, the Great Creator", "Mycosynth Lattice"),
            ("Traumatize", "Maddening Cacophony"),
            ("Traumatize", "Bruvac the Grandiloquent"),
            ("Kaalia of the Vast", "Master of Cruelties"),
            ("Forensic Gadgeteer", "Toralf, God of Fury"),
            ("Professor Onyx", "Chain of Smog"),
            ("Witherbloom Apprentice", "Chain of Smog"),
            ("Solphim, Mayhem Dominus", "Heartless Hidetsugu"),
            ("Cut Your Losses", "Bruvac the Grandiloquent"),
            ("Starscape Cleric", "Peregrin Took"),
            ("Ondu Spiritdancer", "Secret Arcade"),
            ("Ondu Spiritdancer", "Dusty Parlor"),
            ("Vandalblast", "Toralf, God of Fury"),
            ("Nest of Scarabs", "Blowfly Infestation"),
            ("Duskmantle Guildmage", "Mindcrank"),
            ("Rosie Cotton of South Lane", "Peregrin Took"),
            ("Terisian Mindbreaker", "Maddening Cacophony"),
            ("Bloom Tender", "Freed from the Real"),
            ("Priest of Titania", "Freed from the Real"),
            ("Devoted Druid", "Swift Reconfiguration"),
            ("Basking Broodscale", "Ivy Lane Denizen"),
            ("Ratadrabik of Urborg", "Boromir, Warden of the Tower"),
            ("Dualcaster Mage", "Electroduplicate"),
            ("Abdel Adrian, Gorion's Ward", "Animate Dead"),
            ("Animate Dead", "Worldgorger Dragon"),
            ("Tivit, Seller of Secrets", "Time Sieve"),
            ("Satya, Aetherflux Genius", "Lightning Runner"),
            ("Ghostly Flicker", "Naru Meha, Master Wizard"),
            ("Ghostly Flicker", "Dualcaster Mage"),
            ("Vizkopa Guildmage", "Exquisite Blood"),
            ("Doomsday", "Thassa's Oracle"),
            ("Doomsday", "Laboratory Maniac"),
            ("Heliod, Sun-Crowned", "Triskelion"),
            ("Grindstone", "Painter's Servant"),
            ("Splinter Twin", "Pestermite"),
            ("Splinter Twin", "Deceiver Exarch")
        ]

        # Load salt scores from cache (fast, comprehensive)
        salt_cache = get_salt_cache()
        await salt_cache.ensure_loaded()
        salt_cards = salt_cache.get_all_salt_scores()
        
        if not salt_cards:
            logger.warning("Salt cache empty, using fallback scores")
            salt_cards = self._get_fallback_salt_scores()

        # Load tutor cards from Scryfall API
        tutor_cards = await self._load_tutor_cards()

        data = {
            "mass_land_denial": mass_land_denial,
            "early_game_combo_pairs": early_game_combo_pairs,
            "game_changers": game_changers,
            "tutors": tutor_cards,
            "salt_cards": salt_cards,
        }

        self.cache["authoritative_data"] = data
        return data

    async def _scrape_edhrec_salt_scores(self) -> Dict[str, float]:
        """Scrape salt scores from EDHRec via HTTP with a fallback table."""
        salt_cards = await self._scrape_salt_scores_via_http()
        if salt_cards:
            return salt_cards

        logger.warning("Unable to scrape salt scores, using fallback table")
        return self._get_fallback_salt_scores()

    async def _scrape_salt_scores_via_http(self) -> Dict[str, float]:
        """Fallback HTTP scraping method that parses the static HTML."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        salt_url = "https://edhrec.com/top/salt"

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                trust_env=False,
            ) as client:
                response = await client.get(salt_url, headers=headers)
                response.raise_for_status()

                html_content = response.text
                soup = BeautifulSoup(html_content, "html.parser")

                # Extract salt scores from the HTML using the correct JSON structure
                salt_data = self._extract_salt_scores_from_html(soup)

                if not salt_data:
                    salt_data = self._parse_salt_scores_from_dom(html_content)

                if salt_data:
                    logger.info(f"Scraped {len(salt_data)} salt scores from EDHRec HTML page")
                return salt_data

        except Exception as exc:
            logger.error(f"Error scraping salt scores: {exc}")
            return {}

    def _extract_salt_scores_from_json(self, payload: Dict[str, Any]) -> Dict[str, float]:
        """Extract salt scores from cached JSON payloads for testability."""
        if not payload:
            return {}

        if "props" in payload:
            result = self._extract_salt_scores_from_next_data(payload)
            if result:
                return result

        if "pageProps" in payload:
            result = self._extract_salt_scores_from_next_data({"props": payload})
            if result:
                return result

        return self._extract_salt_scores_alternative_method(payload)

    def _parse_salt_scores_from_dom(self, html_content: str) -> Dict[str, float]:
        """Parse salt scores from rendered HTML when JSON extraction fails."""
        if not html_content:
            return {}

        soup = BeautifulSoup(html_content, "html.parser")
        salt_data = self._extract_salt_scores_from_html(soup)
        if salt_data:
            return salt_data

        parsed_scores: Dict[str, float] = {}
        salt_labels = soup.find_all(string=SALT_LABEL_RE)

        for label in salt_labels:
            match = SALT_LABEL_RE.search(label)
            if not match:
                continue

            try:
                salt_score = float(match.group(1))
            except ValueError:
                continue

            container = label.parent
            steps = 0
            card_name = ""

            while container is not None and steps < 6 and not card_name:
                card_name = self._extract_card_name_from_node(container)
                container = container.parent if hasattr(container, "parent") else None
                steps += 1

            if card_name and 0 <= salt_score <= 5:
                parsed_scores[card_name] = salt_score

        return parsed_scores

    def _extract_card_name_from_node(self, node: Any) -> str:
        """Best-effort extraction of a card name from a DOM node."""
        if not isinstance(node, Tag):
            return ""

        attr_name = node.get("data-card-name") or node.get("data-name")
        if isinstance(attr_name, str) and attr_name.strip():
            return attr_name.strip()

        selectors = [
            "[data-card-name]",
            ".card-name",
            ".card__name",
            ".name",
            "a.card",
            "a[href*='/cards/']",
            "a[href*='/commanders/']",
            "a",
            "strong",
            "h3",
            "h4",
            "span",
        ]

        for selector in selectors:
            target = node.select_one(selector)
            if target and target.get_text(strip=True):
                text = target.get_text(strip=True)
                if text and not text.lower().startswith("salt score"):
                    return text

        text_content = node.get_text(" ", strip=True)
        if "Salt Score" in text_content:
            text_content = text_content.split("Salt Score")[0].strip(" -:\n")
        return text_content

    def _extract_salt_score_from_card(self, card_data: Dict[str, Any]) -> Optional[float]:
        """Normalize a salt score from a single card record."""
        if not isinstance(card_data, dict):
            return None

        salt_score = card_data.get("salt")
        if isinstance(salt_score, str):
            try:
                salt_score = float(salt_score)
            except ValueError:
                salt_score = None
        elif isinstance(salt_score, (int, float)):
            salt_score = float(salt_score)

        if salt_score is None:
            label_text = card_data.get("label") or ""
            match = SALT_LABEL_RE.search(label_text)
            if match:
                try:
                    salt_score = float(match.group(1))
                except ValueError:
                    salt_score = None

        if salt_score is None:
            synergy = card_data.get("synergy")
            if isinstance(synergy, (int, float)) and 0 <= synergy <= 5:
                salt_score = float(synergy)

        if salt_score is None:
            scores = card_data.get("scores") or {}
            if isinstance(scores, dict):
                embedded = scores.get("salt")
                if isinstance(embedded, (int, float)):
                    salt_score = float(embedded)

        if salt_score is None:
            stats = card_data.get("stats") or {}
            if isinstance(stats, dict):
                embedded = stats.get("salt")
                if isinstance(embedded, (int, float)):
                    salt_score = float(embedded)

        if salt_score is None:
            return None

        if 0 <= salt_score <= 5:
            return float(salt_score)
        return None

    def _extract_salt_scores_from_html(self, soup: BeautifulSoup) -> Dict[str, float]:
        """Extract salt scores from HTML structure using the correct JSON parsing"""
        salt_data = {}
        
        # Look for the main JSON data in the __NEXT_DATA__ script
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag and script_tag.string:
            try:
                data = json.loads(script_tag.string)
                salt_data = self._extract_salt_scores_from_next_data(data)
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Error parsing __NEXT_DATA__: {e}")
        
        return salt_data

    def _extract_salt_scores_from_next_data(self, data: Dict[str, Any]) -> Dict[str, float]:
        """Extract salt scores from the Next.js data structure"""
        salt_data = {}
        
        try:
            # Navigate through the nested structure to find card data
            page_props = data.get("props", {}).get("pageProps", {})
            page_data = page_props.get("data", {})
            container = page_data.get("container", {})
            json_dict = container.get("json_dict", {})
            cardlists = json_dict.get("cardlists", [])
            
            # Look through all cardlists for salt score data
            for cardlist in cardlists:
                if not isinstance(cardlist, dict):
                    continue
                    
                cardviews = cardlist.get("cardviews", [])
                for card_data in cardviews:
                    if not isinstance(card_data, dict):
                        continue

                    # Extract card name and salt score
                    card_name = card_data.get("name", "").strip()
                    if not card_name:
                        continue

                    salt_score = self._extract_salt_score_from_card(card_data)
                    if salt_score is not None:
                        salt_data[card_name] = salt_score
            
            # Alternative approach: Look for the specific salt score cardlist
            if not salt_data:
                salt_data = self._extract_salt_scores_alternative_method(data)
                
        except Exception as e:
            logger.error(f"Error extracting salt scores from Next data: {e}")
        
        return salt_data

    def _extract_salt_scores_alternative_method(self, data: Dict[str, Any]) -> Dict[str, float]:
        """Alternative method to extract salt scores if primary method fails"""
        salt_data = {}
        
        try:
            # Sometimes the data is in a different structure
            # Look for any array that contains card objects with salt scores
            def search_for_salt_scores(obj, path=""):
                if isinstance(obj, dict):
                    if "name" in obj or "card" in obj:
                        card_name = obj.get("name", "").strip()
                        if not card_name:
                            nested_card = obj.get("card")
                            if isinstance(nested_card, dict):
                                card_name = (nested_card.get("name") or "").strip()
                        salt_score = self._extract_salt_score_from_card(obj)
                        if card_name and salt_score is not None:
                            salt_data[card_name] = salt_score

                    # Recursively search nested objects
                    for key, value in obj.items():
                        search_for_salt_scores(value, f"{path}.{key}")
                        
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        search_for_salt_scores(item, f"{path}[{i}]")
            
            # Start search from the root of the data
            search_for_salt_scores(data)
            
        except Exception as e:
            logger.error(f"Error in alternative salt score extraction: {e}")
        
        return salt_data

    def _get_fallback_salt_scores(self) -> Dict[str, float]:
        """
        Fallback salt scores for when scraping fails.
        This should match the data we can see on https://edhrec.com/top/salt
        """
        return {
            "Stasis": 3.06,
            "Winter Orb": 2.96, 
            "Vivi Ornitier": 2.81,
            "Tergrid, God of Fright": 2.80,
            "Rhystic Study": 2.73,
            "The Tabernacle at Pendrell Vale": 2.68,
            "Armageddon": 2.67,
            "Static Orb": 2.62,
            "Vorinclex, Voice of Hunger": 2.61,
            "Thassa's Oracle": 2.59,
            "Grand Arbiter Augustin IV": 2.58,
            "Smothering Tithe": 2.58,
            "Jin-Gitaxias, Core Augur": 2.57,
            "The One Ring": 2.55,
            "Humility": 2.51,
            "Drannith Magistrate": 2.46,
            "Expropriate": 2.45,
            "Sunder": 2.44,
            "Obliterate": 2.42,
            "Devastation": 2.41,
            "Ravages of War": 2.39,
            "Cyclonic Rift": 2.36,
            "Jokulhaups": 2.36,
            "Apocalypse": 2.34,
            "Opposition Agent": 2.32,
            "Urza, Lord High Artificer": 2.31,
            "Fierce Guardianship": 2.30,
            "Hokori, Dust Drinker": 2.27,
            "Back to Basics": 2.23,
            "Nether Void": 2.23,
            "Jin-Gitaxias, Progress Tyrant": 2.22,
            "Braids, Cabal Minion": 2.21,
            "Worldfire": 2.20,
            "Toxrill, the Corrosive": 2.19,
            "Aura Shards": 2.18,
            "Gaea's Cradle": 2.17,
            "Kinnan, Bonder Prodigy": 2.15,
            "Yuriko, the Tiger's Shadow": 2.15,
            "Teferi's Protection": 2.13,
            "Blood Moon": 2.13,
            "Farewell": 2.13,
            "Rising Waters": 2.11,
            "Decree of Annihilation": 2.10,
            "Winter Moon": 2.08,
            "Smokestack": 2.08,
            "Orcish Bowmasters": 2.07,
            "Tectonic Break": 2.05,
            "Edgar Markov": 2.05,
            "Sen Triplets": 2.04,
            "Warp World": 2.04,
            "Sheoldred, the Apocalypse": 2.03,
            "Emrakul, the Promised End": 2.03,
            "Scrambleverse": 2.02,
            "Thieves' Auction": 2.02,
            "Force of Will": 2.01,
            "Narset, Parter of Veils": 2.01
        }

    async def _classify_card(self, card_name: str, quantity: int, data: Dict[str, Set[str]]) -> DeckCard:
        """Classify a single card using authoritative scraped lists."""
        categories = []
        is_game_changer = False

        if card_name in data["mass_land_denial"]:
            categories.append("mass_land_denial")
        if card_name in data["game_changers"]:
            categories.append("game_changer")
            is_game_changer = True
        if card_name in data["tutors"]:
            categories.append("tutor")

        return DeckCard(
            name=card_name,
            quantity=quantity,
            is_game_changer=is_game_changer,
            bracket_categories=categories,
            legality_status="pending"
        )
    
    def _detect_combos(self, cards: List[DeckCard], combo_pairs: List[tuple]) -> List[tuple]:
        """
        Detect complete 2-card combos in the deck.
        Returns list of combo pairs found where BOTH pieces are present.
        """
        card_names = {card.name for card in cards}
        detected_combos = []
        
        for card1, card2 in combo_pairs:
            if card1 in card_names and card2 in card_names:
                detected_combos.append((card1, card2))
        
        return detected_combos
    
    async def _validate_legality(
        self,
        cards: List[DeckCard],
        commander: Optional[str],
        duplicate_cards: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Validate commander format legality"""
        legality_issues = []
        warnings = []

        if duplicate_cards is None:
            duplicate_cards = self._find_illegal_duplicates(cards)

        # Basic commander format rules
        if commander:
            # Commander color identity check would go here
            # For now, just basic validation

            total_main_deck = self._calculate_total_card_count(cards)
            commander_present = any(card.name.lower() == commander.lower() for card in cards)
            total_with_commander = total_main_deck + (0 if commander_present else 1)

            if total_with_commander != 100:
                legality_issues.append(
                    "Deck must have exactly 99 cards plus 1 commander (total 100 cards, "
                    f"detected {total_main_deck} non-commander cards and "
                    f"{'includes' if commander_present else 'excludes'} the commander)."
                )

        if duplicate_cards:
            duplicate_list = ", ".join(
                f"{name} x{count}" for name, count in sorted(duplicate_cards.items())
            )
            legality_issues.append(
                "Commander is a singleton format. Only basic lands and a handful of cards "
                "that explicitly break this rule can appear more than once. Duplicate cards "
                f"detected: {duplicate_list}."
            )

        # Check for banned cards (placeholder - would need comprehensive banlist)
        banned_cards = ["Ancestral Recall", "Black Lotus", "Time Walk", "Mox Sapphire", "Mox Jet", "Mox Pearl", "Mox Ruby", "Mox Emerald"]
        for card in cards:
            if card.name in banned_cards:
                legality_issues.append(f"Card '{card.name}' is banned in Commander")

        return {
            "is_legal": len(legality_issues) == 0,
            "issues": legality_issues,
            "warnings": warnings,
            "illegal_duplicates": duplicate_cards,
        }
    
    async def _infer_bracket(self, cards: List[DeckCard]) -> str:
        """
        Automatically infer the appropriate bracket for a deck based on its characteristics.
        Returns the bracket name that best matches the deck's power level and cards.
        """
        # Count relevant characteristics
        game_changer_count = sum(1 for card in cards if card.is_game_changer)
        combo_pairs = [
            ("Demonic Consultation", "Thassa's Oracle"),
            ("Tainted Pact", "Thassa's Oracle"),
            ("Tainted Pact", "Laboratory Maniac"),
            ("Demonic Consultation", "Laboratory Maniac"),
            ("Exquisite Blood", "Sanguine Bond"),
            ("Dramatic Reversal", "Isochron Scepter"),
            ("Dualcaster Mage", "Twinflame"),
            ("Heliod, Sun-Crowned", "Walking Ballista")
        ]
        card_names = {card.name for card in cards}
        combo_count = sum(1 for card1, card2 in combo_pairs if card1 in card_names and card2 in card_names)
        mass_land_count = sum(1 for card in cards if "mass_land_denial" in card.bracket_categories)
        tutor_count = sum(1 for card in cards if "tutor" in card.bracket_categories)
        
        # Calculate cEDH score for advanced detection
        cedh_score = self._calculate_cedh_score(cards, combo_count, game_changer_count, mass_land_count)
        
        # Strict hierarchy based on Commander Brackets definition
        
        # cEDH: Must have metagame characteristics and high power
        if (combo_count >= 2 and game_changer_count >= 5) or cedh_score >= 30:
            return "cedh"
        
        # Optimized: High power but not necessarily meta-tuned
        # Key: Fast, consistent, efficient but not cEDH-level
        elif (game_changer_count >= 4 or 
              (combo_count >= 1 and game_changer_count >= 2) or
              cedh_score >= 20):
            return "optimized"
        
        # Upgraded: Moderate power with synergy
        # Key: Some game changers, good tutors, but still moderate
        elif (game_changer_count >= 1 or 
              tutor_count >= 4 or 
              cedh_score >= 10):
            return "upgraded"
        
        # Core: Mechanically focused but not optimized
        # Key: Few/no game changers, minimal tutors, structured gameplay
        elif (game_changer_count == 0 and 
              mass_land_count == 0 and 
              combo_count == 0 and
              tutor_count <= 3):
            return "core"
        
        # Exhibition: Theme-focused, very restrictive
        # Key: Heavily theme-based, minimal power cards
        elif (game_changer_count == 0 and
              mass_land_count == 0 and
              combo_count == 0 and
              tutor_count <= 2):
            return "exhibition"
        
        # Fallback based on available indicators
        else:
            if game_changer_count > 0:
                return "upgraded"
            elif tutor_count > 3:
                return "core"
            elif mass_land_count > 0:
                return "optimized"
            else:
                return "exhibition"

    def _calculate_cedh_score(self, cards: List[DeckCard], combo_count: int, game_changer_count: int, mass_land_count: int) -> int:
        """
        Calculate cEDH score based on multiple sophisticated criteria.
        Higher scores indicate more likely cEDH deck.
        """
        score = 0
        
        # Fast mana concentration (cEDH decks run almost all of them)
        fast_mana_cards = {
            "Sol Ring", "Mana Crypt", "Mana Vault", "Chrome Mox", "Mox Diamond", 
            "Mox Opal", "Lotus Petal", "Dark Ritual", "Cabal Ritual", "Ancient Tomb", 
            "Mishra's Workshop", "Grim Monolith"
        }
        fast_mana_count = sum(1 for card in cards if card.name in fast_mana_cards and card.is_game_changer)
        score += fast_mana_count * 2  # Fast mana is very important in cEDH
        
        # Premium tutors (not thematic tutors) - much stricter scoring
        premium_tutors = {
            "Demonic Tutor", "Vampiric Tutor", "Imperial Seal", "Grim Tutor",
            "Mystical Tutor", "Worldly Tutor", "Enlightened Tutor",
            "Beseech the Mirror"
        }
        premium_tutor_count = sum(1 for card in cards if card.name in premium_tutors and card.is_game_changer)
        score += premium_tutor_count * 3  # Premium tutors are crucial
        
        # Premium stack interaction
        premium_interaction = {
            "Force of Will", "Force of Negation", "Mana Drain", "Counterspell",
            "Spell Pierce", "Misdirection", "Pact of Negation"
        }
        interaction_count = sum(1 for card in cards if card.name in premium_interaction and card.is_game_changer)
        score += interaction_count * 2  # Stack interaction is vital
        
        # Best combo pieces (cEDH priority)
        best_combo_pieces = {
            "Thassa's Oracle", "Demonic Consultation", "Tainted Pact", 
            "Exquisite Blood", "Sanguine Bond"
        }
        combo_piece_count = sum(1 for card in cards if card.name in best_combo_pieces and card.is_game_changer)
        score += combo_piece_count * 2
        
        # Premium value engines
        premium_engines = {
            "Necropotence", "Ad Nauseam", "Underworld Breach", "Yawgmoth's Will",
            "Timetwister", "Wheel of Fortune"
        }
        engine_count = sum(1 for card in cards if card.name in premium_engines and card.is_game_changer)
        score += engine_count
        
        # More conservative bonuses - require true cEDH concentrations
        if fast_mana_count >= 5:
            score += 3  # cEDH typically runs 5-7 fast mana sources
        if premium_tutor_count >= 3:
            score += 4  # cEDH runs 3-5+ tutors
        if interaction_count >= 3:
            score += 3  # cEDH has lots of interaction
        
        # Stronger penalty for casual elements
        if mass_land_count > 0:
            score -= 3  # cEDH typically avoids mass land denial
        
        # Minimum requirements for cEDH classification
        total_critical_elements = fast_mana_count + premium_tutor_count + interaction_count + combo_piece_count
        if total_critical_elements < 8:  # Need at least 8 critical cEDH elements
            score = min(score, 15)  # Cap score if missing critical elements
        
        return score

    async def _load_tutor_cards(self) -> Set[str]:
        """Load all tutor cards from Scryfall API using otag:tutor query.
        
        Returns a set of tutor card names for classification.
        """
        if "tutor_cards" in self.cache:
            return self.cache["tutor_cards"]
        
        logger.info("Loading tutor cards from Scryfall API...")
        tutor_cards = set()
        page = 1
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while True:
                    # Fetch one page of tutor cards from Scryfall
                    url = f"https://api.scryfall.com/cards/search"
                    params = {
                        "q": "otag:tutor",
                        "unique": "cards",  # Remove duplicate gameplay objects
                        "order": "name",
                        "page": page,
                        "format": "json"
                    }
                    
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    
                    data = response.json()
                    
                    # Extract card names from this page
                    for card in data.get("data", []):
                        card_name = card.get("name", "").strip()
                        if card_name:
                            tutor_cards.add(card_name)
                    
                    # Check if there are more pages
                    if not data.get("has_more", False):
                        break
                    
                    page += 1
                    
                    # Safety limit to prevent infinite loops
                    if page > 20:  # Scryfall returns ~175 cards per page, 1166 total = ~7 pages
                        logger.warning("Reached page limit while fetching tutor cards")
                        break
                        
        except Exception as exc:
            logger.error(f"Error loading tutor cards from Scryfall: {exc}")
            # Fallback to common tutors if API fails
            tutor_cards = {
                "Demonic Tutor", "Vampiric Tutor", "Imperial Seal", "Grim Tutor",
                "Mystical Tutor", "Worldly Tutor", "Enlightened Tutor", "Beseech the Mirror",
                "Diabolic Intent", "Song of the Dryads", "Natural Order", "Chord of Calling",
                "Finale of Devastation", "Finale of Promise", "Rite of the Raging Storm",
                "Academy Rector", "Arena Rector", "Spellseeker", "Weathered Wayfarer",
                "Gamble", "Merchant Scroll", "Muddle the Mixture", "Transmute Artifact",
                "Tinker", "Demonic Consultation", "Tainted Pact"
            }
            logger.info(f"Using fallback tutor list with {len(tutor_cards)} cards")
        
        logger.info(f"Loaded {len(tutor_cards)} tutor cards from Scryfall")
        self.cache["tutor_cards"] = tutor_cards
        return tutor_cards

    async def _validate_bracket(self, cards: List[DeckCard], target_bracket: str, bracket_inferred: bool = False) -> BracketValidation:
        """Validate deck against bracket requirements"""
        if target_bracket not in COMMANDER_BRACKETS:
            return BracketValidation(
                target_bracket=target_bracket,
                overall_compliance=False,
                bracket_score=1,
                violations=[f"Invalid bracket: {target_bracket}"],
                recommendations=[f"Valid brackets: {', '.join(COMMANDER_BRACKETS.keys())}"]
            )
        
        # Load authoritative data to get combo pairs
        data = await self._load_authoritative_data()
        combo_pairs = data.get("early_game_combo_pairs", [])
        
        bracket_info = COMMANDER_BRACKETS[target_bracket]
        violations = []
        recommendations = []
        score_factors = []
        
        # Count deck characteristics
        game_changer_count = sum(1 for card in cards if card.is_game_changer)
        mass_land_count = sum(1 for card in cards if "mass_land_denial" in card.bracket_categories)
        tutor_count = sum(1 for card in cards if "tutor" in card.bracket_categories)
        
        # Check for extra turn cards
        extra_turn_cards = await self._get_extra_turn_cards()
        extra_turn_names = set(extra_turn_cards.keys())
        deck_extra_turn_cards = [
            card.name for card in cards 
            if card.name in extra_turn_names
        ]
        extra_turn_count = len(deck_extra_turn_cards)
        
        # Check for chaining extra turns (multiple extra turn cards)
        has_chaining_potential = extra_turn_count > 1
        
        # Check for 2-card combos
        detected_combos = self._detect_combos(cards, combo_pairs)
        combo_count = len(detected_combos)
        
        # Validate based on bracket restrictions from Commander Brackets system
        
        # Exhibition (Bracket 1): Theme-focused, very restrictive
        if target_bracket == "exhibition":
            if game_changer_count > 0:
                violations.append(f"Game changers found in Exhibition bracket ({game_changer_count} found)")
                recommendations.append("Consider moving to Core bracket or removing game changers")
            if mass_land_count > 0:
                violations.append(f"Mass land denial found in Exhibition bracket ({mass_land_count} found)")
                recommendations.append("Consider moving to Core bracket or removing mass land denial")
            if extra_turn_count > 0:
                extra_turn_list = ", ".join(deck_extra_turn_cards)
                violations.append(f"Extra turn cards found in Exhibition bracket: {extra_turn_list}")
                recommendations.append("Exhibition bracket prohibits extra turn cards - consider Core bracket")
            if combo_count > 0:
                combo_list = ", ".join([f"{c1} + {c2}" for c1, c2 in detected_combos])
                violations.append(f"2-card combos found in Exhibition bracket: {combo_list}")
                recommendations.append("Exhibition allows combos only if highly thematic - consider Core bracket")
            if tutor_count > 3:
                recommendations.append(f"High tutor count ({tutor_count}) may conflict with theme focus in Exhibition")
        
        # Core (Bracket 2): Mechanically focused, still restrictive  
        elif target_bracket == "core":
            if game_changer_count > 0:
                violations.append(f"Game changers found in Core bracket ({game_changer_count} found)")
                recommendations.append("Consider moving to Upgraded bracket or removing game changers")
            if mass_land_count > 0:
                violations.append(f"Mass land denial found in Core bracket ({mass_land_count} found)")
                recommendations.append("Consider moving to Upgraded bracket or removing mass land denial")
            if has_chaining_potential:
                extra_turn_list = ", ".join(deck_extra_turn_cards)
                violations.append(f"Chaining extra turns potential in Core bracket: {extra_turn_list}")
                recommendations.append("Core bracket prohibits chaining extra turns - consider Upgraded bracket")
            if combo_count > 0:
                combo_list = ", ".join([f"{c1} + {c2}" for c1, c2 in detected_combos])
                violations.append(f"2-card combos found in Core bracket: {combo_list}")
                recommendations.append("Consider moving to Upgraded bracket or removing combos")
            if tutor_count > 5:
                recommendations.append(f"High tutor count ({tutor_count}) may be too strong for Core bracket")
        
        # Upgraded (Bracket 3): Powered up with synergy
        elif target_bracket == "upgraded":
            if game_changer_count > 3:
                violations.append(f"Too many game changers for Upgraded bracket ({game_changer_count} found, max 3)")
                recommendations.append("Consider moving to Optimized bracket or reducing game changers")
            if mass_land_count > 0:
                violations.append(f"Mass land denial found in Upgraded bracket ({mass_land_count} found)")
                recommendations.append("Consider moving to Optimized bracket or removing mass land denial")
            if has_chaining_potential:
                extra_turn_list = ", ".join(deck_extra_turn_cards)
                violations.append(f"Chaining extra turns potential in Upgraded bracket: {extra_turn_list}")
                recommendations.append("Upgraded bracket prohibits chaining extra turns - consider Optimized bracket")
            if combo_count > 0:
                combo_list = ", ".join([f"{c1} + {c2}" for c1, c2 in detected_combos])
                violations.append(f"2-card combos found in Upgraded bracket: {combo_list}")
                recommendations.append("Consider moving to Optimized bracket or removing early-game combos")
            
        # Optimized (Bracket 4): Fast, lethal, no restrictions
        elif target_bracket == "optimized":
            # No restrictions - this bracket allows everything
            if game_changer_count < 2:
                recommendations.append(f"Consider adding more powerful cards ({game_changer_count} game changers)")
            if tutor_count < 3:
                recommendations.append(f"Consider adding more tutors for consistency ({tutor_count} tutors)")
            if combo_count == 0:
                recommendations.append("Consider adding combos for faster wins")
        
        # cEDH (Bracket 5): Competitive metagame, no restrictions
        elif target_bracket == "cedh":
            # No restrictions - this is the highest tier
            recommendations.append("cEDH allows all cards - deck should be optimized for competitive play")
            if game_changer_count < 5:
                recommendations.append(f"Consider adding more game changers ({game_changer_count} found)")
        
        # Calculate overall compliance score (1-5 scale)
        if len(violations) == 0:
            compliance_score = 5
        elif len(violations) == 1:
            compliance_score = 4
        elif len(violations) == 2:
            compliance_score = 3
        elif len(violations) == 3:
            compliance_score = 2
        else:
            compliance_score = 1
            
        overall_compliance = len(violations) == 0
        
        return BracketValidation(
            target_bracket=target_bracket,
            overall_compliance=overall_compliance,
            bracket_score=compliance_score,
            violations=violations,
            recommendations=recommendations
        )
        
        # Calculate bracket score (1-5)
        compliance_score = 5
        if violations:
            compliance_score = max(1, 5 - len(violations))
        
        # Add recommendations based on analysis
        if target_bracket == "exhibition" and mass_land_count > 0:
            recommendations.append("Consider thematic alternatives to mass land denial")
        
        if tutor_count == 0 and target_bracket in ["upgraded", "optimized"]:
            recommendations.append("Consider adding tutors for better consistency")
        
        return BracketValidation(
            target_bracket=target_bracket,
            overall_compliance=len(violations) == 0,
            bracket_score=compliance_score,
            compliance_details={
                "game_changers": game_changer_count,
                "mass_land_denial": mass_land_count,
                "extra_turn_cards": extra_turn_count,
                "extra_turn_card_names": deck_extra_turn_cards,
                "has_chaining_potential": has_chaining_potential,
                "early_game_combos": combo_count,
                "detected_combos": [f"{c1} + {c2}" for c1, c2 in detected_combos],
                "tutors": tutor_count,
                "total_cards": self._calculate_total_card_count(cards),
                "bracket_inferred": bracket_inferred
            },
            violations=violations,
            recommendations=recommendations
        )
    
    def _check_duplicates(self, cards: List[DeckCard]) -> bool:
        """Check for duplicate cards using total quantities per name."""
        return bool(self._find_illegal_duplicates(cards))

    def _find_illegal_duplicates(self, cards: List[DeckCard]) -> Dict[str, int]:
        """Return a mapping of card names that violate the singleton rule."""
        counts: Dict[str, int] = defaultdict(int)

        for card in cards:
            normalized_name = self._normalize_card_name(card.name)
            counts[normalized_name] += max(card.quantity, 1)

        illegal_duplicates: Dict[str, int] = {}
        for name, total in counts.items():
            if total <= 1:
                continue
            if self._is_unlimited_card(name):
                continue
            illegal_duplicates[name] = total

        return illegal_duplicates

    def _is_unlimited_card(self, card_name: str) -> bool:
        """Return True if the card is exempt from singleton restrictions."""
        normalized = self._normalize_card_name(card_name).lower()
        return normalized in UNLIMITED_DUPLICATE_CARDS

    def _calculate_total_card_count(self, cards: List[DeckCard]) -> int:
        """Sum quantities to understand the real deck size."""
        return sum(card.quantity for card in cards)

    def _calculate_total_card_count(self, cards: List[DeckCard]) -> int:
        """Sum quantities to understand the real deck size."""
        return sum(card.quantity for card in cards)

    def _calculate_salt_score(self, cards: List[DeckCard], data: Dict[str, Dict[str, float]]) -> float:
        """
        Calculate salt score for a deck based on saltiest cards.
        Returns a score from 0-5 where higher means saltier.
        """
        if not cards:
            return 0.0
        
        salt_cards = data.get("salt_cards", {})
        total_salt = 0.0
        card_count = 0
        
        for card in cards:
            # Normalize card name for lookup
            card_name = card.name.strip()
            salt_score = salt_cards.get(card_name, 0.0)

            # Weight by quantity if present
            weighted_salt = salt_score * card.quantity
            total_salt += weighted_salt
            card_count += card.quantity
        
        # Calculate average salt per card, then scale to 0-5
        avg_salt_per_card = total_salt / max(card_count, 1)
        
        # Salt scores are already in reasonable range, scale appropriately
        # Most cards are 1.5-3.0 range, so we'll normalize to 0-5
        normalized_score = min(5.0, avg_salt_per_card * 1.5)
        
        return round(normalized_score, 2)

    def _generate_commander_lookup_names(self, commander_name: str) -> List[str]:
        """Generate normalized variations of a commander name for cache lookups."""

        if not commander_name:
            return []

        normalized = self._normalize_card_name(commander_name)
        normalized = normalized.replace("’", "'").replace("`", "'")
        normalized = re.sub(r"\s+", " ", normalized).strip()

        candidates: List[str] = []

        def _add_candidate(value: str) -> None:
            value = value.strip()
            if value and value not in candidates:
                candidates.append(value)

        _add_candidate(normalized)

        # Handle split cards or MDFCs that might include both faces
        if "//" in normalized:
            _add_candidate(normalized.split("//")[0].strip())

        # Some clients provide the commander with parenthetical print details
        if normalized.endswith(")"):
            simplified = re.sub(r"\s*\([^)]*\)\s*$", "", normalized).strip()
            _add_candidate(simplified)

        # Remove commas when callers omit them (e.g., "Atraxa Praetors' Voice")
        if "," in normalized:
            _add_candidate(normalized.replace(",", ""))

        return candidates

    async def _get_commander_salt_score(self, commander_name: str) -> float:
        """Get salt score for a commander from EDHRec or cache (with fuzzy lookup)."""
        if not commander_name:
            return 0.0

        salt_cache = get_salt_cache()
        await salt_cache.ensure_loaded()

        # Generate name variants
        candidates = self._generate_commander_lookup_names(commander_name)
        normalized_candidates = [c.lower().replace(",", "").replace("’", "'") for c in candidates]

        # 1️⃣ Try exact cache match
        for candidate in candidates:
            cache_score = salt_cache.get_card_salt(candidate)
            if cache_score and cache_score > 0:
                return round(cache_score, 2)

        # 2️⃣ Try lowercase or comma-stripped variants
        for name in normalized_candidates:
            for cached_name, salt in salt_cache.get_all_salt_scores().items():
                normalized_cached = cached_name.lower().replace(",", "").replace("’", "'")
                if normalized_cached == name:
                    return round(salt, 2)

        # 3️⃣ Try fuzzy partial match (e.g., "Aesi" inside "Aesi Tyrant of Gyre Strait")
        for name in normalized_candidates:
            for cached_name, salt in salt_cache.get_all_salt_scores().items():
                if name in cached_name.lower() and salt > 0:
                    return round(salt, 2)

        # 4️⃣ Final fallback - use EDHRec direct lookup
        try:
            commander_normalized = commander_name.lower().replace(" ", "-").replace(",", "").replace("'", "")
            url = f"https://edhrec.com/commanders/{commander_normalized}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    salt_score = self._extract_salt_score_from_html_commander(soup, commander_name)
                    if salt_score > 0:
                        return salt_score
        except Exception as e:
            logger.warning(f"Failed live fetch for commander salt ({commander_name}): {e}")

        # 5️⃣ Last fallback
        return self._get_fallback_commander_salt(commander_name.lower().replace(" ", "-"))

    def _get_fallback_commander_salt(self, commander_normalized: str) -> float:
        """Fallback salt scores for known high-salt commanders."""
        fallback_scores = {
            "tergrid-god-of-fright": 2.8,
            "yuriko-the-tigers-shadow": 2.15,
            "vorinclex-voice-of-hunger": 2.61,
            "kinnan-bonder-prodigy": 2.15,
            "jin-gitaxias-core-augur": 2.57,
            "edgar-markov": 2.05,
            "sheoldred-the-apocalypse": 2.03,
            "atraxa-praetors-voice": 1.72,
            "urza-lord-high-artificer": 2.31,
            "winota-joiner-of-forces": 1.95,
            "slicer-hired-muscle": 0.96  # Add the specific case from user's example
        }
        return fallback_scores.get(commander_normalized, 1.0)

    def _extract_salt_score_from_html_commander(self, soup: BeautifulSoup, commander_name: str) -> float:
        """Extract salt score from commander page HTML."""
        # Look for salt score in various places in the HTML
        
        # Method 1: Look for JSON data
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag and script_tag.string:
            try:
                data = json.loads(script_tag.string)
                page_props = data.get("props", {}).get("pageProps", {})
                page_data = page_props.get("data", {})
                container = page_data.get("container", {})
                json_dict = container.get("json_dict", {})
                
                # Try to find salt score in the commander data
                return self._extract_salt_score_from_commander_data(json_dict)
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug(f"Failed to extract commander salt from JSON: {e}")
        
        # Method 2: Look for salt score in the page text
        page_text = soup.get_text()
        import re
        
        # Look for patterns like "Salt Score: 2.5" or "Salt Score 2.5"
        salt_patterns = [
            r"Salt Score:\s*(\d+\.?\d*)",
            r"Salt Score\s+(\d+\.?\d*)",
            r"EDHREC Salt Score:\s*(\d+\.?\d*)"
        ]
        
        for pattern in salt_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        
        # Method 3: Look for specific elements containing salt score
        salt_elements = soup.find_all(string=re.compile(r"Salt Score", re.IGNORECASE))
        for element in salt_elements:
            # Look for nearby numbers
            parent = element.parent if element.parent else element
            number_match = re.search(r'(\d+\.?\d*)', parent.get_text())
            if number_match:
                try:
                    return float(number_match.group(1))
                except ValueError:
                    continue
        
        return 0.0

    def _extract_salt_score_from_commander_data(self, data: Dict[str, Any]) -> float:
        """Extract salt score from commander JSON data."""
        if not isinstance(data, dict):
            return 0.0
        
        # Look for salt score in various data structures
        def search_for_salt(obj, path=""):
            if isinstance(obj, dict):
                if "salt" in obj:
                    salt_value = obj["salt"]
                    if isinstance(salt_value, (int, float)) and 0 <= salt_value <= 5:
                        return salt_value
                    elif isinstance(salt_value, str):
                        try:
                            return float(salt_value)
                        except ValueError:
                            pass
                
                # Recursively search nested objects
                for key, value in obj.items():
                    result = search_for_salt(value, f"{path}.{key}")
                    if result > 0:
                        return result
                        
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    result = search_for_salt(item, f"{path}[{i}]")
                    if result > 0:
                        return result
            
            return 0.0
        
        return search_for_salt(data)

    def _get_salt_level_description(self, score: float) -> str:
        """Get a description of the salt level based on score."""
        if score >= 3.0:
            return "Extremely Salty"
        elif score >= 2.5:
            return "Very Salty"
        elif score >= 2.0:
            return "Moderately Salty"
        elif score >= 1.5:
            return "Slightly Salty"
        elif score >= 1.0:
            return "Mildly Salty"
        else:
            return "Casual"


# Create global validator instance
deck_validator = DeckValidator()


# --------------------------------------------------------------------
# Deck Validation API Endpoints
# --------------------------------------------------------------------

@router.post("/api/v1/deck/validate", response_model=DeckValidationResponse)
async def validate_deck(
    request: DeckValidationRequest,
    api_key: str = Depends(verify_api_key)
) -> DeckValidationResponse:
    """
    Validate a deck against Commander Brackets rules and format legality.
    
    - Provide a decklist via:
      * List of card names
      * Multi-line text blob
      * Text chunks
      * Deck URL (Moxfield or Archidekt)
    - Optionally specify commander and target bracket
    - Validates against official Commander Brackets system
    - Checks for Game Changers, format legality, and power level compliance
    """
    try:
        result = await deck_validator.validate_deck(request)

        # Cache the result for 1 hour using the validator's cache
        signature = DeckValidator.build_request_signature(request)
        cache_key = f"deck_validation_{signature}"
        deck_validator.cache[cache_key] = result
        
        return result
        
    except Exception as exc:
        logger.error(f"Error in deck validation: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to validate deck: {str(exc)}"
        )


@router.get("/api/v1/deck/validate/sample")
async def get_sample_validation(
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get sample deck validation to demonstrate the endpoint functionality.
    """
    sample_deck = DeckValidationRequest(
        decklist=[
            "1x Sol Ring",
            "4x Lightning Bolt",
            "2x Counterspell",
            "1x Demonic Consultation",
            "1x Thassa's Oracle",
            "1x Swords to Plowshares",
            "1x Ponder",
            "1x Brainstorm",
            "1x Vampiric Tutor",
            "97x Island"
        ],
        commander="Jace, Wielder of Mysteries",
        target_bracket="upgraded",
        validate_bracket=True,
        validate_legality=True
    )
    
    result = await deck_validator.validate_deck(sample_deck)
    result.warnings.append("This is a sample validation for demonstration purposes")
    
    return {
        "sample_request": sample_deck.dict(),
        "validation_result": result.dict(),
        "note": "This demonstrates the validation endpoint with a sample deck"
    }


@router.get("/api/v1/brackets/info")
async def get_brackets_info(
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get comprehensive information about Commander Brackets system.
    
    Returns official bracket definitions, expectations, and restrictions
    based on Wizards of the Coast's October 21, 2025 update.
    """
    return {
        "brackets": COMMANDER_BRACKETS,
        "game_changers": {
            "current_list_size": len(GAME_CHANGERS["current_list"]),
            "recent_removals": GAME_CHANGERS["removed_2025"],
            "total_removed_2025": len(GAME_CHANGERS["removed_2025"])
        },
        "validation_categories": {
            "mass_land_denial": {
                "description": "Cards that destroy, exile, or bounce multiple lands",
                "sample_cards": MASS_LAND_DENIAL[:10]
            },
            "early_game_combos": {
                "description": "2-card combinations that can win early",
                "combos": EARLY_GAME_COMBOS
            }
        },
        "last_updated": "2025-10-21",
        "source": "https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-october-21-2025"
    }


@router.get("/api/v1/brackets/game-changers/list")
async def get_game_changers_list(
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get the complete list of Game Changers cards.
    
    Based on the October 21, 2025 update from Wizards of the Coast.
    """
    return {
        "current_game_changers": GAME_CHANGERS["current_list"],
        "recently_removed": GAME_CHANGERS["removed_2025"],
        "removal_reasoning": {
            "high_mana_value": "Expropriate, Jin-Gitaxias, Sway of the Stars, Vorinclex",
            "legends_strongest_as_commanders": "Kinnan, Urza, Winota, Yuriko",
            "other": "Deflecting Swat, Food Chain"
        },
        "last_updated": "2025-10-21"
    }


@router.post("/api/v1/salt/refresh")
async def refresh_salt_data(
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Manually refresh the salt score cache from EDHRec.
    
    This fetches all 30,000+ cards with salt scores from EDHRec's JSON API
    and saves them to the local cache. The cache never expires automatically -
    only use this endpoint when you want fresh data.
    
    Recommended refresh interval: Every 3 months.
    """
    try:
        result = await refresh_salt_cache()
        return {
            "message": "Salt cache refresh completed",
            "result": result
        }
    except Exception as exc:
        logger.error(f"Error refreshing salt cache: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh salt cache: {str(exc)}"
        )


@router.get("/api/v1/salt/info")
async def get_salt_cache_info(
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get information about the current salt score cache.
    
    Returns cache status, card count, and last refresh time.
    """
    salt_cache = get_salt_cache()
    return salt_cache.get_cache_info()


@router.get("/api/v1/salt/card/{card_name}")
async def get_card_salt_score(
    card_name: str,
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get the salt score for a specific card.
    
    Args:
        card_name: The name of the card (case-insensitive)
    
    Returns:
        Card name and salt score
    """
    salt_cache = get_salt_cache()
    await salt_cache.ensure_loaded()
    
    salt_score = salt_cache.get_card_salt(card_name)
    
    return {
        "card_name": card_name,
        "salt_score": salt_score,
        "found": salt_score > 0
    }


# --------------------------------------------------------------------
# Exception Handlers
# --------------------------------------------------------------------


