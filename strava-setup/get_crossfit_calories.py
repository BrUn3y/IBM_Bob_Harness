import json
import requests
from datetime import datetime
import time

# Load tokens
with open('strava_tokens.json', 'r') as f:
    tokens = json.load(f)

access_token = tokens['access_token']
headers = {'Authorization': f'Bearer {access_token}'}

# Get all activities
all_activities = []
page = 1

while True:
    response = requests.get(
        'https://www.strava.com/api/v3/athlete/activities',
        headers=headers,
        params={'per_page': 200, 'page': page}
    )
    
    if response.status_code != 200:
        print(f"Error getting activities: {response.status_code}")
        break
    
    activities = response.json()
    if not activities:
        break
    
    all_activities.extend(activities)
    page += 1

# Filter for CrossFit and Workout activities
target_activities = []
for activity in all_activities:
    activity_type = activity.get('type', '')
    if activity_type in ['Crossfit', 'Workout', 'WeightTraining']:
        target_activities.append(activity)

print(f"Found {len(target_activities)} CrossFit/Workout/WeightTraining activities")
print("Fetching detailed data with calories...\n")

# Get detailed info for each activity
detailed_activities = []
for i, activity in enumerate(target_activities, 1):
    activity_id = activity['id']
    
    # Get detailed activity data
    response = requests.get(
        f'https://www.strava.com/api/v3/activities/{activity_id}',
        headers=headers
    )
    
    if response.status_code == 200:
        detailed = response.json()
        calories = detailed.get('calories')
        
        if calories:
            detailed_activities.append(detailed)
            print(f"  {i}/{len(target_activities)}: {activity['name']} - {calories:.0f} kcal")
        else:
            print(f"  {i}/{len(target_activities)}: {activity['name']} - No calorie data")
    else:
        print(f"  {i}/{len(target_activities)}: Error fetching details")
    
    # Rate limiting
    time.sleep(0.2)

# Sort by calories
detailed_activities.sort(key=lambda x: x.get('calories', 0), reverse=True)

print(f"\n{'='*80}")
print(f"TOP SESSIONS BY CALORIES BURNED:")
print(f"{'='*80}\n")

for i, activity in enumerate(detailed_activities[:10], 1):
    date = datetime.fromisoformat(activity['start_date'].replace('Z', '+00:00'))
    name = activity['name']
    calories = activity.get('calories', 0)
    duration = activity['moving_time'] // 60
    avg_hr = activity.get('average_heartrate', 0)
    max_hr = activity.get('max_heartrate', 0)
    activity_id = activity['id']
    activity_type = activity.get('type', 'N/A')
    
    print(f"{i}. {name}")
    print(f"   📅 Date: {date.strftime('%d/%m/%Y')}")
    print(f"   🏋️ Type: {activity_type}")
    print(f"   🔥 Calories: {calories:.0f} kcal")
    print(f"   ⏱️ Duration: {duration} min")
    if avg_hr:
        print(f"   ❤️ Avg HR: {avg_hr:.0f} bpm")
    if max_hr:
        print(f"   💓 Max HR: {max_hr:.0f} bpm")
    print(f"   🔗 URL: https://www.strava.com/activities/{activity_id}")
    print()
