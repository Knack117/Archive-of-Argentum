# Code Change: Side-by-Side Comparison

## File: `aoa/services/commanders.py`

### BEFORE (Lines 19-41) ❌ - Broken
```python
def _extract_page_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the commander data block regardless of how Next.js nests it."""

    if not isinstance(payload, dict):
        return {}

    queue: Deque[Any] = deque([payload])
    while queue:
        node = queue.popleft()
        if isinstance(node, dict):
            page_props = node.get("pageProps")
            if isinstance(page_props, dict):
                data_block = page_props.get("data")
                if isinstance(data_block, dict):
                    return data_block
            for value in node.values():
                if isinstance(value, (dict, list, tuple)):
                    queue.append(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                if isinstance(item, (dict, list, tuple)):
                    queue.append(item)
    return {}  # ← Returns empty dict when pageProps.data not found
```

**Problem:** When EDHRec returns data directly (new format), this function searches the entire tree for `pageProps.data`, doesn't find it, and returns `{}`. This causes all commander fields to be empty.

---

### AFTER (Lines 19-52) ✅ - Fixed
```python
def _extract_page_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the commander data block regardless of how Next.js nests it."""

    if not isinstance(payload, dict):
        return {}

    # ✅ NEW: Check if payload is already the data block (new EDHRec API format)
    # The data block typically has keys like 'panels', 'similar', 'cardlists', 'container'
    data_indicators = {'panels', 'similar', 'cardlists', 'container'}
    if any(key in payload for key in data_indicators):
        logger.debug("Payload appears to be direct data block (new format)")
        return payload  # ← Return the payload directly!

    # Otherwise, search for pageProps.data (old format with Next.js wrapper)
    queue: Deque[Any] = deque([payload])
    while queue:
        node = queue.popleft()
        if isinstance(node, dict):
            page_props = node.get("pageProps")
            if isinstance(page_props, dict):
                data_block = page_props.get("data")
                if isinstance(data_block, dict):
                    logger.debug("Found data block in pageProps.data (old format)")
                    return data_block
            for value in node.values():
                if isinstance(value, (dict, list, tuple)):
                    queue.append(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                if isinstance(item, (dict, list, tuple)):
                    queue.append(item)
    
    logger.warning("Could not find commander data in payload")
    return {}
```

**Solution:** Before doing the expensive tree traversal, first check if the payload already looks like commander data by checking for characteristic keys. If found, return it immediately. Otherwise, fall back to searching for the old `pageProps.data` structure.

---

## Summary of Changes

| Aspect | Before | After |
|--------|--------|-------|
| Lines of code | 23 lines | 34 lines |
| Handles new format | ❌ No | ✅ Yes |
| Handles old format | ✅ Yes | ✅ Yes |
| Empty data issue | ❌ Yes | ✅ Fixed |
| Logging | None | ✅ Debug logs added |

## What Makes This Fix Work

The fix adds a **fast-path check** at the beginning:

```python
data_indicators = {'panels', 'similar', 'cardlists', 'container'}
if any(key in payload for key in data_indicators):
    return payload
```

This simple check detects the new API format by looking for keys that are characteristic of EDHRec's data structure. If any are present, we know the payload is already the data block we need.

## Performance Impact

**Improved Performance** ⚡
- Before: Had to traverse entire JSON tree (potentially hundreds of objects)
- After: Checks 4 keys at root level, returns immediately

## Deployment

This change is:
- ✅ Backward compatible
- ✅ All tests passing
- ✅ No API changes required
- ✅ Safe to deploy immediately

Simply copy the modified `aoa/services/commanders.py` file to your production environment.
