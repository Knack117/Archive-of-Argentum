"""Theme and tag response models."""
from typing import Dict, List, Optional

from pydantic import BaseModel


class ThemeItem(BaseModel):
    card_name: str
    inclusion_percentage: str
    synergy_percentage: str


class ThemeCollection(BaseModel):
    header: str
    items: List[ThemeItem]


class ThemeContainer(BaseModel):
    collections: List[ThemeCollection]


class PageTheme(BaseModel):
    header: str
    description: str
    tags: List[str]
    container: ThemeContainer
    source_url: str
    error: Optional[str] = None
