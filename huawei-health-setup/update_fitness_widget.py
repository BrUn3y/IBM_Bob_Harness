#!/usr/bin/env python3
"""
Huawei Health Widget Updater for GitHub Profile README
Updates fitness statistics in README.md with data from Huawei Health Kit API
"""

import json
import os
from datetime import datetime, timedelta
import requests

# Huawei Health API endpoints
HUAWEI_API_BASE = "https://health-api.cloud.huawei.com"

def load_credentials():
    """Load credentials from token.json"""
    if not os.path.exists('token.json'):
        raise FileNotFoundError("token.json not found. Please run huawei_health_setup.py first.")
    
    with open('token.json', 'r') as f:
        token_data = json.load(f)
    
    return token_data

def refresh_token_if_needed(token_data):
    """Refresh access token if expired"""
    # Check if token is expired (if expiry info is available)
    if 'expires_at' in token_data:
        expires_at = datetime.fromisoformat(token_data['expires_at'])
        if datetime.now() >= expires_at:
            print("🔄 Token expired, refreshing...")
            return refresh_access_token(token_data)
    
    return token_data

def refresh_access_token(token_data):
    """Refresh the access token using refresh token"""
    if 'refresh_token' not in token_data:
        raise Exception("No refresh token available")
    
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': token_data['refresh_token'],
        'client_id': os.getenv('HUAWEI_CLIENT_ID'),
        'client_secret': os.getenv('HUAWEI_CLIENT_SECRET')
    }
    
    response = requests.post(
        "https://oauth-login.cloud.huawei.com/oauth2/v3/token",
        data=data
    )
    
    if response.status_code == 200:
        new_token_data = response.json()
        # Save updated token
        with open('token.json', 'w') as f:
            json.dump(new_token_data, f, indent=2)
        print("✅ Token refreshed successfully")
        return new_token_data
    else:
        raise Exception(f"Token refresh failed: {response.status_code} - {response.text}")

def get_monthly_stats(access_token):
    """Get fitness statistics for the current month from Huawei Health API"""
    now = datetime.now()
    start_of_month = datetime(now.year, now.month, 1)
    
    # Convert to milliseconds (Huawei API typically uses milliseconds)
    start_time = int(start_of_month.timestamp() * 1000)
    end_time = int(now.timestamp() * 1000)
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    stats = {
        'steps': 0,
        'calories': 0,
        'distance': 0,
        'active_minutes': 0
    }
    
    # Fetch steps data
    try:
        steps_response = requests.get(
            f"{HUAWEI_API_BASE}/healthkit/v1/activityRecords",
            headers=headers,
            params={
                'startTime': start_time,
                'endTime': end_time,
                'dataType': 'STEPS'
            }
        )
        
        if steps_response.status_code == 200:
            steps_data = steps_response.json()
            if 'data' in steps_data:
                for record in steps_data['data']:
                    stats['steps'] += record.get('value', 0)
        else:
            print(f"⚠️ Steps API returned: {steps_response.status_code}")
    except Exception as e:
        print(f"⚠️ Error fetching steps: {e}")
    
    # Fetch calories data
    try:
        calories_response = requests.get(
            f"{HUAWEI_API_BASE}/healthkit/v1/activityRecords",
            headers=headers,
            params={
                'startTime': start_time,
                'endTime': end_time,
                'dataType': 'CALORIES'
            }
        )
        
        if calories_response.status_code == 200:
            calories_data = calories_response.json()
            if 'data' in calories_data:
                for record in calories_data['data']:
                    stats['calories'] += record.get('value', 0)
        else:
            print(f"⚠️ Calories API returned: {calories_response.status_code}")
    except Exception as e:
        print(f"⚠️ Error fetching calories: {e}")
    
    # Fetch distance data
    try:
        distance_response = requests.get(
            f"{HUAWEI_API_BASE}/healthkit/v1/activityRecords",
            headers=headers,
            params={
                'startTime': start_time,
                'endTime': end_time,
                'dataType': 'DISTANCE'
            }
        )
        
        if distance_response.status_code == 200:
            distance_data = distance_response.json()
            if 'data' in distance_data:
                for record in distance_data['data']:
                    # Distance is typically in meters
                    stats['distance'] += record.get('value', 0)
        else:
            print(f"⚠️ Distance API returned: {distance_response.status_code}")
    except Exception as e:
        print(f"⚠️ Error fetching distance: {e}")
    
    # Fetch active minutes data
    try:
        activity_response = requests.get(
            f"{HUAWEI_API_BASE}/healthkit/v1/activityRecords",
            headers=headers,
            params={
                'startTime': start_time,
                'endTime': end_time,
                'dataType': 'ACTIVITY_MINUTES'
            }
        )
        
        if activity_response.status_code == 200:
            activity_data = activity_response.json()
            if 'data' in activity_data:
                for record in activity_data['data']:
                    stats['active_minutes'] += record.get('value', 0)
        else:
            print(f"⚠️ Activity minutes API returned: {activity_response.status_code}")
    except Exception as e:
        print(f"⚠️ Error fetching active minutes: {e}")
    
    return stats

def format_number(num):
    """Format number with thousand separators"""
    return f"{int(num):,}"

def update_readme(stats):
    """Update README.md with new fitness statistics"""
    now = datetime.now()
    month_year = now.strftime("%B %Y")
    
    # Convert distance from meters to km
    distance_km = stats['distance'] / 1000
    
    fitness_section = f"""## 🏃 Fitness Stats ({month_year})

| 👟 Steps | 🔥 Calories | 📏 Distance | ⏱️ Active Minutes |
|----------|-------------|-------------|-------------------|
| {format_number(stats['steps'])} | {format_number(stats['calories'])} | {distance_km:.1f} km | {format_number(stats['active_minutes'])} |

*Updated automatically via Huawei Health API*
"""
    
    # Read current README
    readme_path = '../Brun3y/README.md' if os.path.exists('../Brun3y/README.md') else 'README.md'
    
    with open(readme_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find and replace fitness section
    start_marker = "## 🏃 Fitness Stats"
    end_marker = "*Updated automatically via"
    
    start_idx = content.find(start_marker)
    if start_idx != -1:
        end_idx = content.find(end_marker, start_idx)
        if end_idx != -1:
            end_idx = content.find('\n', end_idx) + 1
            new_content = content[:start_idx] + fitness_section + content[end_idx:]
        else:
            new_content = content[:start_idx] + fitness_section
    else:
        # Append at the end if section doesn't exist
        new_content = content + "\n\n" + fitness_section
    
    # Write updated README
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"✅ README updated with fitness stats for {month_year}")
    print(f"   Steps: {format_number(stats['steps'])}")
    print(f"   Calories: {format_number(stats['calories'])}")
    print(f"   Distance: {distance_km:.1f} km")
    print(f"   Active Minutes: {format_number(stats['active_minutes'])}")

def main():
    """Main function"""
    try:
        print("🏥 Huawei Health Widget Updater")
        print("=" * 50)
        
        # Load credentials
        print("📂 Loading credentials...")
        token_data = load_credentials()
        
        # Refresh token if needed
        token_data = refresh_token_if_needed(token_data)
        
        access_token = token_data.get('access_token')
        if not access_token:
            raise Exception("No access token found in token.json")
        
        print("✅ Credentials loaded")
        print()
        
        # Get monthly statistics
        print("📊 Fetching fitness data from Huawei Health...")
        stats = get_monthly_stats(access_token)
        print("✅ Data fetched successfully")
        print()
        
        # Update README
        print("📝 Updating README...")
        update_readme(stats)
        print()
        
        print("=" * 50)
        print("🎉 Widget update complete!")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print("Run 'python huawei_health_setup.py' first to set up authentication.")
    except Exception as e:
        print(f"❌ Error: {e}")
        raise

if __name__ == '__main__':
    main()
