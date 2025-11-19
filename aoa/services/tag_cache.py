"""Tag cache service for managing EDHRec theme/tag catalog."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class TagCacheService:
    """Service for managing EDHRec theme/tag cache."""
    
    def __init__(self, cache_file: str = "data/tags_cache.json"):
        self.cache_file = Path(cache_file)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._cache_data: Optional[Dict] = None
        self._tags_set: Set[str] = set()
        self._is_loaded = False
    
    async def load_cache(self) -> None:
        """Load the tag cache from file."""
        if self._is_loaded and self._cache_data:
            return
        
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    self._cache_data = json.load(f)
                
                tags = self._cache_data.get('tags', [])
                self._tags_set = set(tags)
                
                logger.info(f"Loaded {len(self._tags_set)} tags from cache")
            else:
                self._cache_data = {}
                self._tags_set = set()
                logger.info("No existing tag cache found")
            
            self._is_loaded = True
            
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load tag cache: {e}")
            self._cache_data = {}
            self._tags_set = set()
            self._is_loaded = True
    
    async def is_cache_fresh(self, max_age_hours: int = 24) -> bool:
        """Check if the cache is fresh (less than max_age_hours old)."""
        if not self._cache_data:
            return False
        
        cached_at = self._cache_data.get('cached_at')
        if not cached_at:
            return False
        
        try:
            cache_time = datetime.fromisoformat(cached_at)
            age = datetime.utcnow() - cache_time
            return age < timedelta(hours=max_age_hours)
        except (ValueError, TypeError):
            return False
    
    async def get_available_tags(self) -> List[str]:
        """Get all available tags from cache."""
        await self.load_cache()
        return sorted(list(self._tags_set))
    
    async def tag_exists(self, tag: str) -> bool:
        """Check if a tag exists in the cache."""
        await self.load_cache()
        return tag.lower() in self._tags_set
    
    async def is_valid_base_theme(self, theme: str) -> bool:
        """Check if a theme exists as a base theme in the cache."""
        await self.load_cache()
        return theme.lower() in self._tags_set
    
    async def get_tag_examples(self, limit: int = 10) -> List[str]:
        """Get example tags from the cache."""
        await self.load_cache()
        return sorted(list(self._tags_set))[:limit]
    
    async def get_composite_suggestions(self, theme: str, colors: List[str]) -> List[str]:
        """Get suggestions for theme-color combinations."""
        await self.load_cache()
        suggestions = []
        
        theme_lower = theme.lower()
        for color in colors:
            color_lower = color.lower()
            # Try theme-color pattern (e.g., goblins-izzet)
            suggestion = f"{theme_lower}-{color_lower}"
            if suggestion in self._tags_set:
                suggestions.append(suggestion)
        
        return suggestions
    
    async def refresh_cache_from_source(self, tags: List[str]) -> None:
        """Refresh the cache with new tags from source."""
        cache_data = {
            "cached_at": datetime.utcnow().isoformat(),
            "tags_count": len(tags),
            "tags": tags
        }
        
        with open(self.cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
        
        self._cache_data = cache_data
        self._tags_set = set(tags)
        
        logger.info(f"Refreshed cache with {len(tags)} tags")


# Global instance
tag_cache = TagCacheService()


async def get_tag_cache() -> TagCacheService:
    """Get the global tag cache instance."""
    return tag_cache


async def validate_theme_slug(theme_slug: str, cache: TagCacheService) -> None:
    """Validate that a theme slug is properly formatted.
    
    This is a lenient validation that allows themes not in the cache to proceed
    to EDHRec lookup. Only rejects obviously malformed inputs.
    """
    sanitized = (theme_slug or "").strip().lower()
    if not sanitized:
        raise HTTPException(status_code=400, detail="Theme slug cannot be empty")
    
    # Reject slugs with invalid characters (only allow alphanumeric, hyphens, and underscores)
    import re
    if not re.match(r'^[a-z0-9\-_]+$', sanitized):
        raise HTTPException(
            status_code=400,
            detail=f"Theme slug '{sanitized}' contains invalid characters. Use only letters, numbers, and hyphens."
        )
    
    # Warn if not in cache but allow request to proceed
    await cache.load_cache()
    if not await cache.tag_exists(sanitized):
        # Check if it's a composite theme (color-theme or theme-color)
        if '-' in sanitized:
            parts = sanitized.split('-', 1)
            if len(parts) == 2:
                part1, part2 = parts
                # If either part exists in cache, allow it through
                if await cache.tag_exists(part1) or await cache.tag_exists(part2):
                    logger.info(f"Theme '{sanitized}' not in cache but has valid components, allowing")
                    return
        
        # Not in cache, but we'll still try EDHRec (lenient validation)
        logger.info(f"Theme '{sanitized}' not in cache, will attempt EDHRec lookup")
    
    # All checks passed (or we're being lenient)
    return
