#!/usr/bin/env python3
"""
Script simplificado para autorización de Strava
El usuario pega la URL completa de redirección
"""
import requests
import json
import sys
from urllib.parse import urlparse, parse_qs

CLIENT_ID = "197414"
CLIENT_SECRET = "a96a7843d21e79d5520af03696bf57c1a03adaec"

def extract_code_from_url(url):
    """Extrae el código de autorización de la URL de redirección"""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    return params.get('code', [None])[0]

def exchange_code_for_tokens(code):
    """Intercambia el código por tokens de acceso"""
    token_url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code"
    }
    
    response = requests.post(token_url, data=payload)
    return response

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 strava_auth_simple.py 'URL_COMPLETA_DE_REDIRECCION'")
        print("\nEjemplo:")
        print("python3 strava_auth_simple.py 'http://localhost:8001/callback?code=abc123&scope=...'")
        sys.exit(1)
    
    redirect_url = sys.argv[1]
    
    # Extraer código
    code = extract_code_from_url(redirect_url)
    
    if not code:
        print("✗ No se pudo extraer el código de la URL")
        print(f"URL recibida: {redirect_url}")
        sys.exit(1)
    
    print(f"✓ Código extraído: {code[:10]}...")
    print("\nIntercambiando código por tokens...")
    
    # Intercambiar por tokens
    response = exchange_code_for_tokens(code)
    
    if response.status_code == 200:
        tokens = response.json()
        
        # Guardar tokens
        with open("strava_tokens.json", "w") as f:
            json.dump(tokens, f, indent=2)
        
        print("\n" + "="*60)
        print("✓ ¡AUTORIZACIÓN EXITOSA!")
        print("="*60)
        print(f"\n✓ Tokens guardados en strava_tokens.json")
        print(f"\nInformación del atleta:")
        print(f"  • ID: {tokens['athlete']['id']}")
        print(f"  • Nombre: {tokens['athlete']['firstname']} {tokens['athlete']['lastname']}")
        if 'username' in tokens['athlete']:
            print(f"  • Username: {tokens['athlete']['username']}")
        print(f"\nToken de acceso válido hasta: {tokens.get('expires_at', 'N/A')}")
        print("="*60)
    else:
        print(f"\n✗ Error: {response.status_code}")
        print(response.text)
        sys.exit(1)
