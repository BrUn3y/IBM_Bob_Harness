#!/usr/bin/env python3
"""
Script para obtener datos de actividad física de Google Fit API

Usa las credenciales OAuth 2.0 del archivo .env
"""

import os
import datetime
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import json

# Cargar variables de entorno
load_dotenv()

# Scopes necesarios para leer datos de actividad física
SCOPES = [
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.location.read',
    'https://www.googleapis.com/auth/fitness.body.read'
]

def create_credentials_file():
    """Crea el archivo credentials.json desde las variables de entorno"""
    client_id = os.getenv('GOOGLE_FIT_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_FIT_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        raise ValueError("Faltan GOOGLE_FIT_CLIENT_ID o GOOGLE_FIT_CLIENT_SECRET en .env")
    
    credentials = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost:8080/"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
        }
    }
    
    with open('credentials.json', 'w') as f:
        json.dump(credentials, f, indent=2)
    
    print("✅ Archivo credentials.json creado desde .env")

def authenticate():
    """Autentica con Google Fit API usando OAuth 2.0"""
    creds = None
    
    # Crear credentials.json si no existe
    if not os.path.exists('credentials.json'):
        create_credentials_file()
    
    # El archivo token.json almacena los tokens de acceso y refresh
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # Si no hay credenciales válidas, solicita login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=8080)
        
        # Guarda las credenciales para la próxima ejecución
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    return creds

def get_activity_data(service, days_back=7):
    """Obtiene datos de actividad física de los últimos N días"""
    
    # Calcular timestamps en nanosegundos
    end_time = datetime.datetime.now()
    start_time = end_time - datetime.timedelta(days=days_back)
    
    end_time_ns = int(end_time.timestamp() * 1e9)
    start_time_ns = int(start_time.timestamp() * 1e9)
    
    # Tipos de datos disponibles
    data_sources = [
        'derived:com.google.step_count.delta:com.google.android.gms:estimated_steps',
        'derived:com.google.calories.expended:com.google.android.gms:merge_calories_expended',
        'derived:com.google.distance.delta:com.google.android.gms:merge_distance_delta',
        'derived:com.google.active_minutes:com.google.android.gms:merge_active_minutes'
    ]
    
    results = {}
    
    for data_source in data_sources:
        try:
            dataset_id = f"{start_time_ns}-{end_time_ns}"
            
            response = service.users().dataSources().datasets().get(
                userId='me',
                dataSourceId=data_source,
                datasetId=dataset_id
            ).execute()
            
            data_type = data_source.split(':')[1].split('.')[2]
            results[data_type] = response.get('point', [])
            
        except Exception as e:
            print(f"⚠️  Error obteniendo {data_source}: {e}")
    
    return results

def format_activity_summary(data):
    """Formatea los datos de actividad en un resumen legible"""
    
    summary = {
        'pasos_totales': 0,
        'calorias_totales': 0,
        'distancia_total_km': 0,
        'minutos_activos': 0
    }
    
    # Procesar pasos
    if 'step_count' in data:
        for point in data['step_count']:
            for value in point.get('value', []):
                summary['pasos_totales'] += value.get('intVal', 0)
    
    # Procesar calorías
    if 'calories' in data:
        for point in data['calories']:
            for value in point.get('value', []):
                summary['calorias_totales'] += value.get('fpVal', 0)
    
    # Procesar distancia (convertir de metros a km)
    if 'distance' in data:
        for point in data['distance']:
            for value in point.get('value', []):
                summary['distancia_total_km'] += value.get('fpVal', 0) / 1000
    
    # Procesar minutos activos
    if 'active_minutes' in data:
        for point in data['active_minutes']:
            for value in point.get('value', []):
                summary['minutos_activos'] += value.get('intVal', 0)
    
    return summary

def main():
    """Función principal"""
    print("🏃 Conectando a Google Fit API...\n")
    
    try:
        # Autenticar
        creds = authenticate()
        service = build('fitness', 'v1', credentials=creds)
        
        print("✅ Conexión exitosa a Google Fit API\n")
        
        # Obtener datos de los últimos 7 días
        print("📊 Consultando actividad de los últimos 7 días...\n")
        activity_data = get_activity_data(service, days_back=7)
        
        # Formatear resumen
        summary = format_activity_summary(activity_data)
        
        # Mostrar resultados
        print("=" * 50)
        print("RESUMEN DE ACTIVIDAD FÍSICA (últimos 7 días)")
        print("=" * 50)
        print(f"👟 Pasos totales: {summary['pasos_totales']:,}")
        print(f"🔥 Calorías quemadas: {summary['calorias_totales']:.0f} kcal")
        print(f"📏 Distancia recorrida: {summary['distancia_total_km']:.2f} km")
        print(f"⏱️  Minutos activos: {summary['minutos_activos']} min")
        print("=" * 50)
        
        return summary
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

if __name__ == '__main__':
    main()