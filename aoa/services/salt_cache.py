"""
Salt Score Cache Service for EDHRec data.

Fetches and caches all salt scores from EDHRec's JSON API.
Cache never expires - only refreshed on manual request.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# Default cache file location
DEFAULT_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "salt_cache.json"
)


class SaltCacheService:
    """Service for managing EDHRec salt score cache."""
    
    # Salt tier thresholds for deck average salt scores (0-5 scale)
    SALT_TIERS = {
        'Casual': (0.0, 1.0),
        'Slightly Salty': (1.0, 1.5),
        'Moderately Salty': (1.5, 2.0),
        'Very Salty': (2.0, 2.5),
        'Extremely Salty': (2.5, 3.0),
        'Toxic': (3.0, float('inf'))
    }
    
    def __init__(self, cache_file: Optional[str] = None):
        """
        Initialize the salt cache service.
        
        Args:
            cache_file: Path to cache file. If None, uses default location.
        """
        self.cache_file = cache_file or DEFAULT_CACHE_FILE
        self.salt_data: Dict[str, float] = {}  # card_name (lowercase) -> salt_score
        self._is_loaded = False
        
        # Ensure cache directory exists
        cache_dir = os.path.dirname(self.cache_file)
        if cache_dir and not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)
        
        # Load cache on initialization
        self._load_cache()
    
    def _load_cache(self) -> None:
        """Load cached data from file if it exists."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                
                self.salt_data = cache.get('cards', {})
                cached_at = cache.get('cached_at', 'unknown')
                card_count = len(self.salt_data)
                
                logger.info(f"Loaded {card_count:,} salt scores from cache (cached: {cached_at})")
                self._is_loaded = True
                
            except (json.JSONDecodeError, KeyError, IOError) as e:
                logger.warning(f"Failed to load salt cache: {e}")
                self.salt_data = {}
                self._is_loaded = False
        else:
            logger.info("No salt cache file found - will fetch on first use or manual refresh")
            self._is_loaded = False
    
    async def ensure_loaded(self) -> None:
        """Ensure salt data is loaded, fetching if necessary."""
        if not self._is_loaded or not self.salt_data:
            logger.info("Salt cache not loaded - fetching from EDHRec...")
            await self.refresh_cache()
    
    async def refresh_cache(self) -> Dict[str, Any]:
        """
        Fetch fresh salt data from EDHRec and save to cache.
        
        Returns:
            Dictionary with refresh results including card count.
        """
        logger.info("Refreshing salt cache from EDHRec JSON API...")
        
        base_url = 'https://json.edhrec.com/pages/'
        self.salt_data = {}
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # First page has different structure
                url = base_url + 'top/salt.json'
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                
                cardlist = data['container']['json_dict']['cardlists'][0]
                cards = cardlist.get('cardviews', [])
                next_page = cardlist.get('more', '')
                
                # Process first page
                for card in cards:
                    self._process_card(card)
                
                # Fetch remaining pages
                page = 1
                while next_page:
                    url = base_url + next_page
                    response = await client.get(url)
                    response.raise_for_status()
                    data = response.json()
                    
                    for card in data.get('cardviews', []):
                        self._process_card(card)
                    
                    next_page = data.get('more', '')
                    page += 1
                    
                    if page % 50 == 0:
                        logger.info(f"Fetched {page} pages ({len(self.salt_data):,} cards)...")
                
                # Save to cache file
                cache_data = {
                    'cached_at': datetime.now().isoformat(),
                    'card_count': len(self.salt_data),
                    'cards': self.salt_data
                }
                
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f)
                
                self._is_loaded = True
                logger.info(f"Salt cache refreshed: {len(self.salt_data):,} cards saved to {self.cache_file}")
                
                return {
                    'success': True,
                    'card_count': len(self.salt_data),
                    'cached_at': cache_data['cached_at'],
                    'pages_fetched': page + 1
                }
                
        except Exception as e:
            logger.error(f"Failed to refresh salt cache: {e}")
            return {
                'success': False,
                'error': str(e),
                'card_count': len(self.salt_data)
            }
    
    def _process_card(self, card: Dict[str, Any]) -> None:
        """Process a single card and add to salt_data."""
        card_name = card.get('name', '').strip()
        if not card_name:
            return
        
        # Extract salt score from label
        label = card.get('label', '')
        if 'Salt Score:' in label:
            try:
                salt_text = label.split('\n')[0].replace('Salt Score: ', '')
                salt_score = float(salt_text)
                self.salt_data[card_name.lower()] = salt_score
            except (ValueError, IndexError):
                pass
    
    def get_card_salt(self, card_name: str) -> float:
        """
        Get salt score for a single card.
        
        Args:
            card_name: The card name (case-insensitive)
        
        Returns:
            Salt score (0.0 if card not found)
        """
        return self.salt_data.get(card_name.lower().strip(), 0.0)
    
    def get_salt_tier(self, average_salt: float) -> str:
        """
        Get the salt tier for a given average salt score.
        
        Args:
            average_salt: Average salt score per card (0-5 scale)
        
        Returns:
            Tier name (e.g., "Casual", "Salty", "Toxic")
        """
        for tier, (min_val, max_val) in self.SALT_TIERS.items():
            if min_val <= average_salt < max_val:
                return tier
        return "Unknown"
    
    def calculate_deck_salt(self, card_names: list) -> Dict[str, Any]:
        """
        Calculate total salt score for a deck.
        
        Args:
            card_names: List of card names (strings)
        
        Returns:
            Dictionary with salt analysis results
        """
        total = 0.0
        card_scores = []
        unknown = []
        
        for card_name in card_names:
            normalized = card_name.lower().strip()
            
            if normalized in self.salt_data:
                salt = self.salt_data[normalized]
                if salt > 0:
                    card_scores.append({
                        'name': card_name,
                        'salt': round(salt, 2)
                    })
                    total += salt
            else:
                unknown.append(card_name)
        
        # Sort by salt score descending
        card_scores.sort(key=lambda x: x['salt'], reverse=True)
        
        total_salt = round(total, 2)
        card_count = len(card_names)
        
        return {
            'total_salt': total_salt,  # Keep for backward compatibility
            'average_salt': round(total / card_count, 2) if card_count > 0 else 0,
            'salt_tier': self.get_salt_tier(round(total / card_count, 2) if card_count > 0 else 0),
            'card_count': card_count,
            'salty_card_count': len(card_scores),
            'top_offenders': card_scores[:10],
            'all_salty_cards': card_scores,
            'unknown_cards': unknown
        }
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about the current cache."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                
                return {
                    'cached_at': cache.get('cached_at'),
                    'card_count': cache.get('card_count', len(self.salt_data)),
                    'cache_file': self.cache_file,
                    'is_loaded': self._is_loaded
                }
            except Exception:
                pass
        
        return {
            'cached_at': None,
            'card_count': 0,
            'cache_file': self.cache_file,
            'is_loaded': False
        }
    
    def get_all_salt_scores(self) -> Dict[str, float]:
        """
        Get all salt scores as a dictionary.
        
        Returns:
            Dictionary mapping card names to salt scores.
            Note: Keys are lowercase for case-insensitive lookup.
        """
        return self.salt_data.copy()


# Global singleton instance
_salt_cache_instance: Optional[SaltCacheService] = None


def get_salt_cache() -> SaltCacheService:
    """Get the global salt cache service instance."""
    global _salt_cache_instance
    if _salt_cache_instance is None:
        _salt_cache_instance = SaltCacheService()
    return _salt_cache_instance


async def refresh_salt_cache() -> Dict[str, Any]:
    """Convenience function to refresh the global salt cache."""
    cache = get_salt_cache()
    return await cache.refresh_cache()
