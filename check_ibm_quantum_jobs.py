#!/usr/bin/env python3
"""
Monitor IBM Quantum jobs and notify via Slack when they complete.
Tracks job states and only notifies on status changes.
"""
import os
import json
import requests
from datetime import datetime

# IBM Quantum credentials
IBM_API_KEY = os.environ.get("IBM_QUANTUM_TOKEN", "hds0nIHE023EQitX98p97lh8kNQl_bC6J-BcN-qYxTnz")
IBM_SERVICE_CRN = os.environ.get("IBM_SERVICE_CRN", "crn:v1:bluemix:public:quantum-computing:us-east:a/54e39d6f2e3c400992a744f54921d217:4721cee3-4673-4981-b4ab-81783c3d73ae::")

# State file to track previously seen jobs
STATE_FILE = "/home/brun3y/IBM_Bob_Harness/quantum_jobs_state.json"

def load_state():
    """Load previous job states from file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(state):
    """Save current job states to file."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def get_iam_token():
    """Get IBM Cloud IAM access token using API key."""
    try:
        url = "https://iam.cloud.ibm.com/identity/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        data = {
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": IBM_API_KEY
        }
        
        response = requests.post(url, headers=headers, data=data, timeout=30)
        
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            print(f"Error getting IAM token: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Exception getting IAM token: {e}")
        return None

def get_running_jobs():
    """Get running/pending jobs from IBM Quantum Platform using REST API."""
    try:
        # Primero obtener el IAM token
        iam_token = get_iam_token()
        if not iam_token:
            print("No se pudo obtener el IAM token")
            return []
        
        # IBM Quantum Runtime REST API endpoint (v1)
        url = "https://quantum.cloud.ibm.com/api/v1/jobs"
        
        # Required headers según la documentación oficial
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {iam_token}",
            "IBM-API-Version": "2024-01-01",
            "Service-CRN": IBM_SERVICE_CRN
        }
        
        # Filtrar por jobs pendientes (Queued o Running)
        params = {
            "limit": 50,
            "pending": "true",  # true = Queued/Running, false = Completed/Cancelled/Failed
            "exclude_params": "true"  # No necesitamos los parámetros del job
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            return data.get("jobs", [])
        else:
            print(f"Error fetching jobs: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        print(f"Exception fetching jobs: {e}")
        return []

def format_job_info(job):
    """Format job information for Slack message."""
    job_id = job.get("id", "unknown")
    
    # En API v1, el status puede estar en state.status o directamente en status
    state = job.get("state", {})
    status = state.get("status") if isinstance(state, dict) else job.get("status", "unknown")
    
    # Backend es un string directo en API v1
    backend = job.get("backend", "unknown")
    created = job.get("created", "")
    
    # Program es un objeto con id
    program_obj = job.get("program", {})
    program = program_obj.get("id", "quantum-job") if isinstance(program_obj, dict) else "quantum-job"
    
    return {
        "id": job_id,
        "status": status,
        "backend": backend,
        "program": program,
        "created": created
    }

def check_and_notify():
    """Check for job status changes and return notification message if needed."""
    previous_state = load_state()
    current_jobs = get_running_jobs()
    
    # Build current state
    current_state = {}
    for job in current_jobs:
        job_id = job.get("id")
        if job_id:
            # En API v1, status está en state.status
            state = job.get("state", {})
            status = state.get("status") if isinstance(state, dict) else job.get("status", "unknown")
            
            # Backend es un string directo en API v1
            backend = job.get("backend", "unknown")
            
            # Program es un objeto con id
            program_obj = job.get("program", {})
            program = program_obj.get("id", "quantum-job") if isinstance(program_obj, dict) else "quantum-job"
            
            current_state[job_id] = {
                "status": status,
                "backend": backend,
                "program": program
            }
    
    # Check for completed jobs (were in previous state but not in current)
    completed_jobs = []
    for job_id, prev_info in previous_state.items():
        if job_id not in current_state:
            # Job is no longer running/queued, it must have completed
            completed_jobs.append({
                "id": job_id,
                "backend": prev_info.get("backend", "unknown"),
                "program": prev_info.get("program", "quantum-job")
            })
    
    # Save current state
    save_state(current_state)
    
    # Build notification message
    if completed_jobs:
        message = "*🎉 IBM Quantum Jobs Completados*\n\n"
        for job in completed_jobs:
            message += f"• *Job ID:* `{job['id']}`\n"
            message += f"  *Backend:* {job['backend']}\n"
            message += f"  *Programa:* {job['program']}\n"
            message += f"  *Estado:* Completado ✅\n\n"
        
        # Add info about remaining jobs
        if current_state:
            message += f"_Jobs aún corriendo: {len(current_state)}_"
        else:
            message += "_No hay más jobs en ejecución_"
        
        return message
    
    # No completed jobs, don't notify
    return None

if __name__ == "__main__":
    result = check_and_notify()
    if result:
        print(result)
    # If no result, script exits silently (no notification needed)
