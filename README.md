# MTG Deckbuilding API

A FastAPI-based REST API for Magic: The Gathering card search and deckbuilding using the [mightstone](https://mightstone.readthedocs.io/) library.

## Features

- **Card Search**: Search for cards by name, type, colors, etc.
- **Card Details**: Get detailed information about specific cards
- **Random Cards**: Get random cards for inspiration
- **Autocomplete**: Card name suggestions for GPT integration
- **Database Persistence**: MongoDB caching via mightstone's Beanie integration
- **API Key Authentication**: Secure access for your GPT
- **Render Deployment**: Docker-ready for easy cloud hosting

## Quick Start

### Prerequisites

- Python 3.11+
- MongoDB (local or cloud)
- Docker (for deployment)

### Environment Variables

Create a `.env` file based on `.env.example`:

```bash
cp .env.example .env
```

Required variables:
- `API_KEY`: Your secure API key for authentication
- `MONGODB_URL`: MongoDB connection string
- `ENVIRONMENT`: Set to `production` for Render

### Local Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. **Run the API:**
   ```bash
   python app.py
   ```

The API will be available at `http://localhost:8000`

### Render Deployment

1. **Build and push to Docker registry** (or use Render's auto-deploy from GitHub)

2. **Set Environment Variables in Render:**
   - `API_KEY`: Your secure API key
   - `MONGODB_URL`: MongoDB connection string
   - `ENVIRONMENT`: `production`
   - `PORT`: `10000` (Render will provide this)

3. **Deploy**: Connect your GitHub repository to Render and deploy

## API Endpoints

All endpoints require API key authentication via Bearer token.

### `GET /`
Basic health check and API information.

### `GET /health`
Health check endpoint for monitoring.

### `POST /api/v1/cards/search`
Search for Magic: The Gathering cards.

**Request Body:**
```json
{
    "query": "lightning bolt",
    "limit": 20,
    "order": "name",
    "unique": "cards"
}
```

**Response:**
```json
{
    "success": true,
    "data_list": [...],
    "message": "Found 1 cards",
    "count": 1
}
```

### `GET /api/v1/cards/{card_id}`
Get detailed information about a specific card by Scryfall ID.

### `GET /api/v1/cards/random`
Get a random Magic: The Gathering card.

**Query Parameters:**
- `query` (optional): Filter the random card search

### `GET /api/v1/cards/autocomplete`
Get autocomplete suggestions for card names.

**Query Parameters:**
- `q`: Search query (minimum 2 characters)

## Usage Example

```python
import requests

# Set your API key
headers = {
    "Authorization": "Bearer your_api_key_here"
}

# Search for cards
response = requests.post(
    "https://your-render-app.onrender.com/api/v1/cards/search",
    headers=headers,
    json={"query": "lightning bolt", "limit": 10}
)

cards = response.json()
print(f"Found {cards['count']} cards")

# Get a random card
random_response = requests.get(
    "https://your-render-app.onrender.com/api/v1/cards/random",
    headers=headers
)

random_card = random_response.json()
print(f"Random card: {random_card['data']['name']}")
```

## Database Configuration

The API uses mightstone's built-in persistence with Beanie ODM for MongoDB.

### MongoDB Options:

1. **Local MongoDB:**
   ```
   MONGODB_URL=mongodb://localhost:27017/mtg_api
   ```

2. **MongoDB Atlas (Recommended for production):**
   ```
   MONGODB_URL=mongodb+srv://username:password@cluster.mongodb.net/mtg_api
   ```

3. **Render Persistent Disk:**
   Set up a MongoDB service on Render or use MongoDB Atlas.

## Architecture

- **FastAPI**: High-performance async web framework
- **mightstone**: MTG data integration with Scryfall, EDHREC, MTGJSON
- **MongoDB**: Caching and persistence via Beanie ODM
- **Docker**: Containerized deployment ready for Render

## Security

- API key authentication for all endpoints
- CORS configuration for production
- Secure environment variable handling
- Non-root Docker user

## Monitoring

- Health check endpoints for uptime monitoring
- Structured logging for troubleshooting
- Error handling with appropriate HTTP status codes

## Development

### Running Tests
```bash
pytest
```

### Code Formatting
```bash
black app.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues and questions:
1. Check the [mightstone documentation](https://mightstone.readthedocs.io/)
2. Review the API documentation at `/docs`
3. Open an issue in this repository