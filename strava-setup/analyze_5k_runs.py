import json
import requests
from datetime import datetime

# Load tokens
with open('strava_tokens.json', 'r') as f:
    tokens = json.load(f)

access_token = tokens['access_token']

# Get activities
headers = {'Authorization': f'Bearer {access_token}'}
params = {
    'per_page': 200,  # Get more activities to find 5Ks
}

response = requests.get(
    'https://www.strava.com/api/v3/athlete/activities',
    headers=headers,
    params=params
)

if response.status_code != 200:
    print(f"Error: {response.status_code}")
    print(response.text)
    exit(1)

activities = response.json()

# Filter for running activities around 5K (4.5km - 5.5km to catch variations)
runs_5k = []
for activity in activities:
    if activity['type'] == 'Run':
        distance_km = activity['distance'] / 1000
        if 4.5 <= distance_km <= 5.5:
            runs_5k.append({
                'name': activity['name'],
                'date': datetime.fromisoformat(activity['start_date'].replace('Z', '+00:00')),
                'distance': distance_km,
                'time': activity['moving_time'],
                'pace': activity['moving_time'] / distance_km / 60,  # min/km
                'avg_hr': activity.get('average_heartrate'),
                'max_hr': activity.get('max_heartrate'),
                'url': f"https://www.strava.com/activities/{activity['id']}"
            })

# Sort by time (fastest first)
runs_5k.sort(key=lambda x: x['time'])

print(f"\n🏃 Encontré {len(runs_5k)} carreras de ~5K en tu historial\n")

if runs_5k:
    print("🏆 TUS MEJORES TIEMPOS EN 5K:\n")
    for i, run in enumerate(runs_5k[:10], 1):  # Top 10
        minutes = run['time'] // 60
        seconds = run['time'] % 60
        pace_min = int(run['pace'])
        pace_sec = int((run['pace'] - pace_min) * 60)
        
        print(f"{i}. {run['name']}")
        print(f"   📅 {run['date'].strftime('%d/%m/%Y')}")
        print(f"   📏 {run['distance']:.2f} km")
        print(f"   ⏱️  {int(minutes)}:{int(seconds):02d}")
        print(f"   🏃 Ritmo: {pace_min}:{pace_sec:02d} min/km")
        if run['avg_hr']:
            print(f"   ❤️  FC promedio: {int(run['avg_hr'])} bpm")
        print(f"   🔗 {run['url']}")
        print()
else:
    print("No encontré carreras de 5K en tu historial.")
    print("\nActividades de running encontradas:")
    running_activities = [a for a in activities if a['type'] == 'Run']
    for activity in running_activities[:5]:
        distance_km = activity['distance'] / 1000
        print(f"  • {activity['name']}: {distance_km:.2f} km")
