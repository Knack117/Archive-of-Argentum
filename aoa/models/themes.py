"""Theme and tag response models."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ThemeItem(BaseModel):
    """Individual theme item (card) with optional metadata."""
    name: str
    id: Optional[str] = None  # Scryfall UUID
    image: Optional[str] = None  # Optional Scryfall image URL


class ThemeCollection(BaseModel):
    """Collection of theme items under a specific header."""
    header: str
    items: List[ThemeItem] = Field(default_factory=list)


class ThemeContainer(BaseModel):
    """Container holding multiple theme collections."""
    collections: List[ThemeCollection] = Field(default_factory=list)


class PageTheme(BaseModel):
    """Complete page theme with metadata and card collections."""
    header: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    container: ThemeContainer
    source_url: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str


# Error handling classes
class EdhrecError(Exception):
    """Custom error class for EDHREC operations."""
    
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for API responses."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details
        }
