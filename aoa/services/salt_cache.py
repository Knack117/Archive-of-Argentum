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
        
        # Log cache status for debugging
        cache_count = len(self.salt_data)
        logger.info(f"Salt cache status: {cache_count:,} cards loaded, cache ready: {self._is_loaded}")
    
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
        
        # Try multiple ways to extract salt score for robustness
        salt_score = None
        
        # Method 1: Extract from label (original format)
        label = card.get('label', '')
        if 'Salt Score:' in label:
            try:
                # Handle variations like "Salt Score: 1.48\n#123 Most Salty Card"
                salt_text = label.split('Salt Score:')[-1].split('\n')[0].strip()
                salt_score = float(salt_text)
            except (ValueError, IndexError):
                pass
        
        # Method 2: Direct salt field (if EDHRec uses this format)
        if salt_score is None and 'salt' in card:
            try:
                salt_score = float(card['salt'])
            except (ValueError, TypeError):
                pass
        
        # Method 3: Alternative field names
        if salt_score is None:
            for field in ['salt_score', 'score', 'rating']:
                if field in card:
                    try:
                        salt_score = float(card[field])
                        break
                    except (ValueError, TypeError):
                        continue
        
        # Store the salt score if we found one
        if salt_score is not None and salt_score >= 0:
            self.salt_data[card_name.lower()] = salt_score
        else:
            logger.debug(f"Failed to extract salt score for card: {card_name}")
    
    def get_card_salt(self, card_name: str) -> float:
        """
        Get salt score for a single card using centralized normalization.
        
        Args:
            card_name: The card name to look up
        
        Returns:
            Salt score (0.0 if card not found)
        """
        normalized_name = self.normalize_card_name(card_name)
        return self.salt_data.get(normalized_name, 0.0)
    
    @staticmethod
    def normalize_card_name(name: str) -> str:
        """
        Centralized card name normalization for consistent lookups.
        
        This method normalizes card names by:
        - Converting to lowercase
        - Stripping leading/trailing whitespace
        - Handling common punctuation variations
        
        Args:
            name: The card name to normalize
        
        Returns:
            Normalized card name suitable for cache lookup
        """
        if not name:
            return ""
        
        normalized = name.lower().strip()
        # Handle common punctuation variations
        normalized = normalized.replace("'", "'")  # Ensure consistent apostrophes
        normalized = normalized.replace("—", "-")  # Normalize em/en dashes to hyphens
        
        return normalized

    @staticmethod
    def generate_name_variants(name: str) -> list[str]:
        """
        Generate multiple name variants for comprehensive fallback matching.
        
        This method creates various normalization forms to handle mismatches between
        different data sources (EDHRec, Moxfield, Archidekt, etc.).
        
        Args:
            name: The card name to generate variants for
        
        Returns:
            List of normalized name variants
        """
        if not name:
            return []
        
        normalized_base = SaltCacheService.normalize_card_name(name)
        
        variants = {
            normalized_base,  # Original normalized
            normalized_base.replace(" ", ""),  # No spaces
            normalized_base.replace(" ", "-"),  # Spaces to hyphens
            normalized_base.replace(",", ""),  # Remove commas
            normalized_base.replace(",", "").replace(" ", ""),  # Remove commas and spaces
            normalized_base.replace(" ", "-").replace(",", ""),  # Hyphens, no commas
            normalized_base.replace(",", "").replace(" ", "-"),  # Commas to hyphens
        }
        
        return list(variants)

    def get_card_salt_with_variants(self, card_name: str) -> float:
        """
        Get salt score using comprehensive variant matching.
        
        This method tries multiple name normalization approaches to find the best match.
        It's particularly useful for commander salt scoring where name format varies.
        
        Args:
            card_name: The card name to look up
        
        Returns:
            Salt score (0.0 if card not found in any variant)
        """
        variants = self.generate_name_variants(card_name)
        
        for variant in variants:
            score = self.salt_data.get(variant, None)
            if score is not None:
                return score
        
        # If no variants matched, fall back to basic lookup
        return self.salt_data.get(self.normalize_card_name(card_name), 0.0)

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
        Calculate total salt score for a deck with comprehensive cache monitoring.
        
        Args:
            card_names: List of card names (strings)
        
        Returns:
            Dictionary with salt analysis results and cache performance metrics
        """
        total = 0.0
        card_scores = []
        unknown = []
        cache_hits = 0
        
        for card_name in card_names:
            # Use centralized normalization
            normalized = self.normalize_card_name(card_name)
            
            if normalized in self.salt_data:
                salt = self.salt_data[normalized]
                if salt > 0:
                    card_scores.append({
                        'name': card_name,
                        'salt': round(salt, 2)
                    })
                    total += salt
                    cache_hits += 1
            else:
                unknown.append(card_name)
        
        # Sort by salt score descending
        card_scores.sort(key=lambda x: x['salt'], reverse=True)
        
        total_salt = round(total, 2)
        card_count = len(card_names)
        
        # Calculate cache hit ratio for monitoring
        hit_ratio = cache_hits / card_count if card_count > 0 else 0
        
        # Log cache performance metrics
        logger.debug(f"Salt cache analysis: {cache_hits}/{card_count} hits ({hit_ratio:.1%}), "
                    f"average_salt: {total_salt/card_count:.2f}, tier: {self.get_salt_tier(round(total / card_count, 2))}")
        
        return {
            'total_salt': total_salt,  # Keep for backward compatibility
            'average_salt': round(total / card_count, 2) if card_count > 0 else 0,
            'salt_tier': self.get_salt_tier(round(total / card_count, 2) if card_count > 0 else 0),
            'card_count': card_count,
            'salty_card_count': len(card_scores),
            'top_offenders': card_scores[:10],
            'all_salty_cards': card_scores,
            'unknown_cards': unknown,
            'cache_performance': {
                'cache_hits': cache_hits,
                'total_lookups': card_count,
                'hit_ratio': round(hit_ratio, 3),
                'misses': len(unknown)
            }
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
    
    def debug_cache_status(self) -> Dict[str, Any]:
        """
        Debug information about the cache status for troubleshooting.
        
        Returns:
            Dictionary with cache debugging information.
        """
        return {
            'is_loaded': self._is_loaded,
            'cache_file_exists': os.path.exists(self.cache_file),
            'cache_file_path': self.cache_file,
            'card_count': len(self.salt_data),
            'cache_size_bytes': os.path.getsize(self.cache_file) if os.path.exists(self.cache_file) else 0,
            'sample_cards': list(self.salt_data.keys())[:10] if self.salt_data else [],
            'top_salt_scores': sorted(self.salt_data.items(), key=lambda x: x[1], reverse=True)[:5] if self.salt_data else []
        }


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
