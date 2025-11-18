"""Commander summary and average deck response models."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CommanderCard(BaseModel):
    name: Optional[str] = None
    num_decks: Optional[int] = None
    potential_decks: Optional[int] = None
    inclusion_percentage: Optional[float] = None
    synergy_percentage: Optional[float] = None
    sanitized_name: Optional[str] = None
    card_url: Optional[str] = None


class CommanderTag(BaseModel):
    tag: Optional[str] = None
    count: Optional[int] = None
    link: Optional[str] = None


class CommanderCombo(BaseModel):
    combo: Optional[str] = None
    url: Optional[str] = None


class SimilarCommander(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None


class CommanderSummary(BaseModel):
    commander_name: str
    commander_url: Optional[str] = None
    timestamp: Optional[str] = None
    commander_tags: List[str] = Field(default_factory=list)
    top_10_tags: List[CommanderTag] = Field(default_factory=list)
    all_tags: List[CommanderTag] = Field(default_factory=list)
    combos: List[CommanderCombo] = Field(default_factory=list)
    similar_commanders: List[SimilarCommander] = Field(default_factory=list)
    categories: Dict[str, List[CommanderCard]] = Field(default_factory=dict)


class AverageDeckResponse(BaseModel):
    commander: CommanderSummary
    deck_stats: Dict[str, Any]
    timestamp: str
