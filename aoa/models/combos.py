"""Commander Spellbook combo response models."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ComboCard(BaseModel):
    name: str
    image_url: Optional[str] = None


class ComboResult(BaseModel):
    combo_id: str
    name: str
    identity: str
    cards: List[ComboCard]
    produces: List[str]
    requires: List[str]
    salt_score: Optional[float] = None
    edhrec_salt_link: Optional[str] = None


class ComboSearchResponse(BaseModel):
    success: bool
    total_results: int
    results: List[ComboResult]
    source_url: str
    timestamp: str
    warnings: List[str] = []
