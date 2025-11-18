# Fix: EDHRec API Structure Change - Commander Data Not Displaying

## Problem Summary

Your endpoints were failing to display commander data (tags, combos, similar commanders, categories) even though the data was being successfully fetched from EDHRec. The issue affected **ALL** commanders, not just "Fire Lord Ozai".

## Root Cause

**EDHRec changed their JSON API structure**, but your extraction code was only looking for the old format.

### Old Format (What your code expected):
```json
{
  "__N_SSP": true,
  "pageProps": {
    "data": {
      "panels": {...},
      "similar": [...],
      "cardlists": [...]
    }
  }
}
```

### New Format (What EDHRec now returns):
```json
{
  "avg_price": 1859.0,
  "panels": {...},
  "similar": [...],
  "cardlists": [...],
  "container": {...}
}
```

The data is now returned **directly at the root level** without the `__N_SSP` and `pageProps` wrapper.

## The Fix

Modified the `_extract_page_data()` function in <filepath>aoa/services/commanders.py</filepath> to:

1. **First check if the payload is already the data block** (new format) by looking for data indicators like `panels`, `similar`, `cardlists`, or `container`
2. **If not found, search for the old `pageProps.data` structure** (backward compatibility)
3. **Return empty dict only if neither format is found**

### Code Changes

```python
def _extract_page_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the commander data block regardless of how Next.js nests it."""

    if not isinstance(payload, dict):
        return {}

    # Check if payload is already the data block (new EDHRec API format)
    # The data block typically has keys like 'panels', 'similar', 'cardlists', 'container'
    data_indicators = {'panels', 'similar', 'cardlists', 'container'}
    if any(key in payload for key in data_indicators):
        logger.debug("Payload appears to be direct data block (new format)")
        return payload

    # Otherwise, search for pageProps.data (old format with Next.js wrapper)
    # ... [rest of original code for backward compatibility]
```

## Test Results

### Before Fix:
- **Fire Lord Ozai**: 0 tags, 0 combos, 0 similar commanders, 0 categories ❌
- **The Ur-Dragon**: 0 tags, 0 combos, 0 similar commanders, 0 categories ❌

### After Fix:
- **Fire Lord Ozai**: 25 tags, 4 combos, 6 similar commanders, 12 categories ✅
- **The Ur-Dragon**: 164 tags, 4 combos, 6 similar commanders, 14 categories ✅

## Verification

All existing unit tests pass, confirming backward compatibility with the old format:
```
test_extract_commander_json_data_from_standard_payload PASSED
test_extract_commander_json_data_from_nested_props PASSED
test_extract_commander_json_data_from_fallback_payload PASSED
test_extract_commander_sections_and_tags_support_nested_data PASSED
test_scrape_edhrec_commander_page_returns_full_summary PASSED
```

## Impact

This fix resolves the issue for:
- ✅ `/api/v1/commander/summary` endpoint
- ✅ `/api/v1/average_deck/summary` endpoint
- ✅ All commanders (both new and established)
- ✅ Maintains backward compatibility with old API format

## Files Modified

- <filepath>aoa/services/commanders.py</filepath> - Updated `_extract_page_data()` function

---

**MiniMax Agent**
