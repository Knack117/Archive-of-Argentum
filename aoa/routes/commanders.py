"""Commander summary and average deck endpoints."""
import asyncio
import logging
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query

from aoa.constants import EDHREC_BASE_URL
from aoa.models import CommanderCard, CommanderCombo, CommanderSummary, CommanderTag, SimilarCommander
from aoa.security import verify_api_key
from aoa.services.commanders import (
    extract_commander_name_from_url,
    normalize_commander_name,
    scrape_edhrec_commander_page,
)

router = APIRouter(prefix="/api/v1", tags=["commanders"])
logger = logging.getLogger(__name__)


@router.get("/commander/summary", response_model=CommanderSummary)
async def get_commander_summary(
    name: Optional[str] = Query(None, description="Commander name"),
    commander_url: Optional[str] = Query(None, description="EDHRec commander URL"),
    limit: int = Query(
        40,
        ge=1,
        le=200,
        description="Maximum cards per category (default: 40 for GPT compatibility)"
    ),
    categories: Optional[str] = Query(
        None,
        description="Comma-separated category filters (e.g., 'creatures,instants,enchantments'). "
                   "Supports: creatures, instants, sorceries, artifacts, enchantments, planeswalkers, "
                   "lands, highsynergy, topcards, newcards"
    ),
    mode: str = Query(
        "standard",
        regex="^(standard|compact)$",
        description="Response mode: 'standard' (full data) or 'compact' (minimal data)"
    ),
    api_key: str = Depends(verify_api_key),
) -> CommanderSummary:
    """Fetch EDHRec commander summary data with pagination and filtering.
    
    GPT compatibility notes:
    - Default limit (40 cards/category) keeps responses within GPT limits
    - Filter categories to reduce response size further
    - Use compact mode for minimal responses
    
    Examples:
    - Basic: `?name=halana-kessig-ranger`
    - Limited: `?name=halana&limit=30`
    - Filtered: `?name=halana&categories=creatures,instants,enchantments`
    - Compact: `?name=halana&mode=compact&limit=20`
    """
    logger.info(f"Commander summary endpoint accessed with params: name={name}, commander_url={commander_url}, limit={limit}, categories={categories}, mode={mode}")
    
    # Add timeout wrapper for commander data fetching
    try:
        # Use asyncio.wait_for to limit total execution time
        commander_data = await asyncio.wait_for(
            _fetch_commander_data(name, commander_url, limit, categories, mode),
            timeout=25.0  # 25 second total timeout
        )
    except asyncio.TimeoutError:
        logger.warning(f"Commander summary timeout for {name or commander_url}")
        raise HTTPException(
            status_code=504,
            detail="Request timed out while fetching commander data from EDHRec. Please try again later."
        )
    
async def _fetch_commander_data(name, commander_url, limit, categories, mode):
    """Internal function to fetch commander data with better error handling."""
    if name:
        slug = normalize_commander_name(name)
    elif commander_url:
        parsed_name = extract_commander_name_from_url(commander_url)
        slug = normalize_commander_name(parsed_name)
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either 'name' or 'commander_url'",
        )

    commander_url_val = f"{EDHREC_BASE_URL}commanders/{slug}"

    # Parse categories filter
    categories_filter: Optional[Set[str]] = None
    if categories:
        # Normalize category names (remove spaces, lowercase)
        categories_filter = {
            cat.strip().lower().replace(" ", "").replace("-", "")
            for cat in categories.split(",")
            if cat.strip()
        }

    # Determine compact mode
    compact_mode = (mode == "compact")

    # Fetch commander data with filters
    commander_data = await scrape_edhrec_commander_page(
        commander_url_val,
        limit_per_category=limit,
        categories_filter=categories_filter,
        compact_mode=compact_mode
    )
    
    return commander_data

    categories_output: Dict[str, List[CommanderCard]] = {}
    for category_key, category_data in commander_data.get("categories", {}).items():
        if not isinstance(category_data, dict):
            continue
        cards_data = category_data.get("cards", [])
        card_objects: List[CommanderCard] = []
        for card in cards_data:
            if isinstance(card, dict):
                card_objects.append(
                    CommanderCard(
                        name=card.get("name"),
                        num_decks=card.get("num_decks"),
                        potential_decks=card.get("potential_decks"),
                        inclusion_percentage=card.get("inclusion_percentage"),
                        synergy_percentage=card.get("synergy_percentage"),
                        sanitized_name=card.get("sanitized_name"),
                        card_url=card.get("card_url"),
                    )
                )
        if card_objects:
            categories_output[category_key] = card_objects

    all_tags_output: List[CommanderTag] = []
    for tag_data in commander_data.get("all_tags", []):
        if isinstance(tag_data, dict):
            all_tags_output.append(
                CommanderTag(
                    tag=tag_data.get("tag"),
                    count=tag_data.get("count"),
                    link=tag_data.get("url"),
                )
            )

    combos_output: List[CommanderCombo] = []
    for combo_data in commander_data.get("combos", []):
        if isinstance(combo_data, dict):
            combos_output.append(
                CommanderCombo(
                    combo=combo_data.get("name"),
                    url=combo_data.get("url"),
                )
            )

    similar_commanders_output: List[SimilarCommander] = []
    for sim_cmd in commander_data.get("similar_commanders", []):
        if isinstance(sim_cmd, dict):
            similar_commanders_output.append(
                SimilarCommander(
                    name=sim_cmd.get("name"),
                    url=sim_cmd.get("url"),
                )
            )

    top_10_tags_output: List[CommanderTag] = []
    for tag_data in commander_data.get("top_10_tags", []):
        if isinstance(tag_data, dict):
            top_10_tags_output.append(
                CommanderTag(
                    tag=tag_data.get("tag"),
                    count=tag_data.get("count"),
                    link=tag_data.get("url"),
                )
            )

    return CommanderSummary(
        commander_name=commander_data.get("commander_name", ""),
        commander_url=commander_data.get("commander_url"),
        timestamp=commander_data.get("timestamp"),
        commander_tags=commander_data.get("commander_tags", []),
        top_10_tags=top_10_tags_output,
        all_tags=all_tags_output,
        combos=combos_output,
        similar_commanders=similar_commanders_output,
        categories=categories_output,
    )


@router.get("/average_deck/summary", response_model=CommanderSummary)
async def get_average_deck_summary(
    commander_name: Optional[str] = Query(None),
    commander_slug: Optional[str] = Query(None),
    bracket: Optional[str] = Query(
        None,
        description="Bracket type: exhibition, core, upgraded, optimized, or cedh.",
    ),
    limit: int = Query(
        40,
        ge=1,
        le=200,
        description="Maximum cards per category (default: 40 for GPT compatibility)"
    ),
    categories: Optional[str] = Query(
        None,
        description="Comma-separated category filters (e.g., 'creatures,instants,enchantments')"
    ),
    mode: str = Query(
        "standard",
        regex="^(standard|compact)$",
        description="Response mode: 'standard' (full data) or 'compact' (minimal data)"
    ),
    api_key: str = Depends(verify_api_key),
) -> CommanderSummary:
    """Fetch a summary of an EDHRec Average Deck page for a given commander."""
    if not commander_name and not commander_slug:
        raise HTTPException(
            status_code=400,
            detail="You must provide either 'commander_name' or 'commander_slug'.",
        )

    if commander_slug:
        slug = commander_slug.strip().lower()
    else:
        slug = normalize_commander_name(commander_name or "")

    base_url = f"{EDHREC_BASE_URL}average-decks/{slug}"
    if bracket:
        base_url += f"/{bracket.strip().lower()}"

    # Parse categories filter
    categories_filter: Optional[Set[str]] = None
    if categories:
        categories_filter = {
            cat.strip().lower().replace(" ", "").replace("-", "")
            for cat in categories.split(",")
            if cat.strip()
        }

    compact_mode = (mode == "compact")

    try:
        commander_data = await scrape_edhrec_commander_page(
            base_url,
            limit_per_category=limit,
            categories_filter=categories_filter,
            compact_mode=compact_mode
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error fetching average deck summary for %s: %s", slug, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch average deck summary: {exc}",
        )

    categories_output: Dict[str, List[CommanderCard]] = {}
    for category_key, category_data in commander_data.get("categories", {}).items():
        if not isinstance(category_data, dict):
            continue
        cards_data = category_data.get("cards", [])
        card_objects: List[CommanderCard] = []
        for card in cards_data:
            if isinstance(card, dict):
                card_objects.append(
                    CommanderCard(
                        name=card.get("name"),
                        num_decks=card.get("num_decks"),
                        potential_decks=card.get("potential_decks"),
                        inclusion_percentage=card.get("inclusion_percentage"),
                        synergy_percentage=card.get("synergy_percentage"),
                        sanitized_name=card.get("sanitized_name"),
                        card_url=card.get("card_url"),
                    )
                )
        if card_objects:
            categories_output[category_key] = card_objects

    all_tags_output: List[CommanderTag] = []
    for tag_data in commander_data.get("all_tags", []):
        if isinstance(tag_data, dict):
            all_tags_output.append(
                CommanderTag(
                    tag=tag_data.get("tag"),
                    count=tag_data.get("count"),
                    link=tag_data.get("url"),
                )
            )

    combos_output: List[CommanderCombo] = []
    for combo_data in commander_data.get("combos", []):
        if isinstance(combo_data, dict):
            combos_output.append(
                CommanderCombo(
                    combo=combo_data.get("name"),
                    url=combo_data.get("url"),
                )
            )

    similar_commanders_output: List[SimilarCommander] = []
    for sim_cmd in commander_data.get("similar_commanders", []):
        if isinstance(sim_cmd, dict):
            similar_commanders_output.append(
                SimilarCommander(
                    name=sim_cmd.get("name"),
                    url=sim_cmd.get("url"),
                )
            )

    top_10_tags_output: List[CommanderTag] = []
    for tag_data in commander_data.get("top_10_tags", []):
        if isinstance(tag_data, dict):
            top_10_tags_output.append(
                CommanderTag(
                    tag=tag_data.get("tag"),
                    count=tag_data.get("count"),
                    link=tag_data.get("url"),
                )
            )

    return CommanderSummary(
        commander_name=commander_data.get("commander_name", ""),
        commander_url=commander_data.get("commander_url"),
        timestamp=commander_data.get("timestamp"),
        commander_tags=commander_data.get("commander_tags", []),
        top_10_tags=top_10_tags_output,
        all_tags=all_tags_output,
        combos=combos_output,
        similar_commanders=similar_commanders_output,
        categories=categories_output,
    )
