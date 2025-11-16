"""Deck validation request/response models."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class DeckValidationRequest(BaseModel):
    """Request model for deck validation (simplified, no user-supplied sources)."""

    decklist: List[str] = Field(
        default_factory=list,
        description="List of card names in the deck. Useful for short requests.",
    )
    decklist_text: Optional[str] = Field(
        default=None,
        description=(
            "Optional multi-line decklist text blob. Each line should represent a card entry."
        ),
    )
    decklist_chunks: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional list of decklist text chunks. Use this when client payload limits require splitting "
            "a decklist into several strings."
        ),
    )
    commander: Optional[str] = Field(None, description="Commander name")
    target_bracket: Optional[str] = Field(
        None, description="Target bracket (exhibition, core, upgraded, optimized, cedh)"
    )
    validate_bracket: bool = Field(
        default=True, description="Validate against bracket rules"
    )
    validate_legality: bool = Field(
        default=True, description="Validate Commander format legality"
    )

    @model_validator(mode="after")
    def _ensure_decklist_present(self) -> "DeckValidationRequest":
        """Ensure that at least one decklist input method is provided."""
        has_direct_list = any(entry.strip() for entry in self.decklist)
        has_text_blob = bool(self.decklist_text and self.decklist_text.strip())
        has_chunks = bool(
            self.decklist_chunks
            and any(chunk and chunk.strip() for chunk in self.decklist_chunks)
        )

        if not (has_direct_list or has_text_blob or has_chunks):
            raise ValueError(
                "A decklist must be supplied via 'decklist', 'decklist_text', or 'decklist_chunks'."
            )

        return self


class DeckCard(BaseModel):
    """Individual card in deck with validation metadata."""

    name: str
    quantity: int = 1
    is_game_changer: bool = False
    bracket_categories: List[str] = Field(default_factory=list)
    legality_status: str = "unknown"
    validation_issues: List[str] = Field(default_factory=list)


class BracketValidation(BaseModel):
    """Bracket validation results."""

    target_bracket: str
    overall_compliance: bool
    bracket_score: int = Field(
        ..., ge=1, le=5, description="Bracket confidence score"
    )
    compliance_details: Dict[str, Any] = Field(default_factory=dict)
    violations: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class DeckValidationResponse(BaseModel):
    """Complete deck validation response."""

    success: bool
    deck_summary: Dict[str, Any]
    cards: List[DeckCard]
    bracket_validation: Optional[BracketValidation]
    legality_validation: Dict[str, Any]
    validation_timestamp: str
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    salt_scores: Dict[str, Any] = Field(default_factory=dict)
