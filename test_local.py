#!/usr/bin/env python3
"""
Test script to verify MTG API is working correctly
Run this locally to test the API before deploying to Render
"""

import os
import sys
import subprocess
import time
import requests
import json
from pathlib import Path


def start_api_server():
    """Start the API server in the background"""
    print("🚀 Starting MTG API server...")
    
    # Set development environment
    env = os.environ.copy()
    env["ENVIRONMENT"] = "development"
    env["API_KEY"] = "test-key-123"  # Test API key
    env["MONGODB_URL"] = "mongodb://localhost:27017/mtg_api"
    
    # Start server
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to start
    time.sleep(5)
    return process


def test_api_endpoints():
    """Test all API endpoints"""
    base_url = "http://localhost:8000"
    headers = {"Authorization": "Bearer test-key-123"}
    
    tests = [
        ("GET", "/", "Root endpoint"),
        ("GET", "/health", "Health check"),
        ("POST", "/api/v1/cards/search", "Card search", {"query": "lightning bolt", "limit": 5}),
        ("GET", "/api/v1/cards/random", "Random card"),
        ("GET", "/api/v1/cards/autocomplete?q=light", "Autocomplete"),
    ]
    
    results = []
    
    for test in tests:
        method, endpoint, description, *data = test
        
        try:
            if method == "GET":
                response = requests.get(f"{base_url}{endpoint}", headers=headers, timeout=10)
            elif method == "POST":
                response = requests.post(f"{base_url}{endpoint}", headers=headers, json=data[0], timeout=10)
            
            result = {
                "test": description,
                "endpoint": endpoint,
                "status_code": response.status_code,
                "success": response.status_code < 400,
                "response_size": len(response.content)
            }
            
            if response.status_code < 400:
                result["data_preview"] = str(response.json())[:200] + "..."
            
            results.append(result)
            
            status = "✅ PASS" if response.status_code < 400 else "❌ FAIL"
            print(f"{status} {description} (Status: {response.status_code})")
            
        except Exception as e:
            result = {
                "test": description,
                "endpoint": endpoint,
                "error": str(e),
                "success": False
            }
            results.append(result)
            print(f"❌ ERROR {description}: {str(e)}")
    
    return results


def main():
    """Main test function"""
    print("🧪 MTG API Test Suite")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not Path("app.py").exists():
        print("❌ Error: app.py not found. Run this script from the project directory.")
        return
    
    # Install dependencies
    print("\n📦 Installing dependencies...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                      check=True, capture_output=True)
        print("✅ Dependencies installed")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing dependencies: {e}")
        return
    
    # Start server
    server_process = None
    try:
        server_process = start_api_server()
        
        # Test endpoints
        print("\n🔍 Testing API endpoints...")
        results = test_api_endpoints()
        
        # Summary
        print("\n📊 Test Summary")
        print("=" * 50)
        passed = sum(1 for r in results if r.get("success", False))
        total = len(results)
        print(f"Tests passed: {passed}/{total}")
        
        if passed == total:
            print("🎉 All tests passed! API is ready for deployment.")
        else:
            print("⚠️  Some tests failed. Check the output above.")
            
        # Save results
        with open("test_results.json", "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n📄 Detailed results saved to test_results.json")
        
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"❌ Error during testing: {str(e)}")
    finally:
        if server_process:
            print("\n🛑 Stopping API server...")
            server_process.terminate()
            server_process.wait()


if __name__ == "__main__":
    main()