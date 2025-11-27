"""System endpoints such as status and root."""
from datetime import datetime
from typing import Any, Dict
from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

from aoa.constants import API_VERSION

router = APIRouter(tags=["system"])


@router.get("/api/v1/status", response_model=Dict[str, Any])
async def api_status() -> Dict[str, Any]:
    """API status endpoint."""
    return {
        "success": True,
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "version": API_VERSION,
    }


@router.get("/", response_model=Dict[str, Any])
async def root() -> Dict[str, Any]:
    """Root endpoint."""
    return {
        "success": True,
        "message": "MTG Deckbuilding API",
        "version": API_VERSION,
        "docs": "/docs",
        "status": "/api/v1/status",
    }


@router.get("/health", response_model=Dict[str, Any])
async def health_check() -> Dict[str, Any]:
    """Health check endpoint expected by hosting environments."""
    return {
        "success": True,
        "status": "healthy",
        "message": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "MTG Deckbuilding API",
    }


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> str:
    """Privacy policy page for GPT public deployment."""
    
    # Simple HTML privacy policy (no markdown dependency)
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Privacy Policy - Archive of Argentum</title>
        <style>
            body { 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                max-width: 800px; 
                margin: 0 auto; 
                padding: 20px; 
                line-height: 1.6;
                color: #333;
                background: #fff;
            }
            h1, h2, h3 { 
                color: #1a1a1a; 
                margin-top: 30px;
                margin-bottom: 15px;
            }
            h1 { 
                border-bottom: 3px solid #4285f4; 
                padding-bottom: 10px;
                font-size: 2.2em;
            }
            h2 { 
                font-size: 1.5em;
                border-left: 4px solid #4285f4;
                padding-left: 15px;
            }
            p { margin-bottom: 15px; }
            ul { padding-left: 20px; margin-bottom: 15px; }
            li { margin-bottom: 8px; }
            strong { color: #1a1a1a; }
            .meta { 
                color: #666; 
                font-style: italic; 
                margin-bottom: 30px; 
                font-size: 0.9em;
            }
            .contact { 
                background: #f8f9fa; 
                padding: 20px; 
                border-radius: 8px; 
                border-left: 4px solid #4285f4;
                margin-top: 30px;
            }
            .last-updated {
                background: #e3f2fd;
                padding: 10px;
                border-radius: 5px;
                margin-bottom: 20px;
                font-weight: 500;
            }
            a { color: #4285f4; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>Privacy Policy</h1>
        
        <div class="last-updated">
            <strong>Last updated:</strong> November 28, 2025
        </div>
        
        <div class="meta">
            The Archive of Argentum operates the EDH Commander Analysis API. This privacy policy explains how we collect, use, and protect information when you use our Service.
        </div>

        <h2>Overview</h2>
        <p>The Archive of Argentum ("we", "our", or "us") operates the EDH Commander Analysis API ("Service"). This privacy policy explains how we collect, use, and protect information when you use our Service.</p>

        <h2>Information We Collect</h2>
        
        <h3>Information You Provide</h3>
        <p>We do not require you to provide any personal information to use our Service. Our API responds to requests for Magic: The Gathering EDH (Elder Dragon Highlander) commander data and does not require user registration or personal data collection.</p>

        <h3>Information Collected Automatically</h3>
        <ul>
            <li><strong>API Request Data:</strong> When you use our Service, we may temporarily log:
                <ul>
                    <li>Request timestamps</li>
                    <li>Commander names being queried</li>
                    <li>API endpoint calls</li>
                    <li>Basic request metadata (no personal identifiers)</li>
                </ul>
            </li>
            <li><strong>Usage Analytics:</strong> We may collect aggregated, anonymized usage statistics to improve our Service</li>
        </ul>

        <h3>Third-Party Services</h3>
        <p>Our Service retrieves publicly available Magic: The Gathering commander data from <a href="https://edhrec.com" target="_blank">EDHRec</a>. We do not control EDHRec's data collection or privacy practices.</p>

        <h2>How We Use Information</h2>
        <p>We use the information we collect to:</p>
        <ul>
            <li>Provide commander data and analysis through our API</li>
            <li>Maintain and improve our Service functionality</li>
            <li>Monitor API usage and performance</li>
            <li>Respond to technical support requests</li>
        </ul>

        <h2>Data Sharing and Disclosure</h2>
        <p>We do not sell, trade, or rent your personal information. We may disclose information in the following circumstances:</p>
        <ul>
            <li>To comply with legal obligations</li>
            <li>To protect our rights and safety</li>
            <li>In connection with a business transfer or merger</li>
            <li>With your explicit consent</li>
        </ul>

        <h2>Data Security</h2>
        <p>We implement appropriate security measures to protect information against unauthorized access, alteration, disclosure, or destruction. However, no method of transmission over the internet is 100% secure.</p>

        <h2>Cookies and Tracking</h2>
        <p>Our Service does not use cookies or similar tracking technologies. We do not store personal data locally on your device.</p>

        <h2>Data Retention</h2>
        <ul>
            <li><strong>API Logs:</strong> Typically retained for up to 30 days for operational purposes</li>
            <li><strong>Commander Data:</strong> Public commander information is retrieved fresh from EDHRec and not permanently stored</li>
            <li><strong>Usage Analytics:</strong> Aggregated and anonymized data may be retained indefinitely</li>
        </ul>

        <h2>Your Rights</h2>
        <p>Since we do not collect personal information, there is limited personal data to manage. If you have questions about our data practices, contact us using the information below.</p>

        <h2>Children's Privacy</h2>
        <p>Our Service is not directed to children under 13, and we do not knowingly collect personal information from children under 13.</p>

        <h2>International Users</h2>
        <p>Our Service is provided from the United States. If you are accessing our Service from outside the United States, please be aware that your information may be transferred to, stored, and processed in the United States.</p>

        <h2>Changes to This Policy</h2>
        <p>We may update this privacy policy from time to time. We will notify users of any material changes by posting the new policy on this page.</p>

        <h2>Compliance and Legal Basis</h2>
        <p>This privacy policy complies with:</p>
        <ul>
            <li>General Data Protection Regulation (GDPR)</li>
            <li>California Consumer Privacy Act (CCPA)</li>
            <li>Other applicable data protection laws</li>
        </ul>

        <div class="contact">
            <h2>Contact Information</h2>
            <p>If you have questions about this privacy policy or our data practices, please contact us:</p>
            <ul>
                <li><strong>Email:</strong> YOUR_EMAIL@example.com</li>
                <li><strong>GitHub Issues:</strong> https://github.com/yourusername/yourrepo/issues</li>
            </ul>
        </div>

        <hr style="margin: 40px 0; border: none; border-top: 1px solid #eee;">
        <p style="text-align: center; color: #666; font-size: 0.9em;">
            <strong>Effective Date:</strong> November 28, 2025<br>
            <strong>Version:</strong> 1.0
        </p>
    </body>
    </html>
    """
    
    return html_content
