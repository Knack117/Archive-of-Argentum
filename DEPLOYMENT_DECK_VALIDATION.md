# Deck Validation Endpoint - Deployment Guide

## Overview

This guide explains how to deploy the new deck validation endpoint to your existing MTG Mightstone GPT Render application. The endpoint provides comprehensive Commander Brackets validation, format legality checking, and integration with EDHRec data.

## New Features Added

### 1. Deck Validation Endpoint (`/api/v1/deck/validate`)
- Validates deck against Commander Brackets rules (October 2025 update)
- Checks commander format legality
- Bundles the latest Commander Brackets reference data
- References EDHRec combo lists
- Provides detailed compliance scoring and recommendations

### 2. Bracket Information Endpoints
- `/api/v1/brackets/info` - Complete bracket definitions and expectations
- `/api/v1/brackets/game-changers/list` - Current Game Changers list with recent removals

### 3. Commander Brackets Data Integration
- Official bracket definitions from October 21, 2025 update
- Current Game Changers list
- Curated mass land denial cards
- Early game 2-card combos from EDHRec

## Installation Steps

### 1. Update Dependencies
Add to your `requirements.txt`:
```txt
# Additional dependencies for validation (should already be installed)
httpx>=0.25.0
beautifulsoup4>=4.11.0
lxml>=4.9.0
```

### 2. Deploy to Render

#### Option A: Git-based Deployment
```bash
# In your Render dashboard:
# 1. Connect your GitHub repository
# 2. Build command: pip install -r requirements.txt
# 3. Start command: uvicorn app:app --host 0.0.0.0 --port $PORT
# 4. Set environment variable: API_KEY=your-secure-api-key
```

#### Option B: Manual Deployment
```bash
# Clone repository locally
git clone https://github.com/Knack117/Archive-of-Argentum.git
cd Archive-of-Argentum

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export API_KEY="your-secure-api-key"
export ENVIRONMENT="production"
export PORT=8000

# Deploy using Render CLI (install with: npm install -g @render/cli)
render deploy --service mtg-mightstone-gpt --env production
```

### 3. Environment Variables
Set these in your Render dashboard:
```
API_KEY=your-secure-api-key
ENVIRONMENT=production
PORT=8000
LOG_LEVEL=INFO
```

## API Usage Examples

### 1. Validate a Deck

```bash
curl -X POST "https://mtg-mightstone-gpt.onrender.com/api/v1/deck/validate" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "decklist": [
      "1x Sol Ring",
      "1x Demonic Consultation",
      "1x Thassa''s Oracle",
      "4x Lightning Bolt",
      "1x Counterspell",
      "97x Island"
    ],
    "commander": "Jace, Wielder of Mysteries",
    "target_bracket": "optimized",
    "source_urls": [
      "https://archiveofargentum.com/reference/game-changers",
      "https://edhrec.com/combos/early-game-2-card-combos"
    ],
    "validate_bracket": true,
    "validate_legality": true
  }'
```

#### Handling Large Decklists

Some GPT connectors limit how many individual array items can be submitted at once. The validation endpoint now accepts two addi
tional helpers so you can keep the payload small:

- `decklist_text`: Send the full decklist as a newline-delimited string
- `decklist_chunks`: Send a list of newline-delimited text blobs when you must split the payload into multiple pieces

Example using chunks:

```bash
curl -X POST "https://mtg-mightstone-gpt.onrender.com/api/v1/deck/validate" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "decklist_chunks": [
      "1x Light-Paws, Emperor\'s Voice\n1x Esper Sentinel\n1x Sol Ring",
      "1x Daybreak Coronet\n1x Shield of Duty and Reason\n1x Swiftfoot Boots"
    ],
    "commander": "Light-Paws, Emperor\'s Voice",
    "target_bracket": "optimized"
  }'
```

### 2. Get Brackets Information

```bash
curl -X GET "https://mtg-mightstone-gpt.onrender.com/api/v1/brackets/info" \\
  -H "Authorization: Bearer YOUR_API_KEY"
```

### 3. Get Game Changers List

```bash
curl -X GET "https://mtg-mightstone-gpt.onrender.com/api/v1/brackets/game-changers/list" \\
  -H "Authorization: Bearer YOUR_API_KEY"
```

## Integration with GPT

### Python Example
```python
import httpx
import json

async def validate_deck_with_gpt(decklist, commander, target_bracket):
    """Use the API to validate a GPT-generated deck"""
    
    headers = {
        "Authorization": "Bearer YOUR_API_KEY",
        "Content-Type": "application/json"
    }
    
    payload = {
        "decklist": decklist,
        "commander": commander,
        "target_bracket": target_bracket,
        "validate_bracket": True,
        "validate_legality": True,
        "source_urls": [
            "https://archiveofargentum.com/reference/mass-land-denial",
            "https://archiveofargentum.com/reference/game-changers",
            "https://edhrec.com/combos/early-game-2-card-combos"
        ]
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://mtg-mightstone-gpt.onrender.com/api/v1/deck/validate",
            headers=headers,
            json=payload
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Validation failed: {response.status_code}")
```

### GPT Integration Prompt
```
You are helping build a Magic: The Gathering Commander deck. When I provide you with a decklist, 
please use the MTG Mightstone GPT API to validate it against the Commander Brackets system.

API endpoint: https://mtg-mightstone-gpt.onrender.com/api/v1/deck/validate
Required: Authorization header with API key

Example validation request:
{
  "decklist": ["1x Sol Ring", "1x Lightning Bolt", ...],
  "commander": "Commander Name",
  "target_bracket": "upgraded",
  "validate_bracket": true,
  "validate_legality": true
}

The API will return:
- Overall bracket compliance
- Format legality check
- Detailed recommendations
- Game changers detected
- Power level analysis
```

## Features and Validation Rules

### Bracket Validation
- **Exhibition (1)**: Theme over power, minimal game changers
- **Core (2)**: Unoptimized play, limited tutors, few early combos  
- **Upgraded (3)**: Strong synergy, standard combos allowed
- **Optimized (4)**: Fast, efficient decks with tutors and game changers
- **cEDH (5)**: All cards and strategies allowed

### Format Legality Checks
- 99-card deck requirement
- Commander color identity compliance
- Banned card detection
- Basic format rules validation

### Reference Data Integration
- **Commander Brackets Reference**: Mass land denial, game changers, etc.
- **EDHRec Combos**: Early game 2-card combinations
- **Official Wizards Data**: October 21, 2025 bracket updates

## Testing

Run the included test script:
```bash
python test_deck_validation.py
```

This will test all new endpoints with sample data.

## Troubleshooting

### Common Issues

1. **Authentication Errors**
   - Ensure API_KEY is set correctly
   - Check header format: `Authorization: Bearer YOUR_KEY`

2. **Bracket Validation Failures**
   - Verify target bracket is valid: exhibition, core, upgraded, optimized, cedh
   - Check for game changers in lower brackets
   - Review tutor count for Exhibition/Core

3. **Format Legality Issues**
   - Ensure exactly 99 cards in main deck
   - Check for banned cards
   - Verify commander color identity

### API Response Structure
```json
{
  "success": true,
  "deck_summary": {
    "total_cards": 99,
    "commander": "Jace, Wielder of Mysteries",
    "target_bracket": "optimized"
  },
  "bracket_validation": {
    "target_bracket": "optimized",
    "overall_compliance": true,
    "bracket_score": 4,
    "compliance_details": {
      "game_changers": 2,
      "mass_land_denial": 1,
      "tutors": 3,
      "total_cards": 99
    },
    "violations": [],
    "recommendations": []
  },
  "legality_validation": {
    "is_legal": true,
    "issues": [],
    "warnings": []
  }
}
```

## Security Considerations

- Use a strong API key in production
- Consider rate limiting for the validation endpoint
- Implement request size limits to prevent abuse
- Cache validation results to reduce server load

## Performance Optimization

- Validation results are cached for 1 hour
- Bracket data is preloaded for fast access
- Consider implementing database storage for frequently accessed data
- Add rate limiting for high-traffic usage

## Future Enhancements

1. **Enhanced Scraping**: Direct integration with live EDHRec data
2. **User Profiles**: Save user deck preferences and history
3. **Advanced Analytics**: Power level trending and meta analysis
4. **Community Features**: Share validation results and deck builds
5. **Mobile API**: Optimized endpoints for mobile applications

---

## Support

For issues or questions about the deck validation endpoint:
1. Check the test script for debugging
2. Review API response for detailed error messages
3. Ensure proper authentication and parameter formatting
4. Verify bracket definitions match official Wizard's updates

The endpoint is designed to be robust and provide clear feedback for both successful validations and potential issues.