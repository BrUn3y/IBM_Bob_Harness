import json
import requests
from datetime import datetime

# Load tokens
with open('strava_tokens.json', 'r') as f:
    tokens = json.load(f)

access_token = tokens['access_token']

# Get all activities
headers = {'Authorization': f'Bearer {access_token}'}
all_activities = []
page = 1

while True:
    response = requests.get(
        'https://www.strava.com/api/v3/athlete/activities',
        headers=headers,
        params={'per_page': 200, 'page': page}
    )
    
    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        print(response.text)
        break
    
    activities = response.json()
    if not activities:
        break
    
    all_activities.extend(activities)
    page += 1

# Filter for activities with calories (excluding runs)
activities_with_calories = []
for activity in all_activities:
    activity_type = activity.get('type', '').lower()
    calories = activity.get('calories')
    
    # Include all activities with calories except pure running
    if calories and activity_type not in ['run']:
        activities_with_calories.append(activity)

# Sort by calories (descending)
activities_with_calories.sort(key=lambda x: x.get('calories', 0), reverse=True)

print(f"Total activities with calorie data (excluding runs): {len(activities_with_calories)}")
print("\nTop sessions by calories burned:\n")

for i, activity in enumerate(activities_with_calories[:15], 1):
    date = datetime.fromisoformat(activity['start_date'].replace('Z', '+00:00'))
    name = activity['name']
    calories = activity.get('calories', 0)
    duration = activity['moving_time'] // 60  # minutes
    avg_hr = activity.get('average_heartrate', 0)
    max_hr = activity.get('max_heartrate', 0)
    activity_id = activity['id']
    activity_type = activity.get('type', 'N/A')
    sport_type = activity.get('sport_type', 'N/A')
    
    print(f"{i}. {name}")
    print(f"   Date: {date.strftime('%d/%m/%Y')}")
    print(f"   Type: {activity_type} / Sport: {sport_type}")
    print(f"   Calories: {calories:.0f} kcal")
    print(f"   Duration: {duration} min")
    if avg_hr:
        print(f"   Avg HR: {avg_hr:.0f} bpm")
    if max_hr:
        print(f"   Max HR: {max_hr:.0f} bpm")
    print(f"   URL: https://www.strava.com/activities/{activity_id}")
    print()
