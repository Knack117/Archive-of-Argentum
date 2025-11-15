# 🚀 MTG API Deployment Guide

## Project Summary

I've created a complete **FastAPI-based MTG Deckbuilding API** using the mightstone library for your Magic: The Gathering GPT integration. The API includes:

### ✅ Core Features Implemented
- **4 Main Endpoints**: Card Search, Card Details, Random Cards, Autocomplete
- **Database Persistence**: MongoDB integration via mightstone's Beanie ODM
- **API Key Authentication**: Secure Bearer token authentication
- **Docker Support**: Ready for Render deployment
- **CORS Configuration**: Cross-origin support for web clients
- **Structured Logging**: Comprehensive error handling and monitoring

### 📁 Project Structure
```
/workspace/
├── app.py              # Main FastAPI application
├── config.py           # Application configuration
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker configuration for Render
├── render.yaml         # Render deployment configuration
├── test_api.py         # API testing suite
├── test_local.py       # Local testing script
├── README.md           # Complete documentation
├── .env.example        # Environment variables template
├── .dockerignore       # Docker build optimization
└── .gitignore          # Git ignore rules
```

## 🎯 Quick Start for Render Deployment

### 1. Push to GitHub
```bash
git add .
git commit -m "Initial MTG API with mightstone integration"
git push origin main
```

### 2. Deploy to Render
1. Go to [render.com](https://render.com) and connect your GitHub
2. Create a new **Web Service**
3. Connect your `Archive-of-Argentum` repository
4. Configure these settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python -m uvicorn app:app --host 0.0.0.0 --port $PORT`
   - **Environment**: `Python 3.11`
   - **Plan**: Choose your plan (Starter is fine for testing)

### 3. Set Environment Variables in Render Dashboard
- `ENVIRONMENT` = `production`
- `API_KEY` = `your-secure-api-key-here` (Generate a strong key)
- `LOG_LEVEL` = `INFO`
- `PORT` = `10000` (Render provides this automatically)

### 4. Add MongoDB Database
1. Create a **MongoDB Atlas** account (free tier available)
2. Create a new cluster
3. Get your connection string: `mongodb+srv://username:password@cluster.mongodb.net/mtg_api`
4. Add to Render environment variables: `MONGODB_URL` = your_connection_string

## 🧪 Testing Your Deployment

Once deployed, test your API:

```bash
# Replace with your actual Render URL
RENDER_URL="https://your-app.onrender.com"

# Test basic connectivity
curl $RENDER_URL

# Test health check
curl $RENDER_URL/health

# Test card search (requires API key)
curl -X POST $RENDER_URL/api/v1/cards/search \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "lightning bolt", "limit": 5}'
```

## 🔧 Local Development

For local testing:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set environment variables
cp .env.example .env
# Edit .env with your settings

# 3. Start the API
python app.py

# 4. Run tests
python test_local.py
```

## 📊 API Endpoints Summary

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `/` | GET | API information | No |
| `/health` | GET | Health check | No |
| `/api/v1/cards/search` | POST | Search for cards | Yes |
| `/api/v1/cards/{card_id}` | GET | Get card details | Yes |
| `/api/v1/cards/random` | GET | Get random card | Yes |
| `/api/v1/cards/autocomplete` | GET | Card name suggestions | Yes |

## 🔐 API Key Usage

All authenticated endpoints use Bearer token authentication:

```python
import requests

headers = {
    "Authorization": "Bearer your-api-key-here"
}

response = requests.post(
    "https://your-render-app.onrender.com/api/v1/cards/search",
    headers=headers,
    json={"query": "lightning bolt", "limit": 10}
)
```

## 📈 Next Steps for Your GPT Integration

1. **Test the API** thoroughly with your Render deployment
2. **Integrate with your GPT** using the API endpoints
3. **Add new features** as needed:
   - Deck validation
   - Mana curve analysis
   - Format legality checks
   - Card price tracking
   - Synergy analysis

## 🆘 Troubleshooting

### Common Issues:
1. **API returns 401**: Check your API key in Authorization header
2. **Database errors**: Verify MongoDB connection string
3. **Build fails**: Check requirements.txt matches your Python version
4. **CORS issues**: Update `ALLOWED_ORIGINS` in environment variables

### Monitoring:
- Use `/health` endpoint for uptime monitoring
- Check Render logs for detailed error information
- Monitor MongoDB Atlas dashboard for database health

## 📞 Support

If you encounter issues:
1. Check the `/docs` endpoint for interactive API documentation
2. Review the test results in `test_local.py`
3. Check Render deployment logs
4. Verify all environment variables are set correctly

Your MTG API is now ready for deployment! 🎉