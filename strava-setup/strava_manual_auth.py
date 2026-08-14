#!/usr/bin/env python3
"""
Script para autorización manual de Strava
"""

CLIENT_ID = "197414"
CLIENT_SECRET = "a96a7843d21e79d5520af03696bf57c1a03adaec"
REDIRECT_URI = "http://localhost:8001/callback"

# URL de autorización
auth_url = f"https://www.strava.com/oauth/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=read,activity:read_all,profile:read_all"

print("=" * 60)
print("AUTORIZACIÓN MANUAL DE STRAVA")
print("=" * 60)
print("\n1. Abre esta URL en tu navegador:\n")
print(auth_url)
print("\n2. Después de autorizar, Strava intentará redirigirte a localhost")
print("3. La URL en tu navegador se verá así:")
print("   http://localhost:8001/callback?code=XXXXXX&scope=...")
print("\n4. COPIA el código que aparece después de 'code=' (antes del '&')")
print("5. Pégalo aquí cuando te lo pida\n")
print("=" * 60)

code = input("\nPega el código de autorización aquí: ").strip()

# Intercambiar código por tokens
import requests
import json

token_url = "https://www.strava.com/oauth/token"
payload = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "code": code,
    "grant_type": "authorization_code"
}

print("\nIntercambiando código por tokens...")
response = requests.post(token_url, data=payload)

if response.status_code == 200:
    tokens = response.json()
    
    # Guardar tokens
    with open("strava_tokens.json", "w") as f:
        json.dump(tokens, f, indent=2)
    
    print("\n✓ ¡Autorización exitosa!")
    print(f"✓ Tokens guardados en strava_tokens.json")
    print(f"\nInformación del atleta:")
    print(f"  - ID: {tokens['athlete']['id']}")
    print(f"  - Nombre: {tokens['athlete']['firstname']} {tokens['athlete']['lastname']}")
    print(f"  - Username: {tokens['athlete']['username']}")
else:
    print(f"\n✗ Error: {response.status_code}")
    print(response.text)

