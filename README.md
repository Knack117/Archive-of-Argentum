# Archive of Argentum

Archive of Argentum is a FastAPI service that wraps Magic: The Gathering utilities for GPT agents and players. It exposes endpoints for card search, commander and combo lookups, deck validation, and curated EDHRec metadata while enforcing API-key protection by default.

## What the service provides
- **Card utilities:** Scryfall-backed search, autocomplete, and random card selection.
- **Commander helpers:** Summary scrapers, salt scoring, and bracket-aware recommendations.
- **Combo insights:** Early- and late-game combo discovery tuned for cEDH and casual brackets.
- **Deck validation:** Decklist parsing from plain text or popular sites plus legality, bracket, and salt analysis.
- **System endpoints:** Health, status, and OpenAPI discovery for monitoring.

## Project layout
- `app.py` – FastAPI application setup, middleware, and OpenAPI customisation.
- `aoa/` – Core package containing routes, models, security dependencies, and services.
  - `routes/` – Endpoint implementations (cards, commanders, combos, themes, deck validation, etc.).
  - `services/` – Support utilities such as salt-score caching and special-card helpers.
  - `models/` – Pydantic schemas shared across endpoints.
- `data/` – Seed caches for salt scores and tag metadata.
- `tests/` – Comprehensive pytest suite covering system endpoints, security, validation helpers, and salt cache utilities.

## Getting started
1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**
   Create a `.env` file (or export variables) with at least:
   - `API_KEY` – bearer token expected by secured endpoints (defaults to `test-key` for local use).
   - `MONGODB_URL` – connection string if persistence is required by mightstone-backed routes.
   - `LOG_LEVEL` – logging verbosity (default `INFO`).

3. **Run the API locally**
   ```bash
   python app.py
   ```
   The server listens on `http://0.0.0.0:8000` by default. Visit `/docs` for interactive OpenAPI documentation. Public endpoints (`/`, `/health`, `/api/v1/status`) are unauthenticated; all others expect `Authorization: Bearer <API_KEY>`.

## Testing
The repository ships with a fresh pytest suite focused on critical behaviours such as security enforcement, OpenAPI generation, deck validation helpers, and salt-cache handling.

Run all tests with:
```bash
pytest
```

## Deployment notes
- Containerisation is supported via the included `Dockerfile`.
- When deploying to platforms like Render, set `ENVIRONMENT=production` and ensure your API key and MongoDB credentials are supplied as environment variables.

## Contributing
Contributions are welcome! Please open an issue for discussion, then submit a PR with accompanying tests. Ensure new endpoints include clear validation and maintain API-key enforcement.
