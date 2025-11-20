"""Response models for API endpoints."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GameChangerResponse(BaseModel):
    """Response model for game changer cards endpoint."""
    success: bool = Field(True, description="Operation success status")
    data: List[Dict[str, Any]] = Field(..., description="List of game changer cards")
    count: int = Field(..., description="Number of cards returned")
    source: str = Field("scryfall", description="Data source")
    description: str = Field("Commander Game Changer cards sorted by USD price", description="Endpoint description")
    query: str = Field("is:gamechanger", description="Search query used")
    order: str = Field("usd", description="Sort order")
    direction: str = Field("desc", description="Sort direction")
    timestamp: str = Field(..., description="Response timestamp")


class BannedCardsResponse(BaseModel):
    """Response model for banned cards endpoint."""
    success: bool = Field(True, description="Operation success status")
    data: List[Dict[str, Any]] = Field(..., description="List of banned cards")
    count: int = Field(..., description="Number of cards returned")
    source: str = Field("scryfall", description="Data source")
    description: str = Field("Cards banned in Commander format", description="Endpoint description")
    query: str = Field("banned:commander", description="Search query used")
    order: str = Field("name", description="Sort order")
    direction: str = Field("asc", description="Sort direction")
    timestamp: str = Field(..., description="Response timestamp")


class MassLandDestructionResponse(BaseModel):
    """Response model for mass land destruction cards endpoint."""
    success: bool = Field(True, description="Operation success status")
    data: List[Dict[str, Any]] = Field(..., description="List of MLD cards")
    count: int = Field(..., description="Number of cards returned")
    source: str = Field("scryfall", description="Data source")
    description: str = Field("Mass Land Denial cards as defined by Wizards of the Coast", description="Endpoint description")
    definition: str = Field("Cards that regularly destroy, exile, and bounce other lands, keep lands tapped, or change what mana is produced by four or more lands per player without replacing them.", description="MLD definition")
    note: str = Field("Data sourced from Scryfall using multiple search queries to match MLD criteria", description="Data source note")
    timestamp: str = Field(..., description="Response timestamp")


class ComboCheckResponse(BaseModel):
    """Response model for combo checking endpoints."""
    card_names: List[str] = Field(..., description="Input card names")
    combos_found: List[Dict[str, Any]] = Field(default_factory=list, description="Combos found in deck")
    total_combos: int = Field(0, description="Total number of combos found")
    bracket_acceptable: Dict[str, bool] = Field(default_factory=dict, description="Bracket acceptability results")
    timestamp: str = Field(..., description="Response timestamp")


class AutocompleteResponse(BaseModel):
    """Response model for autocomplete endpoint."""
    object: str = Field("list", description="Response object type")
    data: List[str] = Field(..., description="List of card name suggestions")


class PopularDecksResponse(BaseModel):
    """Response model for popular decks endpoints."""
    success: bool = Field(True, description="Operation success status")
    data: List[Dict[str, Any]] = Field(..., description="List of popular decks")
    count: int = Field(..., description="Number of decks returned")
    source: str = Field("moxfield+archidekt", description="Data sources")
    description: str = Field("Top most-viewed Commander decks from Moxfield and Archidekt", description="Endpoint description")
    bracket: Optional[str] = Field(None, description="Bracket filter applied")
    timestamp: str = Field(..., description="Response timestamp")


class PopularDecksInfoResponse(BaseModel):
    """Response model for popular decks info endpoint."""
    description: str = Field("Fetch top most-viewed Commander decks from Moxfield and Archidekt", description="Endpoint description")
    supported_brackets: List[str] = Field(["exhibition", "core", "upgraded", "optimized", "cedh"], description="Supported bracket values")
    usage_examples: Dict[str, str] = Field(default_factory=dict, description="Usage examples")
    timestamp: str = Field(..., description="Response timestamp")


class CEDHSearchResponse(BaseModel):
    """Response model for cEDH search endpoint."""
    success: bool = Field(True, description="Operation success status")
    data: List[Dict[str, Any]] = Field(..., description="List of cEDH decks")
    count: int = Field(..., description="Number of decks returned")
    filters_applied: Dict[str, Any] = Field(default_factory=dict, description="Filters that were applied")
    timestamp: str = Field(..., description="Response timestamp")


class BracketsInfoResponse(BaseModel):
    """Response model for brackets info endpoint."""
    brackets: Dict[str, Dict[str, Any]] = Field(..., description="Bracket information")
    description: str = Field("Commander Brackets system information", description="Endpoint description")
    timestamp: str = Field(..., description="Response timestamp")


class SaltInfoResponse(BaseModel):
    """Response model for salt info endpoint."""
    cache_stats: Dict[str, Any] = Field(..., description="Cache statistics")
    total_cards: int = Field(..., description="Total cards in cache")
    last_updated: str = Field(..., description="Last cache update timestamp")
    description: str = Field("Salt score cache information", description="Endpoint description")


class CommanderSaltResponse(BaseModel):
    """Response model for commander salt endpoint."""
    commander_name: str = Field(..., description="Commander name")
    salt_score: float = Field(..., description="Commander salt score")
    rank: Optional[int] = Field(None, description="Salt rank")
    timestamp: str = Field(..., description="Response timestamp")