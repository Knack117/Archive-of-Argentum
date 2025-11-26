"""Generate multiple OpenAPI documents for CustomGPT Actions.

This script splits the Archive-of-Argentum API into multiple OpenAPI JSON files,
each containing no more than 30 operations to comply with CustomGPT limits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from app import app
from aoa.routes import (
    cards, cedh, commanders, combos, deck_validation, 
    popular_decks, system, themes
)

# Define logical groupings of routes
ROUTE_GROUPS = {
    "system_cards": {
        "title": "Archive API – System & Cards",
        "description": "System status, health checks, and card search functionality including autocomplete, random cards, game changers, banned cards, and mass land destruction.",
        "routers": [system.router, cards.router],
        "priority_paths": [
            "/api/v1/status",
            "/api/v1/health", 
            "/api/v1/cards/search",
            "/api/v1/cards/autocomplete",
            "/api/v1/cards/random",
            "/api/v1/cards/gamechangers",
            "/api/v1/cards/banned",
            "/api/v1/cards/mass-land-destruction",
            "/api/v1/cards/{card_id}",
        ]
    },
    "commanders_combos": {
        "title": "Archive API – Commanders & Combos", 
        "description": "Commander information, summary data, and combo searches including early/late game combos and combo information.",
        "routers": [commanders.router, combos.router],
        "priority_paths": [
            "/api/v1/commanders/summary",
            "/api/v1/commanders/{commander_name}",
            "/api/v1/combos/commander/{commander_name}",
            "/api/v1/combos/search",
            "/api/v1/combos/early-game",
            "/api/v1/combos/late-game", 
            "/api/v1/combos/info",
        ]
    },
    "themes_deck_validation": {
        "title": "Archive API – Themes & Deck Validation",
        "description": "Theme-based deck building and comprehensive deck validation including salt checks, bracket information, and combo validation.",
        "routers": [themes.router, deck_validation.router],
        "priority_paths": [
            "/api/v1/themes/{theme_slug}",
            "/api/v1/tags/available",
            "/api/v1/tags/catalog", 
            "/api/v1/deck/commander-salt/{commander_name}",
            "/api/v1/deck/validate",
            "/api/v1/brackets/info",
            "/api/v1/salt/info",
            "/api/v1/deck/check-early-game-combos",
            "/api/v1/deck/check-late-game-combos",
            "/api/v1/deck/check-all-combos",
        ]
    },
    "popular_decks_cedh": {
        "title": "Archive API – Popular Decks & cEDH",
        "description": "Popular deck lists by bracket and competitive EDH (cEDH) data including commander stats and tournament information.",
        "routers": [popular_decks.router, cedh.router],
        "priority_paths": [
            "/api/v1/popular-decks",
            "/api/v1/popular-decks/info", 
            "/api/v1/popular-decks/{bracket}",
            "/api/v1/cedh/search",
            "/api/v1/cedh/commanders",
            "/api/v1/cedh/stats",
            "/api/v1/cedh/info",
        ]
    }
}

def create_api_for_group(group_name: str, group_config: Dict[str, Any]) -> Dict[str, Any]:
    """Create an OpenAPI schema for a specific group of routers."""
    
    # Create a temporary FastAPI app with only the selected routers
    group_app = FastAPI(
        title=group_config["title"],
        description=group_config["description"],
        version="1.1.0",  # Match the main app version
    )
    
    # Include only the routers for this group
    for router in group_config["routers"]:
        group_app.include_router(router)
    
    # Generate the OpenAPI schema
    openapi_schema = get_openapi(
        title=group_app.title,
        version=group_app.version,
        description=group_app.description,
        routes=group_app.routes,
    )
    
    # Add server configuration
    servers = openapi_schema.setdefault("servers", [])
    render_server = {
        "url": "https://mtg-mightstone-gpt.onrender.com",
        "description": "Render production deployment",
    }
    if render_server not in servers:
        servers.append(render_server)
    
    # Add security schemes
    security_schemes = openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    security_schemes.setdefault(
        "HTTPBearer",
        {
            "type": "http",
            "scheme": "bearer", 
            "bearerFormat": "API Key",
            "description": "All endpoints (except status, health, and root) require a Bearer API key.",
        },
    )
    
    # Apply security to non-public endpoints
    unsecured_paths = {"/", "/health", "/api/v1/status"}
    for path, methods in openapi_schema.get("paths", {}).items():
        if path in unsecured_paths:
            continue
        for method in methods.values():
            method.setdefault("security", [{"HTTPBearer": []}])
    
    # Limit operations to 30 if necessary
    _limit_operations_to_max(openapi_schema, group_config["priority_paths"])
    
    # Fix validation issues
    _fix_validation_issues(openapi_schema)
    
    return openapi_schema

def _fix_validation_issues(openapi_schema: Dict[str, Any]) -> None:
    """Fix common OpenAPI validation issues."""
    
    paths = openapi_schema.get("paths", {})
    
    # Fix mass-land-destruction description length
    mld_path = paths.get("/api/v1/cards/mass-land-destruction")
    if mld_path and mld_path.get("get"):
        mld_desc = mld_path["get"].get("description", "")
        if len(mld_desc) > 300:
            # Shorten the description to under 300 characters
            shortened_desc = (
                "Get Mass Land Destruction cards from Scryfall matching official MLD criteria. "
                "Returns cards that regularly destroy, exile, and bounce other lands, "
                "keep lands tapped, or change mana production by four or more lands per player."
            )
            mld_path["get"]["description"] = shortened_desc
    
    # Fix missing schema properties for status, root, and health endpoints
    problematic_endpoints = {"/api/v1/status", "/", "/health"}
    
    for endpoint in problematic_endpoints:
        endpoint_data = paths.get(endpoint)
        if endpoint_data:
            for method, method_data in endpoint_data.items():
                responses = method_data.get("responses", {})
                if "200" in responses:
                    content = responses["200"].get("content", {})
                    if "application/json" in content:
                        schema = content["application/json"].get("schema", {})
                        # Replace empty schema with proper schema definition
                        if (schema.get("additionalProperties") is True and 
                            "properties" not in schema):
                            schema.update({
                                "type": "object",
                                "title": schema.get("title", f"Response {endpoint.replace('/', '').title()}"),
                                "properties": {
                                    "message": {
                                        "type": "string",
                                        "description": "Response message"
                                    }
                                },
                                "required": ["message"]
                            })

def _limit_operations_to_max(openapi_schema: Dict[str, Any], priority_paths: List[str]) -> None:
    """Limit the number of operations in the schema to 30, prioritizing specified paths."""
    
    MAX_OPERATIONS = 30
    paths = openapi_schema.get("paths", {})
    if not paths:
        return
    
    operation_count = sum(len(methods) for methods in paths.values())
    if operation_count <= MAX_OPERATIONS:
        return
    
    # Start with prioritized paths
    selected_paths = []
    for priority_path in priority_paths:
        if priority_path in paths:
            selected_paths.append(priority_path)
        if len(selected_paths) >= MAX_OPERATIONS:
            break
    
    # Fill remaining slots with any other paths
    if len(selected_paths) < MAX_OPERATIONS:
        for path in paths:
            if path in selected_paths:
                continue
            selected_paths.append(path)
            if len(selected_paths) >= MAX_OPERATIONS:
                break
    
    # Update the paths in the schema
    openapi_schema["paths"] = {path: paths[path] for path in selected_paths if path in paths}

def main() -> None:
    """Generate multiple OpenAPI documents."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate multiple OpenAPI schemas for CustomGPT Actions")
    parser.add_argument("--verify", action="store_true", help="Verify generated schemas after creation")
    parser.add_argument("--output-dir", type=str, help="Output directory for generated files")
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir) if args.output_dir else Path(__file__).resolve().parents[1]
    
    print("Generating multiple OpenAPI schemas for CustomGPT Actions...")
    
    for group_name, group_config in ROUTE_GROUPS.items():
        print(f"\nGenerating {group_name}...")
        
        # Create the OpenAPI schema for this group
        schema = create_api_for_group(group_name, group_config)
        
        # Count operations for reporting
        operation_count = sum(len(methods) for methods in schema.get("paths", {}).values())
        
        # Save to JSON file
        output_file = output_dir / f"{group_name}.json"
        output_file.write_text(json.dumps(schema, indent=2))
        
        print(f"  ✓ Generated {group_name}.json ({operation_count} operations)")
        print(f"  ✓ Title: {group_config['title']}")
        print(f"  ✓ Description: {group_config['description']}")
    
    print(f"\n✅ All OpenAPI schemas generated successfully!")
    print(f"\nGenerated files:")
    for group_name in ROUTE_GROUPS.keys():
        print(f"  - {group_name}.json")
    
    print(f"\n📋 CustomGPT Action Configuration:")
    print(f"Create {len(ROUTE_GROUPS)} actions in CustomGPT, one for each JSON file.")
    print(f"Each action should use the corresponding JSON file as the api_spec.")
    print(f"All actions should point to: https://mtg-mightstone-gpt.onrender.com")
    
    if args.verify:
        print(f"\n🔍 Running verification...")
        try:
            from verify_schemas import main as verify_main
            verify_main()
        except ImportError:
            print("  ⚠️  Verification script not found, skipping verification")

if __name__ == "__main__":
    main()