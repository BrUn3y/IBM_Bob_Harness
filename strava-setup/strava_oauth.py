#!/usr/bin/env python3
"""
Strava OAuth Setup Script
Handles the OAuth flow to get access tokens for Strava API
"""

import os
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests
import json

# Credenciales de Strava
CLIENT_ID = "197414"
CLIENT_SECRET = "a96a7843d21e79d5520af03696bf57c1a03adaec"
REDIRECT_URI = "http://localhost:8001/callback"
TOKEN_FILE = "strava_tokens.json"

# Scopes necesarios para obtener datos de actividades
SCOPES = "read,activity:read_all,profile:read_all"


class CallbackHandler(BaseHTTPRequestHandler):
    """Handler para capturar el código de autorización"""
    
    authorization_code = None
    
    def do_GET(self):
        """Maneja la redirección de Strava con el código"""
        query = urlparse(self.path).query
        params = parse_qs(query)
        
        if 'code' in params:
            CallbackHandler.authorization_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <body>
                    <h1>Autorizacion exitosa!</h1>
                    <p>Ya puedes cerrar esta ventana y volver a la terminal.</p>
                </body>
                </html>
            """)
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Error en la autorizacion</h1></body></html>")
    
    def log_message(self, format, *args):
        """Silencia los logs del servidor"""
        pass


def get_authorization_url():
    """Genera la URL de autorización de Strava"""
    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPES}"
    )
    return auth_url


def exchange_code_for_token(code):
    """Intercambia el código de autorización por tokens de acceso"""
    token_url = "https://www.strava.com/oauth/token"
    
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code'
    }
    
    response = requests.post(token_url, data=payload)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Error al obtener token: {response.status_code} - {response.text}")


def save_tokens(token_data):
    """Guarda los tokens en un archivo JSON"""
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_data, f, indent=2)
    print(f"\n✓ Tokens guardados en {TOKEN_FILE}")


def main():
    """Flujo principal de autenticación"""
    print("=" * 60)
    print("STRAVA OAUTH SETUP")
    print("=" * 60)
    
    # Generar URL de autorización
    auth_url = get_authorization_url()
    
    print("\n1. Abre esta URL en tu navegador:\n")
    print(f"   {auth_url}\n")
    print("2. Autoriza la aplicación en Strava")
    print("3. Serás redirigido a localhost:8001")
    print("\nEsperando autorización...")
    
    # Abrir automáticamente en el navegador
    try:
        webbrowser.open(auth_url)
        print("✓ Navegador abierto automáticamente")
    except:
        print("⚠ No se pudo abrir el navegador automáticamente")
    
    # Iniciar servidor local para capturar el callback
    server = HTTPServer(('localhost', 8001), CallbackHandler)
    
    # Esperar una sola petición (el callback)
    server.handle_request()
    
    if CallbackHandler.authorization_code:
        print("\n✓ Código de autorización recibido")
        print("Intercambiando código por tokens...")
        
        try:
            token_data = exchange_code_for_token(CallbackHandler.authorization_code)
            save_tokens(token_data)
            
            print("\n" + "=" * 60)
            print("AUTENTICACIÓN EXITOSA")
            print("=" * 60)
            print(f"\nAthlete: {token_data.get('athlete', {}).get('firstname', 'N/A')} {token_data.get('athlete', {}).get('lastname', 'N/A')}")
            print(f"Access Token: {token_data['access_token'][:20]}...")
            print(f"Expires at: {token_data['expires_at']}")
            print("\nYa puedes usar la API de Strava!")
            
        except Exception as e:
            print(f"\n✗ Error: {e}")
    else:
        print("\n✗ No se recibió código de autorización")


if __name__ == "__main__":
    main()