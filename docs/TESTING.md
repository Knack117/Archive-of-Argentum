# Testing Overview

The pytest suite focuses on behaviours that can be validated without external network calls. It covers:

- **System routes**: `/`, `/health`, and `/api/v1/status` for availability and version reporting.
- **Security defaults**: API-key validation logic and OpenAPI generation with HTTP Bearer enforcement.
- **Deck validation helpers**: Card-name normalization, duplicate detection, and combo detection utilities.
- **Salt cache utilities**: Name normalization, variant matching for split names, and fallback injection for known commanders.

## Running the suite
Execute all tests from the repository root:

```bash
pytest
```

Tests rely on the bundled sample salt cache in `data/` or temporary cache fixtures and do not require network access.
