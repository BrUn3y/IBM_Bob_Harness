#!/usr/bin/env python3
import requests
import json
import sys
from datetime import datetime

# Credenciales
CLIENT_ID = "197414"
CLIENT_SECRET = "a96a7843d21e79d5520af03696bf57c1a03adaec"

# Obtener código de autorización desde argumentos
if len(sys.argv) > 1:
    AUTH_CODE = sys.argv[1]
else:
    print("❌ Error: Debes proporcionar el código de autorización")
    print("Uso: python3 get_last_activity.py <authorization_code>")
    exit(1)

# Paso 1: Intercambiar código por tokens
token_url = "https://www.strava.com/oauth/token"
token_data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "code": AUTH_CODE,
    "grant_type": "authorization_code"
}

print("🔄 Obteniendo tokens de acceso...")
token_response = requests.post(token_url, data=token_data)

if token_response.status_code != 200:
    print(f"❌ Error al obtener tokens: {token_response.status_code}")
    print(token_response.text)
    exit(1)

tokens = token_response.json()
access_token = tokens["access_token"]

# Guardar tokens
with open("/home/brun3y/IBM_Bob_Harness/strava-setup/strava_tokens.json", "w") as f:
    json.dump(tokens, f, indent=2)
print("✅ Tokens guardados en strava_tokens.json")

# Paso 2: Obtener última actividad
activities_url = "https://www.strava.com/api/v3/athlete/activities"
headers = {"Authorization": f"Bearer {access_token}"}
params = {"per_page": 1}  # Solo la última

print("\n🔄 Consultando última actividad...")
activities_response = requests.get(activities_url, headers=headers, params=params)

if activities_response.status_code != 200:
    print(f"❌ Error al obtener actividades: {activities_response.status_code}")
    print(activities_response.text)
    exit(1)

activities = activities_response.json()

if not activities:
    print("ℹ️ No se encontraron actividades")
    exit(0)

# Mostrar información de la última actividad
activity = activities[0]

print("\n" + "="*60)
print("📊 ÚLTIMA ACTIVIDAD EN STRAVA")
print("="*60)

# Información básica
print(f"\n*Nombre:* {activity.get('name', 'Sin nombre')}")
print(f"*Tipo:* {activity.get('type', 'N/A')}")
print(f"*Deporte:* {activity.get('sport_type', 'N/A')}")

# Fecha
start_date = activity.get('start_date_local', '')
if start_date:
    dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    print(f"*Fecha:* {dt.strftime('%d/%m/%Y a las %H:%M')}")

# Métricas principales
distance_km = activity.get('distance', 0) / 1000
print(f"\n*Distancia:* {distance_km:.2f} km")

moving_time = activity.get('moving_time', 0)
hours = moving_time // 3600
minutes = (moving_time % 3600) // 60
seconds = moving_time % 60
print(f"*Tiempo en movimiento:* {hours}h {minutes}m {seconds}s")

elapsed_time = activity.get('elapsed_time', 0)
hours_e = elapsed_time // 3600
minutes_e = (elapsed_time % 3600) // 60
seconds_e = elapsed_time % 60
print(f"*Tiempo total:* {hours_e}h {minutes_e}m {seconds_e}s")

# Ritmo (si es running/walking)
if distance_km > 0 and activity.get('type') in ['Run', 'Walk']:
    pace_min_per_km = moving_time / 60 / distance_km
    pace_min = int(pace_min_per_km)
    pace_sec = int((pace_min_per_km - pace_min) * 60)
    print(f"*Ritmo promedio:* {pace_min}:{pace_sec:02d} min/km")

# Velocidad
avg_speed = activity.get('average_speed', 0) * 3.6  # m/s a km/h
print(f"*Velocidad promedio:* {avg_speed:.2f} km/h")

max_speed = activity.get('max_speed', 0) * 3.6
print(f"*Velocidad máxima:* {max_speed:.2f} km/h")

# Elevación
total_elevation = activity.get('total_elevation_gain', 0)
print(f"\n*Elevación ganada:* {total_elevation:.0f} m")

# Frecuencia cardíaca
if activity.get('has_heartrate'):
    avg_hr = activity.get('average_heartrate', 0)
    max_hr = activity.get('max_heartrate', 0)
    print(f"\n*Frecuencia cardíaca promedio:* {avg_hr:.0f} bpm")
    print(f"*Frecuencia cardíaca máxima:* {max_hr:.0f} bpm")

# Calorías
calories = activity.get('calories', 0)
if calories > 0:
    print(f"*Calorías:* {calories:.0f} kcal")

# Kudos y comentarios
kudos = activity.get('kudos_count', 0)
comments = activity.get('comment_count', 0)
print(f"\n*Kudos:* {kudos} | *Comentarios:* {comments}")

# Link a la actividad
activity_id = activity.get('id')
print(f"\n*Ver en Strava:* https://www.strava.com/activities/{activity_id}")

print("\n" + "="*60)
