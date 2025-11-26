# Multiple Actions Implementation for CustomGPT

## Overview

This implementation splits the Archive-of-Argentum API into multiple OpenAPI JSON files to comply with CustomGPT's 30-endpoint limit per action. The API has been divided into 4 logical groups, each containing specific functionality.

## Generated Files

The following OpenAPI schema files have been generated:

1. **system_cards.json** (10 operations)
   - **Purpose**: System status, health checks, and card search functionality
   - **Endpoints**: Status, health, card search, autocomplete, random cards, game changers, banned cards, mass land destruction, card details

2. **commanders_combos.json** (10 operations)
   - **Purpose**: Commander information and combo searches
   - **Endpoints**: Commander summary, commander details, combos by commander, combo search, early/late game combos, combo information

3. **themes_deck_validation.json** (16 operations)
   - **Purpose**: Theme-based deck building and comprehensive deck validation
   - **Endpoints**: Themes, tags catalog, deck validation, salt checks, bracket information, combo validation

4. **popular_decks_cedh.json** (7 operations)
   - **Purpose**: Popular deck lists and competitive EDH data
   - **Endpoints**: Popular decks by bracket, cEDH search, commanders, stats, and information

**Total Operations**: 43 endpoints across 4 actions (all within the 30-operation limit per action)

## CustomGPT Configuration

### Step 1: Create Actions in CustomGPT

For each JSON file, create a separate action in your CustomGPT configuration:

#### Action 1: System & Cards
- **Action Name**: `Archive API - System & Cards`
- **Description**: Use this action for system status checks and card search functionality including autocomplete, random cards, game changers, banned cards, and mass land destruction.
- **API Specification**: Upload `system_cards.json`
- **Server URL**: `https://mtg-mightstone-gpt.onrender.com`

#### Action 2: Commanders & Combos  
- **Action Name**: `Archive API - Commanders & Combos`
- **Description**: Use this action for commander information and combo searches including early/late game combos and detailed combo information.
- **API Specification**: Upload `commanders_combos.json`
- **Server URL**: `https://mtg-mightstone-gpt.onrender.com`

#### Action 3: Themes & Deck Validation
- **Action Name**: `Archive API - Themes & Deck Validation`
- **Description**: Use this action for theme-based deck building and comprehensive deck validation including salt checks, bracket information, and combo validation.
- **API Specification**: Upload `themes_deck_validation.json`
- **Server URL**: `https://mtg-mightstone-gpt.onrender.com`

#### Action 4: Popular Decks & cEDH
- **Action Name**: `Archive API - Popular Decks & cEDH`
- **Description**: Use this action for popular deck lists by bracket and competitive EDH (cEDH) data including commander stats and tournament information.
- **API Specification**: Upload `popular_decks_cedh.json`
- **Server URL**: `https://mtg-mightstone-gpt.onrender.com`

### Step 2: Configure Authentication

All actions should use the same authentication configuration:
- **Authentication Type**: Bearer Token
- **Token**: Your API key for the Archive-of-Argentum service

### Step 3: Test Each Action

Verify that each action can successfully call its designated endpoints:

#### Test Endpoints for Each Action:

**System & Cards Action:**
- `GET /api/v1/status` - Check API status
- `POST /api/v1/cards/search` - Search for cards
- `GET /api/v1/cards/random` - Get random cards

**Commanders & Combos Action:**
- `GET /api/v1/commanders/summary` - Get commanders summary
- `POST /api/v1/combos/search` - Search combos
- `GET /api/v1/combos/early-game` - Get early game combos

**Themes & Deck Validation Action:**
- `GET /api/v1/themes/{theme_slug}` - Get theme information
- `POST /api/v1/deck/validate` - Validate a deck
- `GET /api/v1/deck/commander-salt/{commander_name}` - Check commander salt

**Popular Decks & cEDH Action:**
- `GET /api/v1/popular-decks` - Get popular decks
- `POST /api/v1/cedh/search` - Search cEDH data
- `GET /api/v1/cedh/commanders` - Get cEDH commanders

## Implementation Details

### How the Splitting Works

The implementation uses FastAPI's `get_openapi()` function to generate separate OpenAPI schemas for each logical group of routes:

```python
def create_api_for_group(group_name: str, group_config: Dict[str, Any]) -> Dict[str, Any]:
    # Create a temporary FastAPI app with only selected routers
    group_app = FastAPI(title=group_config["title"], description=group_config["description"])
    
    # Include only the routers for this group
    for router in group_config["routers"]:
        group_app.include_router(router)
    
    # Generate the OpenAPI schema
    openapi_schema = get_openapi(title=group_app.title, routes=group_app.routes)
    
    # Add security and server configuration
    # ...
    
    return openapi_schema
```

### Route Groupings

The routes are grouped logically to ensure related functionality is together:

- **System & Cards**: Core system endpoints + card-related functionality
- **Commanders & Combos**: Commander data + combo mechanics
- **Themes & Deck Validation**: Advanced deck building features
- **Popular Decks & cEDH**: Meta and competitive data

### Security Configuration

Each schema includes:
- Bearer token authentication for protected endpoints
- Public access for status/health endpoints
- Consistent server URLs pointing to the Render deployment

## Maintenance

### Regenerating Schemas

If you modify the API routes, regenerate the schemas:

```bash
cd Archive-of-Argentum
python scripts/generate_multiple_openapi.py
```

### Verification

Verify the schemas are valid and within limits:

```bash
python scripts/verify_schemas.py
```

### Adding New Routes

To add new routes:

1. Add the route to the appropriate router file in `aoa/routes/`
2. Include the router in the appropriate group in `scripts/generate_multiple_openapi.py`
3. Regenerate the schemas
4. Update the CustomGPT actions if needed

## Benefits

✅ **Compliance**: All schemas respect the 30-endpoint limit
✅ **Logical Grouping**: Related functionality is grouped together
✅ **Easy Management**: Clear separation of concerns
✅ **Maintainable**: Easy to regenerate and update
✅ **Scalable**: Can add more groups if the API grows

## Troubleshooting

### Common Issues

1. **Schema Validation Errors**: Ensure all JSON files are valid OpenAPI 3.1 schemas
2. **Authentication Failures**: Verify the Bearer token is correctly configured
3. **Missing Endpoints**: Check that the route is included in the correct group
4. **Operation Limit Exceeded**: Review the grouping and consider further splitting

### Monitoring

- Check Render logs for request/response details
- Monitor CustomGPT action usage and success rates
- Validate schema changes don't break existing functionality

---

**Generated on**: 2025-11-27
**Total Operations**: 43
**Actions Created**: 4
**Maximum Operations per Action**: 30