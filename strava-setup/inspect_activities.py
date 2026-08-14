import json
import requests
from datetime import datetime

# Load tokens
with open('strava_tokens.json', 'r') as f:
    tokens = json.load(f)

access_token = tokens['access_token']

# Get recent activities
headers = {'Authorization': f'Bearer {access_token}'}
response = requests.get(
    'https://www.strava.com/api/v3/athlete/activities',
    headers=headers,
    params={'per_page': 50, 'page': 1}
)

if response.status_code != 200:
    print(f"Error: {response.status_code}")
    print(response.text)
    exit(1)

activities = response.json()

# Group by type
by_type = {}
for activity in activities:
    activity_type = activity.get('type', 'Unknown')
    if activity_type not in by_type:
        by_type[activity_type] = []
    by_type[activity_type].append(activity)

print(f"Total activities: {len(activities)}\n")
print("Activities by type:")
for activity_type, acts in by_type.items():
    print(f"  {activity_type}: {len(acts)}")

print("\n" + "="*80)
print("DETAILED VIEW - WeightTraining activities:")
print("="*80 + "\n")

weight_training = by_type.get('WeightTraining', [])
for i, activity in enumerate(weight_training[:5], 1):
    date = datetime.fromisoformat(activity['start_date'].replace('Z', '+00:00'))
    print(f"{i}. {activity['name']}")
    print(f"   Date: {date.strftime('%d/%m/%Y %H:%M')}")
    print(f"   ID: {activity['id']}")
    print(f"   Type: {activity.get('type')}")
    print(f"   Sport Type: {activity.get('sport_type')}")
    print(f"   Duration: {activity.get('moving_time', 0) // 60} min")
    print(f"   Has heartrate: {activity.get('has_heartrate', False)}")
    print(f"   Avg HR: {activity.get('average_heartrate', 'N/A')}")
    print(f"   Max HR: {activity.get('max_heartrate', 'N/A')}")
    print(f"   Calories: {activity.get('calories', 'N/A')}")
    print(f"   Kilojoules: {activity.get('kilojoules', 'N/A')}")
    
    # Show ALL available fields
    print(f"   Available fields: {', '.join(activity.keys())}")
    print()

print("\n" + "="*80)
print("Sample of other activity types:")
print("="*80 + "\n")

for activity_type, acts in list(by_type.items())[:3]:
    if activity_type != 'WeightTraining' and acts:
        activity = acts[0]
        date = datetime.fromisoformat(activity['start_date'].replace('Z', '+00:00'))
        print(f"Type: {activity_type}")
        print(f"  Name: {activity['name']}")
        print(f"  Date: {date.strftime('%d/%m/%Y')}")
        print(f"  Calories: {activity.get('calories', 'N/A')}")
        print(f"  Kilojoules: {activity.get('kilojoules', 'N/A')}")
        print()
