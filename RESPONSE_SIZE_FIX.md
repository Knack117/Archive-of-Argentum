# ResponseTooLargeError Fix for Themes Endpoint

## Problem
The `/api/v1/themes/{theme_slug}` endpoint was causing `ResponseTooLargeError` because it could return very large amounts of data, especially for themes with many categories and cards. This was causing issues with the deployment platform (likely Render or similar services).

## Solution Implemented

### 1. Response Size Management
- Added automatic response size estimation and monitoring
- Implemented size thresholds:
  - **4MB**: Warning threshold - includes performance recommendations
  - **8MB**: Hard limit - automatically switches to summary mode

### 2. Smart Data Reduction
- **Default card limit**: Reduced to ensure manageable response sizes
- **Automatic summary mode**: For very large datasets (> 1000 cards estimated)
- **Metadata-only mode**: New `response_format=metadata` option for categories only

### 3. New Query Parameters
- `response_format`: Control response type
  - `auto` (default): Automatic size management
  - `full`: Return all data (may be truncated)
  - `metadata`: Categories summary only, no individual cards

### 4. Response Models
- `ThemeResponse`: Full data response
- `ThemeMetadataResponse`: Summary-only response for large datasets
- Both include `response_info` with size and recommendation data

## Usage Examples

### Basic Usage (Auto-manages size)
```bash
curl -H "Authorization: Bearer YOUR_KEY" \
  "https://your-app.com/api/v1/themes/spellslinger"
```

### Specify Card Limit
```bash
curl -H "Authorization: Bearer YOUR_KEY" \
  "https://your-app.com/api/v1/themes/spellslinger?max_cards=20"
```

### Metadata Only (Fast)
```bash
curl -H "Authorization: Bearer YOUR_KEY" \
  "https://your-app.com/api/v1/themes/spellslinger?response_format=metadata"
```

### Force Full Response (with recommendations)
```bash
curl -H "Authorization: Bearer YOUR_KEY" \
  "https://your-app.com/api/v1/themes/spellslinger?response_format=full&max_cards=10"
```

## Response Format Changes

### Normal Response
```json
{
  "theme_slug": "spellslinger",
  "theme_url": "https://deckstats.net/themes/spellslinger",
  "timestamp": "2024-01-15T10:30:00Z",
  "categories": {
    "instants": {
      "category_name": "Instants",
      "total_cards": 20,
      "cards": [
        {
          "name": "Lightning Bolt",
          "rank": 1,
          "edhrec_url": "https://deckstats.net/card/lightning-bolt",
          ...
        }
      ],
      "is_truncated": false
    }
  },
  "theme_name": "Spellslinger",
  "total_decks": 15420,
  "response_info": {
    "response_type": "full",
    "size_estimate": 2560000,
    "recommendation": "Consider using max_cards parameter for better performance"
  }
}
```

### Summary Response (for large datasets)
```json
{
  "theme_slug": "spellslinger",
  "theme_url": "https://deckstats.net/themes/spellslinger",
  "timestamp": "2024-01-15T10:30:00Z",
  "theme_name": "Spellslinger",
  "total_decks": 15420,
  "categories_summary": {
    "instants": {
      "category_name": "Instants",
      "total_cards": 45,
      "available_cards": 67,
      "is_truncated": true
    },
    "sorceries": {
      "category_name": "Sorceries", 
      "total_cards": 38,
      "available_cards": 52,
      "is_truncated": true
    }
  },
  "response_info": {
    "response_type": "summary",
    "original_size_estimate": 9500000,
    "reason": "Response exceeded size limit",
    "use_full_endpoint": "Use max_cards parameter to reduce data size"
  }
}
```

## Benefits
1. **No More Errors**: Automatically prevents ResponseTooLargeError
2. **Better Performance**: Smaller responses load faster
3. **Flexible Usage**: Choose between detailed and summary data
4. **Automatic Optimization**: Smart defaults with size monitoring
5. **Backward Compatible**: Existing code continues to work

## Migration Guide
- Existing API calls will automatically benefit from the size management
- For large themes, responses may be truncated - use `max_cards` to control
- If you need summary data, explicitly use `response_format=metadata`
- Check `response_info` field for size recommendations

## Performance Recommendations
- Use `max_cards=10-30` for normal applications
- Use `max_cards=50` for detailed analysis
- Use `response_format=metadata` for category overviews
- Set `max_cards=0` to get only metadata (fastest)