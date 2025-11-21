"""Commander identity utilities - matching the sophisticated approach from the other repository."""
import re
from typing import Dict, List, Optional, Set, Tuple


def normalize_commander_name(name: str) -> Tuple[str, str, str]:
    """Normalize commander name to display name, slug, and EDHREC URL.
    
    Returns:
        Tuple of (display_name, slug, edhrec_url)
    """
    if not name:
        raise ValueError("Commander name is required")
    
    # Clean up the name
    display_name = name.strip()
    
    # Generate slug for EDHREC URL
    slug = _generate_commander_slug(display_name)
    
    # Construct EDHREC URL
    edhrec_url = f"https://edrez.com/commanders/{slug}"
    
    return display_name, slug, edhrec_url


def _generate_commander_slug(name: str) -> str:
    """Generate EDHREC-compatible slug from commander name."""
    if not name:
        return ""
    
    # Convert to lowercase and strip
    normalized = name.lower().strip()
    
    # Handle special cases
    # Remove quotes and commas
    normalized = re.sub(r'["\']', "", normalized)
    normalized = re.sub(r'[,]', "-", normalized)
    
    # Handle multi-word names with spaces/hyphens
    normalized = re.sub(r'[\s]+', '-', normalized)
    
    # Handle MDFC cards with "//"
    normalized = normalized.replace('//', '-')
    
    # Handle "The" prefix
    if normalized.startswith('the '):
        normalized = normalized[4:]
    
    # Clean up multiple consecutive hyphens
    normalized = re.sub(r'-+', '-', normalized)
    
    # Remove leading/trailing hyphens
    normalized = normalized.strip('-')
    
    # Handle specific commander patterns
    commander_slug_mapping = {
        'akiri, line-slinger': 'akiri-line-slinger',
        'jeska, thrice-reborn': 'jeska-thrice-reborn',
        'kraum, ludi vek': 'kraum-ludi-vek',
        'thrasios, triton hero': 'thrasios-triton-hero',
        'vial smasher the fierce': 'vial-smasher-the-fierce',
    }
    
    if normalized in commander_slug_mapping:
        return commander_slug_mapping[normalized]
    
    return normalized


def get_commander_slug_candidates(name: str) -> List[str]:
    """Generate multiple slug candidates for commander name discovery."""
    if not name:
        return []
    
    candidates = []
    
    # Basic normalized slug
    basic_slug = _generate_commander_slug(name)
    if basic_slug:
        candidates.append(basic_slug)
    
    # Handle "The" prefix variations
    if not name.lower().startswith('the ') and not basic_slug.startswith('the'):
        the_slug = f"the-{basic_slug}"
        candidates.append(the_slug)
    
    # Handle partner commanders
    if ', ' in name:
        # Split by comma and create variations
        parts = [part.strip() for part in name.split(',')]
        if len(parts) == 2:
            # Create partner name variations
            partner_variations = [
                f"{parts[0]}-{parts[1]}",
                f"{parts[1]}-{parts[0]}",
                parts[0].lower().replace(' ', '-'),
                parts[1].lower().replace(' ', '-'),
            ]
            candidates.extend(partner_variations)
    
    # Handle MDFC cards
    if ' // ' in name:
        main_name = name.split(' // ')[0].strip()
        main_slug = _generate_commander_slug(main_name)
        if main_slug and main_slug not in candidates:
            candidates.append(main_slug)
    
    # Add common variations
    common_variations = []
    if basic_slug:
        common_variations.extend([
            basic_slug.replace('-', ' ').title().replace(' ', '-'),
            basic_slug.replace('-', ' ').title(),
        ])
    
    candidates.extend(common_variations)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_candidates = []
    for candidate in candidates:
        if candidate.lower() not in seen:
            seen.add(candidate.lower())
            unique_candidates.append(candidate)
    
    return unique_candidates


def extract_color_identity(name: str) -> List[str]:
    """Extract color identity from commander name (simplified)."""
    if not name:
        return []
    
    # This is a simplified implementation
    # In the other repository, this uses more sophisticated card data
    name_lower = name.lower()
    
    colors = []
    color_map = {
        'w': 'white', 'white': 'white',
        'u': 'blue', 'blue': 'blue', 'island': 'blue',
        'b': 'black', 'black': 'black', 'swamp': 'black',
        'r': 'red', 'red': 'red', 'mountain': 'red',
        'g': 'green', 'green': 'green', 'forest': 'green',
    }
    
    for color_code, color_name in color_map.items():
        if color_code in name_lower or color_name in name_lower:
            colors.append(color_name)
    
    return colors
