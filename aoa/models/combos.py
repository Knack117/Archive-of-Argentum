"""Commander Spellbook combo response models."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ComboResult(BaseModel):
    """Serialized representation of a Commander Spellbook combo."""

    combo_id: Optional[str] = None
    combo_name: Optional[str] = None
    color_identity: List[str] = Field(default_factory=list)
    cards_in_combo: List[str] = Field(default_factory=list)
    results_in_combo: List[str] = Field(default_factory=list)
    decks_edhrec: Optional[int] = None
    variants: Optional[int] = None
    combo_url: Optional[str] = None
    price_info: Dict[str, Any] = Field(default_factory=dict)


class ComboSearchResponse(BaseModel):
    """Envelope describing combo search API responses."""

    success: bool
    commander_name: Optional[str] = None
    search_query: Optional[str] = None
    total_results: int
    results: List[ComboResult]
    source_url: str
    timestamp: str
    warnings: List[str] = Field(default_factory=list)
