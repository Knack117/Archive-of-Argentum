# Popular Decks API - Updated Documentation

## Overview
The Popular Decks API fetches the top most-viewed Commander decks from both Moxfield and Archidekt. It now supports **two modes**:
1. **Bracket-filtered search** - Get decks for a specific power level bracket
2. **Bracket-less search** - Get popular decks across all brackets (with bracket information displayed)

## Endpoints

### 1. Get All Popular Decks (No Bracket Filter)
**NEW FUNCTIONALITY** - Search without bracket filtering and see bracket information for each deck.

```
GET /api/v1/popular-decks
```

#### Query Parameters
- `limit_per_source` (optional, default: 5, max: 20): Number of decks to fetch from each source

#### Response Fields
- `bracket_filter`: null (indicating no bracket filter was applied)
- `total_decks`: Total number of decks returned
- `moxfield`: Object containing Moxfield decks
  - `count`: Number of Moxfield decks
  - `decks`: Array of deck objects
- `archidekt`: Object containing Archidekt decks
  - `count`: Number of Archidekt decks
  - `decks`: Array of deck objects
- `all_decks`: Combined array of all decks from both sources
- `summary`: Summary statistics
  - `total_with_primer`: Count of decks that include primers
  - `average_views`: Average view count across all decks
  - `bracket_distribution`: Object showing count of decks per bracket
  - `decks_with_bracket_info`: Count of decks that have bracket information

#### Deck Object Fields
Each deck object includes:
- `url`: Direct link to the deck
- `title`: Deck name
- `views`: Number of views
- `has_primer`: Boolean indicating if deck includes a primer/guide
- `bracket`: **Bracket information** (when available)
  - For Moxfield: Integer (1-5) or null
  - For Archidekt: Object with `name` and `level` or null
- `source`: "moxfield" or "archidekt"
- `format`: "Commander"
- `author`: Deck creator (Moxfield only)
- `last_updated`: Last update timestamp (Moxfield only)

#### Example Request
```bash
curl -X GET "http://localhost:8000/api/v1/popular-decks?limit_per_source=5" \
  -H "X-API-Key: your-api-key"
```

#### Example Response
```json
{
  "bracket_filter": null,
  "total_decks": 10,
  "moxfield": {
    "count": 5,
    "decks": [
      {
        "url": "https://moxfield.com/decks/abc123",
        "title": "Powerful Dragon Deck",
        "views": 1250,
        "has_primer": true,
        "bracket": 4,
        "source": "moxfield",
        "format": "Commander",
        "author": "DragonLord",
        "last_updated": "2025-11-15T10:30:00Z"
      }
    ]
  },
  "archidekt": {
    "count": 5,
    "decks": [
      {
        "url": "https://archidekt.com/decks/456789",
        "title": "Budget Combo Deck",
        "views": 890,
        "has_primer": false,
        "bracket": {
          "name": "Core",
          "level": 2
        },
        "source": "archidekt",
        "format": "Commander"
      }
    ]
  },
  "all_decks": [...],
  "summary": {
    "total_with_primer": 3,
    "average_views": 950.5,
    "bracket_distribution": {
      "2": 2,
      "3": 3,
      "4": 4,
      "5": 1
    },
    "decks_with_bracket_info": 10
  }
}
```

---

### 2. Get Popular Decks by Bracket
Filter decks by specific commander bracket/power level.

```
GET /api/v1/popular-decks/{bracket}
```

#### Path Parameters
- `bracket` (required): Commander bracket level
  - Valid values: `exhibition`, `core`, `upgraded`, `optimized`, `cedh`

#### Query Parameters
- `limit_per_source` (optional, default: 5, max: 20): Number of decks to fetch from each source

#### Response Format
Same as bracket-less endpoint, but with `bracket_filter` set to the requested bracket.

#### Example Request
```bash
curl -X GET "http://localhost:8000/api/v1/popular-decks/upgraded?limit_per_source=10" \
  -H "X-API-Key: your-api-key"
```

---

### 3. Get API Information
Get information about available endpoints and supported brackets.

```
GET /api/v1/popular-decks/info
```

#### Example Response
```json
{
  "description": "Fetch top most-viewed Commander decks from Moxfield and Archidekt",
  "endpoints": [
    {
      "path": "/api/v1/popular-decks",
      "description": "Get popular decks without bracket filtering (includes bracket info for each deck)"
    },
    {
      "path": "/api/v1/popular-decks/{bracket}",
      "description": "Get popular decks filtered by specific bracket"
    }
  ],
  "supported_brackets": ["exhibition", "core", "upgraded", "optimized", "cedh"],
  "default_limit_per_source": 5,
  "max_limit_per_source": 20
}
```

---

## Commander Brackets Explained

Commander brackets represent power levels:

| Bracket | Name | Level | Description |
|---------|------|-------|-------------|
| Exhibition | Exhibition | 1 | Lowest power, casual play |
| Core | Core | 2 | Entry-level competitive |
| Upgraded | Upgraded | 3 | Mid-power competitive |
| Optimized | Optimized | 4 | High-power competitive |
| cEDH | cEDH | 5 | Competitive EDH, highest power |

---

## Usage Examples

### Example 1: Get Popular Decks Without Filter (See All Brackets)
```python
import requests

response = requests.get(
    "http://localhost:8000/api/v1/popular-decks",
    params={"limit_per_source": 10},
    headers={"X-API-Key": "your-api-key"}
)

data = response.json()
print(f"Total decks: {data['total_decks']}")
print(f"Bracket distribution: {data['summary']['bracket_distribution']}")

for deck in data['all_decks']:
    bracket = deck.get('bracket', 'Unknown')
    print(f"{deck['title']} - Bracket: {bracket} - Views: {deck['views']}")
```

### Example 2: Get cEDH Decks Only
```python
response = requests.get(
    "http://localhost:8000/api/v1/popular-decks/cedh",
    headers={"X-API-Key": "your-api-key"}
)

data = response.json()
cedh_decks = data['all_decks']
```

### Example 3: Find High-View Decks with Primers
```python
response = requests.get(
    "http://localhost:8000/api/v1/popular-decks",
    params={"limit_per_source": 20},
    headers={"X-API-Key": "your-api-key"}
)

decks_with_primers = [
    deck for deck in response.json()['all_decks']
    if deck['has_primer'] and deck['views'] > 1000
]
```

---

## Key Features

✅ **Bracket-less search** - View popular decks across all power levels
✅ **Bracket information** - See the declared bracket for each deck
✅ **Bracket distribution** - Summary shows how many decks fall into each bracket
✅ **Dual source** - Aggregates from both Moxfield and Archidekt
✅ **Primer detection** - Identifies decks with comprehensive guides
✅ **View count sorting** - Decks ordered by popularity
✅ **Configurable limits** - Fetch 1-20 decks per source

---

## Notes

- **Moxfield bracket info**: Provided as an integer (1-5) when available via their API
- **Archidekt bracket info**: Provided as an object with bracket name and level when available
- **Bracket availability**: Not all decks have bracket information; check for null values
- **Filtering**: When using bracket-specific endpoint, only Archidekt results are filtered (Moxfield API doesn't support bracket filtering)
- **Rate limiting**: Be mindful of making too many requests in quick succession
- **Data freshness**: Results reflect current data from source websites

---

## Troubleshooting

### No bracket information for some decks
This is expected. Not all deck creators specify bracket information. The `summary.decks_with_bracket_info` field shows how many decks include this data.

### Different bracket formats
Moxfield returns integers (1-5) while Archidekt returns objects with `name` and `level`. Handle both formats in your code:

```python
def get_bracket_display(bracket):
    if bracket is None:
        return "Not specified"
    if isinstance(bracket, dict):
        return f"{bracket.get('name', 'Unknown')} ({bracket.get('level', '?')})"
    return str(bracket)
```

### Empty results
If no decks are returned, the sources may be temporarily unavailable or blocking requests. Check the API logs for error details.
