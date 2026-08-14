import json
import requests
from datetime import datetime

# Load tokens
with open('strava_tokens.json', 'r') as f:
    tokens = json.load(f)

access_token = tokens['access_token']

# Get all activities
headers = {'Authorization': f'Bearer {access_token}'}
all_runs = []
page = 1

while True:
    response = requests.get(
        'https://www.strava.com/api/v3/athlete/activities',
        headers=headers,
        params={'per_page': 200, 'page': page}
    )
    
    if response.status_code != 200:
        break
    
    activities = response.json()
    if not activities:
        break
    
    # Filter only runs
    runs = [a for a in activities if a['type'] == 'Run']
    all_runs.extend(runs)
    page += 1

# Sort by distance (longest first)
all_runs.sort(key=lambda x: x['distance'], reverse=True)

# Get top 15 longest runs
longest_runs = all_runs[:15]

print(f"Total runs found: {len(all_runs)}")
print(f"\nTop {len(longest_runs)} longest runs:\n")

for i, run in enumerate(longest_runs, 1):
    name = run['name']
    distance_km = run['distance'] / 1000
    moving_time = run['moving_time']
    hours = moving_time // 3600
    minutes = (moving_time % 3600) // 60
    seconds = moving_time % 60
    
    # Calculate pace (min/km)
    pace_seconds = moving_time / (distance_km)
    pace_min = int(pace_seconds // 60)
    pace_sec = int(pace_seconds % 60)
    
    # Heart rate
    avg_hr = run.get('average_heartrate', 'N/A')
    max_hr = run.get('max_heartrate', 'N/A')
    
    # Date
    date = datetime.strptime(run['start_date_local'], '%Y-%m-%dT%H:%M:%SZ')
    date_str = date.strftime('%d/%m/%Y')
    
    # Activity URL
    activity_id = run['id']
    url = f"https://www.strava.com/activities/{activity_id}"
    
    print(f"{i}. {name} - {date_str}")
    print(f"   Distance: {distance_km:.2f} km")
    
    if hours > 0:
        print(f"   Time: {hours}h {minutes}min {seconds}s")
    else:
        print(f"   Time: {minutes}min {seconds}s")
    
    print(f"   Pace: {pace_min}:{pace_sec:02d} min/km")
    
    if avg_hr != 'N/A':
        print(f"   HR avg: {int(avg_hr)} bpm | HR max: {int(max_hr)} bpm")
    else:
        print(f"   HR: No data")
    
    print(f"   URL: {url}")
    print()
