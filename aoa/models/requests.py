"""Request models for API endpoints."""

from typing import List
from pydantic import BaseModel, Field


class ComboCheckRequest(BaseModel):
    """Request model for combo checking endpoints."""
    card_names: List[str] = Field(..., description="List of card names to check for combos")


class DeckComboCheckRequest(BaseModel):
    """Request model for deck combo checking endpoints with flexible format support."""
    card_names: List[str] = Field(..., description="List of card names to check for combos")