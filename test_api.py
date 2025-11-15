"""
Test suite for MTG API endpoints
Run with: pytest test_api.py -v
"""

import pytest
import asyncio
from fastapi.testclient import TestClient
from app import app

# Create test client
client = TestClient(app)


class TestBasicEndpoints:
    """Test basic API endpoints"""
    
    def test_root_endpoint(self):
        """Test root endpoint returns correct response"""
        response = client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "MTG Deckbuilding API" in data["message"]
    
    def test_health_endpoint(self):
        """Test health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "healthy" in data["message"]


class TestCardEndpoints:
    """Test card-related endpoints"""
    
    def test_search_cards_missing_auth(self):
        """Test that search requires authentication"""
        response = client.post("/api/v1/cards/search", json={"query": "lightning bolt"})
        # Should fail without proper API key
        assert response.status_code in [401, 403]
    
    def test_get_card_missing_auth(self):
        """Test that card retrieval requires authentication"""
        response = client.get("/api/v1/cards/test-id")
        # Should fail without proper API key
        assert response.status_code in [401, 403]
    
    def test_random_card_missing_auth(self):
        """Test that random card requires authentication"""
        response = client.get("/api/v1/cards/random")
        # Should fail without proper API key
        assert response.status_code in [401, 403]
    
    def test_autocomplete_missing_auth(self):
        """Test that autocomplete requires authentication"""
        response = client.get("/api/v1/cards/autocomplete?q=lightning")
        # Should fail without proper API key
        assert response.status_code in [401, 403]

    def test_theme_missing_auth(self):
        """Test that theme endpoint requires authentication"""
        response = client.get("/api/v1/themes/spellslinger")
        assert response.status_code in [401, 403]


class TestAPIResponseFormat:
    """Test API response format consistency"""
    
    def test_response_structure(self):
        """Test that all responses have consistent structure"""
        # This test would need proper API key setup
        # For now, just test that the app starts correctly
        assert app is not None
        
        # Check that the app has the expected endpoints
        routes = [route.path for route in app.routes]
        assert "/" in routes
        assert "/health" in routes
        assert "/api/v1/cards/search" in routes
        assert "/api/v1/cards/{card_id}" in routes
        assert "/api/v1/cards/random" in routes
        assert "/api/v1/cards/autocomplete" in routes
        assert "/api/v1/themes/{theme_slug}" in routes


class TestDataValidation:
    """Test request/response data validation"""
    
    def test_search_request_validation(self):
        """Test search request validation"""
        # Test with invalid request (missing required fields)
        response = client.post("/api/v1/cards/search", json={})
        assert response.status_code == 422  # Validation error
    
    def test_autocomplete_request_validation(self):
        """Test autocomplete request validation"""
        # Test with query too short
        response = client.get("/api/v1/cards/autocomplete?q=a")
        # Should return empty results or validation error
        assert response.status_code == 200 or response.status_code == 422


if __name__ == "__main__":
    # Run tests without pytest
    test_basic = TestBasicEndpoints()
    test_basic.test_root_endpoint()
    test_basic.test_health_endpoint()
    
    print("Basic tests passed!")
    print("Note: Full API testing requires valid API key setup")