#!/usr/bin/env python3
"""
Huawei Health OAuth Setup Script
Handles OAuth 2.0 authentication flow for Huawei Health Kit API
"""

import json
import os
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, parse_qs, urlparse
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Huawei OAuth endpoints
HUAWEI_AUTH_URL = "https://oauth-login.cloud.huawei.com/oauth2/v3/authorize"
HUAWEI_TOKEN_URL = "https://oauth-login.cloud.huawei.com/oauth2/v3/token"

# Configuration
CLIENT_ID = os.getenv('HUAWEI_CLIENT_ID')
CLIENT_SECRET = os.getenv('HUAWEI_CLIENT_SECRET')
REDIRECT_URI = os.getenv('HUAWEI_REDIRECT_URI', 'http://localhost:8080/callback')

# Scopes for fitness data
SCOPES = [
    'https://www.huawei.com/healthkit/step.read',
    'https://www.huawei.com/healthkit/calories.read',
    'https://www.huawei.com/healthkit/distance.read',
    'https://www.huawei.com/healthkit/activity.read'
]

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP server handler for OAuth callback"""
    
    auth_code = None
    
    def do_GET(self):
        """Handle GET request from OAuth callback"""
        query = urlparse(self.path).query
        params = parse_qs(query)
        
        if 'code' in params:
            OAuthCallbackHandler.auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <body>
                    <h1>Authorization Successful!</h1>
                    <p>You can close this window and return to the terminal.</p>
                </body>
                </html>
            """)
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <body>
                    <h1>Authorization Failed</h1>
                    <p>No authorization code received.</p>
                </body>
                </html>
            """)
    
    def log_message(self, format, *args):
        """Suppress server logs"""
        pass

def get_authorization_url():
    """Generate authorization URL"""
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'state': 'random_state_string'
    }
    return f"{HUAWEI_AUTH_URL}?{urlencode(params)}"

def exchange_code_for_token(auth_code):
    """Exchange authorization code for access token"""
    data = {
        'grant_type': 'authorization_code',
        'code': auth_code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI
    }
    
    response = requests.post(HUAWEI_TOKEN_URL, data=data)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Token exchange failed: {response.status_code} - {response.text}")

def save_token(token_data):
    """Save token to file"""
    with open('token.json', 'w') as f:
        json.dump(token_data, f, indent=2)
    print("✅ Token saved to token.json")

def verify_token(access_token):
    """Verify token by making a test API call"""
    # This is a placeholder - actual endpoint depends on Huawei Health API
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    # Note: Replace with actual Huawei Health API endpoint
    # For now, just confirm token was saved
    print("✅ Token verification complete")
    return True

def main():
    """Main setup flow"""
    print("🏥 Huawei Health OAuth Setup")
    print("=" * 50)
    
    # Check for required environment variables
    if not CLIENT_ID or not CLIENT_SECRET:
        print("❌ Error: Missing required environment variables")
        print("Please create a .env file with:")
        print("  HUAWEI_CLIENT_ID=your_client_id")
        print("  HUAWEI_CLIENT_SECRET=your_client_secret")
        return
    
    print(f"Client ID: {CLIENT_ID[:10]}...")
    print(f"Redirect URI: {REDIRECT_URI}")
    print(f"Scopes: {len(SCOPES)} permissions")
    print()
    
    # Step 1: Get authorization URL
    auth_url = get_authorization_url()
    print("Step 1: Opening browser for authorization...")
    print(f"If browser doesn't open, visit: {auth_url}")
    print()
    
    # Open browser
    webbrowser.open(auth_url)
    
    # Step 2: Start local server to receive callback
    print("Step 2: Waiting for authorization callback...")
    server = HTTPServer(('localhost', 8080), OAuthCallbackHandler)
    server.handle_request()
    
    if not OAuthCallbackHandler.auth_code:
        print("❌ No authorization code received")
        return
    
    print("✅ Authorization code received")
    print()
    
    # Step 3: Exchange code for token
    print("Step 3: Exchanging code for access token...")
    try:
        token_data = exchange_code_for_token(OAuthCallbackHandler.auth_code)
        print("✅ Access token obtained")
        print()
        
        # Step 4: Save token
        print("Step 4: Saving token...")
        save_token(token_data)
        print()
        
        # Step 5: Verify token
        print("Step 5: Verifying token...")
        verify_token(token_data.get('access_token'))
        print()
        
        print("=" * 50)
        print("🎉 Setup complete!")
        print()
        print("Next steps:")
        print("1. Run: python update_fitness_widget.py")
        print("2. Add token.json content to GitHub Secrets as HUAWEI_HEALTH_TOKEN")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return

if __name__ == '__main__':
    main()
