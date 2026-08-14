# VM Backup and Restore Guide

Este repositorio incluye una estrategia de backup completa para reconstruir el ambiente sin almacenar secretos reales en Git.

## Alcance Completo del Backup

### ✅ Incluido en Git (código y configuración)

**Aplicación principal:**
- Scripts de automatización y código de la API
- Workflows de GitHub Actions
- Manifiestos de Slack app
- Configuración de Docker y runtime
- Manifiestos de dependencias
- Fuentes de generación de README
- Guías de setup y notas de restauración

**Integraciones configuradas:**
1. **Strava API**
   - Scripts: `strava-analytics/`, `strava-setup/`, `Brun3y/update_strava_activities.py`
   - Análisis: `analyze_5k_runs.py`, `analyze_crossfit_calories.py`, etc.
   
2. **Google Health/Fit API**
   - Setup: `google-fit-api-setup/`, `google-health-api-setup/`
   - Scripts: `google_fit_setup.py`, `Brun3y/update_fitness_widget.py`
   
3. **IBM Quantum Platform**
   - Script: `check_ibm_quantum_jobs.py`
   - Estado: `quantum_jobs_state.json`
   
4. **Slack Bot**
   - Código: `api/slack_bot.py`
   - Manifest: `slack/manifest.yaml`
   
5. **Scheduler (Cronjobs)**
   - Código: `api/schedules.py`
   - Tests: `api/test_schedules.py`

**Dashboard y README automation:**
- `dashboard/update_dashboard.py`
- `Brun3y/.github/workflows/profile-update.yml`
- `Brun3y/readme.source.md`

### ❌ Excluido de Git (secretos y tokens)

**Archivos con credenciales reales:**
- `.env` (todas las API keys y tokens)
- `credentials.json` (Google OAuth)
- `strava-setup/strava_tokens.json` (Strava OAuth)
- `workspace/schedules.json` (schedules con posibles secretos en prompts)
- Cualquier `*.pem`, `*.key`, `*.p12`, `*.crt`
- Caches de OAuth tokens
- Cookies exportadas del browser
- Archivos de sesión locales

**Contenido generado o desechable:**
- `.git/**`
- `workspace/**` (excepto schedules.json que debe respaldarse aparte)
- `__pycache__/**`
- `.pytest_cache/**`
- `*.pyc`
- Entornos virtuales como `strava-setup/venv/**`

## Secretos Requeridos por Servicio

### 1. Strava API
```bash
# En .env o GitHub Secrets
STRAVA_CLIENT_ID=<tu_client_id>
STRAVA_CLIENT_SECRET=<tu_client_secret>
STRAVA_REFRESH_TOKEN=<tu_refresh_token>

# En strava-setup/strava_tokens.json
{
  "access_token": "<token>",
  "refresh_token": "<token>",
  "expires_at": <timestamp>
}
```

### 2. Google Health/Fit API
```bash
# credentials.json (OAuth 2.0 Client ID)
{
  "installed": {
    "client_id": "<tu_client_id>",
    "client_secret": "<tu_client_secret>",
    "redirect_uris": ["http://localhost"],
    ...
  }
}

# Token generado después de autorización
# Se guarda automáticamente en token.json
```

### 3. IBM Quantum Platform
```bash
# En .env
IBM_QUANTUM_TOKEN=<tu_token>

# quantum_jobs_state.json (se genera automáticamente)
# Contiene el estado de los jobs monitoreados
```

### 4. Slack Bot
```bash
# En .env
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=<secret>
SLACK_DEFAULT_CHANNEL=<channel_id>  # opcional
```

### 5. Bob Shell / Claude API
```bash
# En .env
ANTHROPIC_API_KEY=<tu_api_key>
```

### 6. Cronjobs Persistidos
```bash
# workspace/schedules.json
# Contiene todos los schedules configurados con:
# - cron expressions
# - prompts
# - canales de Slack
# - configuración de retry
```

## Procedimiento de Backup Seguro

### Paso 1: Backup del código (Git)
```bash
cd /home/brun3y/IBM_Bob_Harness
git add -A
git commit -m "backup: full VM state $(date -I)"
git push origin main
```

### Paso 2: Backup de secretos (encriptado)
```bash
# Crear archivo con todos los secretos
tar czf secrets-backup.tar.gz \
  .env \
  credentials.json \
  strava-setup/strava_tokens.json \
  workspace/schedules.json

# Encriptar con GPG
gpg --symmetric --cipher-algo AES256 secrets-backup.tar.gz

# O con age (más moderno)
age -p -o secrets-backup.tar.gz.age secrets-backup.tar.gz

# Guardar secrets-backup.tar.gz.age en:
# - Password manager (1Password, Bitwarden)
# - Almacenamiento encriptado offline
# - Repositorio privado SEPARADO (solo el archivo encriptado)
```

### Paso 3: Backup de schedules activos
```bash
# Exportar schedules actuales
curl -s http://localhost:8080/schedules > schedules-backup.json

# Incluir en el backup encriptado o guardar por separado
```

## Procedimiento de Restauración

### 1. Clonar el repositorio
```bash
git clone https://github.com/BrUn3y/IBM_Bob_Harness.git
cd IBM_Bob_Harness
```

### 2. Restaurar secretos
```bash
# Desencriptar archivo de secretos
gpg -d secrets-backup.tar.gz.gpg > secrets-backup.tar.gz
# O con age
age -d secrets-backup.tar.gz.age > secrets-backup.tar.gz

# Extraer secretos
tar xzf secrets-backup.tar.gz

# Verificar que existen:
ls -la .env credentials.json strava-setup/strava_tokens.json workspace/schedules.json
```

### 3. Configurar GitHub Secrets
En el repositorio `Brun3y/Brun3y`, agregar estos secrets:
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_REFRESH_TOKEN`
- `GOOGLE_FIT_CREDENTIALS` (contenido de credentials.json)

### 4. Levantar el contenedor
```bash
# Construir imagen
docker-compose build

# Iniciar servicios
docker-compose up -d

# Verificar logs
docker-compose logs -f
```

### 5. Restaurar schedules
```bash
# Si schedules.json está en workspace/, el scheduler lo cargará automáticamente
# Si tienes un backup separado:
curl -X POST http://localhost:8080/schedules \
  -H 'Content-Type: application/json' \
  -d @schedules-backup.json
```

### 6. Verificar integraciones

**Strava:**
```bash
cd strava-setup
python3 get_last_activity.py
```

**Google Fit:**
```bash
python3 google_fit_setup.py
```

**IBM Quantum:**
```bash
python3 check_ibm_quantum_jobs.py
```

**Slack Bot:**
```bash
# Verificar en logs que el bot se conectó
docker-compose logs api | grep -i slack
```

**Schedules:**
```bash
# Listar schedules activos
curl http://localhost:8080/schedules

# Verificar crontab
docker-compose exec api crontab -l
```

### 7. Validación final
```bash
# Compilar Python
python3 -m py_compile api/*.py
python3 -m py_compile Brun3y/*.py

# Ejecutar tests
cd api
pytest

# Verificar workflows de GitHub
# Ir a https://github.com/BrUn3y/Brun3y/actions
# Ejecutar manualmente "Profile Update" workflow
```

## Checklist de Restauración

- [ ] Repositorio clonado
- [ ] Secretos desencriptados y colocados
- [ ] GitHub Secrets configurados
- [ ] Contenedor Docker levantado
- [ ] Schedules restaurados
- [ ] Strava API funcionando
- [ ] Google Fit API funcionando
- [ ] IBM Quantum API funcionando
- [ ] Slack Bot conectado
- [ ] Cronjobs instalados en crontab
- [ ] Workflows de GitHub ejecutándose
- [ ] Dashboard actualizado
- [ ] README profile actualizado

## Importante

**NO subas secretos reales a GitHub**, ni siquiera a repositorios privados. Los repositorios privados:
- Amplían el radio de compromiso si hay una brecha
- Hacen más difícil la rotación de secretos
- Pueden volverse públicos accidentalmente

**Siempre encripta los secretos** antes de almacenarlos fuera de un password manager.

## Contacto de Emergencia

Si necesitas restaurar y algo falla:
1. Revisa los logs: `docker-compose logs -f`
2. Verifica variables de entorno: `docker-compose exec api env | grep -E 'STRAVA|SLACK|IBM|ANTHROPIC'`
3. Prueba cada integración por separado
4. Consulta las guías específicas: `GOOGLE_FIT_GUIA.md`, `SLACK_SETUP.md`
