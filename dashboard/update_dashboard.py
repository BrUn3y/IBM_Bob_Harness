#!/usr/bin/env python3
"""
Script para actualizar el dashboard con métricas del sistema en tiempo real.
Recopila información del sistema y actualiza el archivo HTML.
"""

import subprocess
import re
from datetime import datetime, timezone
import os

def run_command(cmd):
    """Ejecuta un comando y retorna su salida."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {str(e)}"

def get_cpu_info():
    """Obtiene información de CPU."""
    cores = run_command("nproc")
    load_avg = run_command("uptime | awk -F'load average:' '{print $2}' | xargs")
    arch = run_command("uname -m")
    
    # Calcular porcentaje de uso de CPU basado en load average
    try:
        load_1min = float(load_avg.split(',')[0].strip())
        cpu_percent = min(100, (load_1min / int(cores)) * 100)
    except:
        cpu_percent = 0
    
    return {
        'cores': cores,
        'load_avg': load_avg,
        'arch': arch,
        'percent': round(cpu_percent, 1)
    }

def get_memory_info():
    """Obtiene información de memoria RAM."""
    mem_output = run_command("free -h | grep Mem:")
    swap_output = run_command("free -h | grep Swap:")
    
    mem_parts = mem_output.split()
    swap_parts = swap_output.split()
    
    total = mem_parts[1] if len(mem_parts) > 1 else "0"
    used = mem_parts[2] if len(mem_parts) > 2 else "0"
    available = mem_parts[6] if len(mem_parts) > 6 else "0"
    
    swap_total = swap_parts[1] if len(swap_parts) > 1 else "0"
    swap_used = swap_parts[2] if len(swap_parts) > 2 else "0"
    
    # Calcular porcentaje
    try:
        mem_bytes = run_command("free -b | grep Mem: | awk '{print $2, $3}'").split()
        percent = round((int(mem_bytes[1]) / int(mem_bytes[0])) * 100, 1)
    except:
        percent = 0
    
    return {
        'total': total,
        'used': used,
        'available': available,
        'swap_total': swap_total,
        'swap_used': swap_used,
        'percent': percent
    }

def get_disk_info():
    """Obtiene información de disco."""
    disk_output = run_command("df -h / | tail -1")
    parts = disk_output.split()
    
    total = parts[1] if len(parts) > 1 else "0"
    used = parts[2] if len(parts) > 2 else "0"
    available = parts[3] if len(parts) > 3 else "0"
    percent_str = parts[4] if len(parts) > 4 else "0%"
    percent = int(percent_str.replace('%', ''))
    
    return {
        'total': total,
        'used': used,
        'available': available,
        'percent': percent
    }

def get_uptime_info():
    """Obtiene información de uptime."""
    uptime_output = run_command("uptime -p")
    uptime_clean = uptime_output.replace('up ', '')
    
    users = run_command("who | wc -l")
    
    return {
        'uptime': uptime_clean,
        'users': users
    }

def get_system_info():
    """Obtiene información general del sistema."""
    os_name = run_command("cat /etc/os-release | grep PRETTY_NAME | cut -d'=' -f2 | tr -d '\"'")
    kernel = run_command("uname -r")
    hostname = run_command("hostname")
    arch = run_command("uname -m")
    
    # Detectar plataforma
    platform = "Unknown"
    if "gcp" in kernel.lower() or "google" in hostname.lower():
        platform = "Google Cloud Platform (GCP)"
    elif "aws" in hostname.lower() or "ec2" in hostname.lower():
        platform = "Amazon Web Services (AWS)"
    elif "azure" in hostname.lower():
        platform = "Microsoft Azure"
    
    # Obtener particiones
    partitions = run_command("df -h | grep -E '(/boot|/boot/efi)' | awk '{print $1 \" (\" $2 \")\"}'")
    partitions_list = partitions.replace('\n', ', ')
    
    return {
        'os_name': os_name,
        'kernel': kernel,
        'hostname': hostname,
        'platform': platform,
        'arch': arch,
        'partitions': partitions_list
    }

def get_progress_class(percent):
    """Determina la clase CSS según el porcentaje."""
    if percent >= 80:
        return "danger"
    elif percent >= 60:
        return "warning"
    return ""

def update_html():
    """Actualiza el archivo HTML con las métricas actuales."""
    html_path = "/home/brun3y/IBM_Bob_Harness/dashboard/index.html"
    
    # Recopilar todas las métricas
    cpu = get_cpu_info()
    memory = get_memory_info()
    disk = get_disk_info()
    uptime = get_uptime_info()
    system = get_system_info()
    
    # Timestamp actual
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Leer el HTML actual
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Actualizar timestamp
    html_content = re.sub(
        r'<span id="lastUpdate">.*?</span>',
        f'<span id="lastUpdate">{timestamp}</span>',
        html_content
    )
    
    # Actualizar CPU - valor
    html_content = re.sub(
        r'(<div class="card-title">.*?⚡.*?CPU.*?</div>\s*<div class="card-value">)[^<]+(</div>)',
        rf'\g<1>{cpu["cores"]} Cores\g<2>',
        html_content,
        flags=re.DOTALL
    )
    
    # Actualizar CPU - load average
    html_content = re.sub(
        r'(Load Average: )[^<]+',
        rf'\g<1>{cpu["load_avg"]}',
        html_content
    )
    
    # Actualizar CPU - progress bar
    cpu_progress_pattern = r'(<!-- CPU Card -->.*?<div class="progress-fill[^"]*")(\s+style="width: )\d+%'
    cpu_class = get_progress_class(cpu["percent"])
    if cpu_class:
        html_content = re.sub(
            cpu_progress_pattern,
            rf'\g<1> {cpu_class}\g<2>{cpu["percent"]}%',
            html_content,
            flags=re.DOTALL
        )
    else:
        html_content = re.sub(
            cpu_progress_pattern,
            rf'\g<1>\g<2>{cpu["percent"]}%',
            html_content,
            flags=re.DOTALL
        )
    
    # Actualizar RAM - valor
    html_content = re.sub(
        r'(<div class="card-title">.*?💾.*?Memoria RAM.*?</div>\s*<div class="card-value">)[^<]+(</div>)',
        rf'\g<1>{memory["used"]} / {memory["total"]}\g<2>',
        html_content,
        flags=re.DOTALL
    )
    
    # Actualizar RAM - detalles
    html_content = re.sub(
        r'(Usado: )\d+\.?\d*%',
        rf'\g<1>{memory["percent"]}%',
        html_content
    )
    html_content = re.sub(
        r'(Disponible: )[^<]+',
        rf'\g<1>{memory["available"]}',
        html_content
    )
    html_content = re.sub(
        r'(Swap: )[^<]+',
        rf'\g<1>{memory["swap_used"]} / {memory["swap_total"]}',
        html_content
    )
    
    # Actualizar RAM - progress bar
    mem_progress_pattern = r'(<!-- RAM Card -->.*?<div class="progress-fill[^"]*")(\s+style="width: )\d+\.?\d*%'
    mem_class = get_progress_class(memory["percent"])
    if mem_class:
        html_content = re.sub(
            mem_progress_pattern,
            rf'\g<1> {mem_class}\g<2>{memory["percent"]}%',
            html_content,
            flags=re.DOTALL
        )
    else:
        html_content = re.sub(
            mem_progress_pattern,
            rf'\g<1>\g<2>{memory["percent"]}%',
            html_content,
            flags=re.DOTALL
        )
    
    # Actualizar Disco - valor
    html_content = re.sub(
        r'(<div class="card-title">.*?💿.*?Almacenamiento.*?</div>\s*<div class="card-value">)[^<]+(</div>)',
        rf'\g<1>{disk["used"]} / {disk["total"]}\g<2>',
        html_content,
        flags=re.DOTALL
    )
    
    # Actualizar Disco - detalles
    html_content = re.sub(
        r'(<!-- Disco Card -->.*?Usado: )\d+%',
        rf'\g<1>{disk["percent"]}%',
        html_content,
        flags=re.DOTALL
    )
    html_content = re.sub(
        r'(<!-- Disco Card -->.*?Disponible: )[^<]+',
        rf'\g<1>{disk["available"]}',
        html_content,
        flags=re.DOTALL
    )
    
    # Actualizar Disco - progress bar
    disk_progress_pattern = r'(<!-- Disco Card -->.*?<div class="progress-fill[^"]*")(\s+style="width: )\d+%'
    disk_class = get_progress_class(disk["percent"])
    if disk_class:
        html_content = re.sub(
            disk_progress_pattern,
            rf'\g<1> {disk_class}\g<2>{disk["percent"]}%',
            html_content,
            flags=re.DOTALL
        )
    else:
        html_content = re.sub(
            disk_progress_pattern,
            rf'\g<1>\g<2>{disk["percent"]}%',
            html_content,
            flags=re.DOTALL
        )
    
    # Actualizar Uptime - valor
    html_content = re.sub(
        r'(<div class="card-title">.*?⏱️.*?Tiempo Activo.*?</div>\s*<div class="card-value">)[^<]+(</div>)',
        rf'\g<1>{uptime["uptime"]}\g<2>',
        html_content,
        flags=re.DOTALL
    )
    html_content = re.sub(
        r'(Usuarios conectados: )\d+',
        rf'\g<1>{uptime["users"]}',
        html_content
    )
    
    # Actualizar información del sistema
    html_content = re.sub(
        r'(<span class="info-label">Sistema Operativo</span>\s*<span class="info-value">)[^<]+(</span>)',
        rf'\g<1>{system["os_name"]}\g<2>',
        html_content,
        flags=re.DOTALL
    )
    html_content = re.sub(
        r'(<span class="info-label">Kernel</span>\s*<span class="info-value">)[^<]+(</span>)',
        rf'\g<1>Linux {system["kernel"]}\g<2>',
        html_content,
        flags=re.DOTALL
    )
    html_content = re.sub(
        r'(<span class="info-label">Hostname</span>\s*<span class="info-value">)[^<]+(</span>)',
        rf'\g<1>{system["hostname"]}\g<2>',
        html_content,
        flags=re.DOTALL
    )
    html_content = re.sub(
        r'(<span class="info-label">Plataforma</span>\s*<span class="info-value">)[^<]+(</span>)',
        rf'\g<1>{system["platform"]}\g<2>',
        html_content,
        flags=re.DOTALL
    )
    html_content = re.sub(
        r'(<span class="info-label">Particiones</span>\s*<span class="info-value">)[^<]+(</span>)',
        rf'\g<1>{system["partitions"]}\g<2>',
        html_content,
        flags=re.DOTALL
    )
    
    # Escribir el HTML actualizado
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✅ Dashboard actualizado exitosamente: {timestamp}")
    print(f"📊 CPU: {cpu['percent']}% | RAM: {memory['percent']}% | Disco: {disk['percent']}%")

if __name__ == "__main__":
    update_html()