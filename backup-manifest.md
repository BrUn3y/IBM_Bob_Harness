# Manifest Completo de Backup

Este manifest define TODO lo que debe preservarse de esta VM para reconstruir el ambiente completamente.

## ✅ Incluir en Git (Código y Configuración)

### Archivos raíz del proyecto
- `.dockerignore`
- `.gitignore`
- `Dockerfile`
- `docker-compose.yml`
- `entrypoint.sh`
- `run-harness.sh`
- `README.md`
- `BACKUP_RESTORE.md` ← Guía de restauración
- `backup-manifest.md` ← Este archivo
- `GOOGLE_FIT_GUIA.md`
- `SLACK_SETUP.md`

### Scripts de integración
- `check_ibm_quantum_jobs.py` ← IBM Quantum Platform
- `google_fit_setup.py` ← Google Fit API
- `quantum_jobs_state.json` ← Estado de jobs (sin secretos)

### Configuración de Bob
- `.bob/custom_modes.yaml`
- `.bob/rules-unrestricted-dev/AGENT.md`
- `.bob/notes/pending-notes.txt` (si no contiene secretos)

### API y servicios
- `api/requirements.txt`
- `api/requirements-dev.txt`
- `api/schedules.py` ← Scheduler de cronjobs
- `api/server.py` ← FastAPI server
- `api/slack_bot.py` ← Slack Socket Mode bot
- `api/test_schedules.py`
- `api/test_server.py`
- `api/test_slack_bot.py`

### Automatización de README/Profile
- `Brun3y/index.html`
- `Brun3y/README.md`
- `Brun3y/readme.source.md` ← Fuente del README
- `Brun3y/update_fitness_widget.py` ← Google Fit widget
- `Brun3y/update_strava_activities.py` ← Strava activities
- `Brun3y/scripts/**` ← Scripts de generación
- `Brun3y/assets/**` ← Assets SVG y banners
- `Brun3y/.github/workflows/**` ← GitHub Actions workflows

### Dashboard
- `dashboard/index.html`
- `dashboard/update_dashboard.py`

### Slack
- `slack/manifest.yaml` ← Configuración de Slack App

### Proyectos de setup/referencia
- `google-fit-api-setup/**`
- `google-health-api-setup/**`
- `huawei-health-setup/**`
- `strava-analytics/**`
- `strava-setup/**` (scripts, NO tokens)

## 🔒 Excluir de Git - Respaldar Encriptado

### Archivos con secretos CRÍTICOS

**Variables de entorno:**
- `.env` ← TODAS las API keys y tokens

**OAuth y tokens:**
- `credentials.json` ← Google OAuth Client ID
- `strava-setup/strava_tokens.json` ← Strava access/refresh tokens
- Cualquier `token.json`, `*.token`, `*_token.json`

**Schedules con configuración:**
- `workspace/schedules.json` ← Cronjobs configurados (puede contener secretos en prompts)

**Certificados y claves:**
- `*.pem`, `*.key`, `*.p12`, `*.crt`
- Cookies exportadas del browser
- Archivos de sesión locales

### Contenido generado (NO respaldar)
- `.git/**` (el repo ya está en GitHub)
- `workspace/**` (excepto schedules.json)
- `__pycache__/**`
- `.pytest_cache/**`
- `*.pyc`
- `venv/**`, `*/venv/**` (entornos virtuales)

## 📋 Secretos Requeridos por Servicio

### 1. Strava API
**Ubicación:** `.env` + `strava-setup/strava_tokens.json`
```bash
STRAVA_CLIENT_ID=<client_id>
STRAVA_CLIENT_SECRET=<client_secret>
STRAVA_REFRESH_TOKEN=<refresh_token>
```

**GitHub Secrets (repo Brun3y/Brun3y):**
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_REFRESH_TOKEN`

### 2. Google Health/Fit API
**Ubicación:** `credentials.json`
```json
{
  "installed": {
    "client_id": "<client_id>",
    "client_secret": "<client_secret>",
    "redirect_uris": ["http://localhost"],
    ...
  }
}
```

**GitHub Secrets (repo Brun3y/Brun3y):**
- `GOOGLE_FIT_CREDENTIALS` (contenido completo de credentials.json)

### 3. IBM Quantum Platform
**Ubicación:** `.env`
```bash
IBM_QUANTUM_TOKEN=<token>
```

### 4. Slack Bot
**Ubicación:** `.env`
```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=<secret>
SLACK_DEFAULT_CHANNEL=<channel_id>
```

### 5. Bob Shell / Claude API
**Ubicación:** `.env`
```bash
ANTHROPIC_API_KEY=<api_key>
```

### 6. Cronjobs Activos
**Ubicación:** `workspace/schedules.json`

Contiene todos los schedules configurados:
- Expresiones cron
- Prompts para Bob
- Canales de Slack para notificaciones
- Configuración de retry y timeout

**Schedules actuales (según crontab):**
1. `6d5435b73b93` - Limpieza diaria de sistema (16:00 UTC)
2. `198210d17d16` - Daily README update (02:00 UTC)
3. `1f7a4e2366dd` - Actualización diaria del dashboard (09:00 UTC)

## 🔐 Comando de Backup Completo

```bash
#!/bin/bash
# backup-secrets.sh - Crear backup encriptado de todos los secretos

BACKUP_DIR="/tmp/backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Copiar archivos con secretos
cp .env "$BACKUP_DIR/"
cp credentials.json "$BACKUP_DIR/" 2>/dev/null || true
cp strava-setup/strava_tokens.json "$BACKUP_DIR/" 2>/dev/null || true
cp workspace/schedules.json "$BACKUP_DIR/" 2>/dev/null || true

# Crear tarball
cd /tmp
tar czf secrets-backup.tar.gz "$(basename $BACKUP_DIR)"

# Encriptar con age (recomendado) o gpg
age -p -o secrets-backup.tar.gz.age secrets-backup.tar.gz
# O con GPG:
# gpg --symmetric --cipher-algo AES256 secrets-backup.tar.gz

# Limpiar archivos temporales
rm -rf "$BACKUP_DIR" secrets-backup.tar.gz

echo "✅ Backup encriptado creado: secrets-backup.tar.gz.age"
echo "⚠️  Guarda este archivo en un lugar seguro (password manager, almacenamiento encriptado)"
```

## 🔄 Comando de Restauración

```bash
#!/bin/bash
# restore-secrets.sh - Restaurar secretos desde backup encriptado

# Desencriptar
age -d secrets-backup.tar.gz.age > secrets-backup.tar.gz
# O con GPG:
# gpg -d secrets-backup.tar.gz.gpg > secrets-backup.tar.gz

# Extraer
tar xzf secrets-backup.tar.gz

# Mover archivos a sus ubicaciones
BACKUP_DIR=$(tar tzf secrets-backup.tar.gz | head -1 | cut -d/ -f1)
cp "$BACKUP_DIR/.env" .
cp "$BACKUP_DIR/credentials.json" . 2>/dev/null || true
cp "$BACKUP_DIR/strava_tokens.json" strava-setup/ 2>/dev/null || true
mkdir -p workspace
cp "$BACKUP_DIR/schedules.json" workspace/ 2>/dev/null || true

# Limpiar
rm -rf "$BACKUP_DIR" secrets-backup.tar.gz

echo "✅ Secretos restaurados"
echo "📋 Verifica que existan:"
ls -la .env credentials.json strava-setup/strava_tokens.json workspace/schedules.json
```

## ✅ Verificación Pre-Backup

Antes de hacer push del backup a GitHub, ejecuta:

```bash
# Buscar secretos obvios
rg -n "token|secret|client_secret|access_token|refresh_token|BEGIN PRIVATE KEY|password|api_key" . \
  --type-not lock \
  --glob '!.git' \
  --glob '!workspace' \
  --glob '!venv' \
  --glob '!__pycache__'

# Verificar que archivos excluidos NO estén staged
git status --ignored

# Confirmar .gitignore está actualizado
cat .gitignore | grep -E "\.env|credentials\.json|strava_tokens\.json|workspace/"
```

## 📊 Resumen de Integraciones

| Servicio | Scripts | Secretos | GitHub Secrets | Cronjob |
|----------|---------|----------|----------------|---------|
| **Strava** | `update_strava_activities.py`, `strava-analytics/*` | `.env`, `strava_tokens.json` | ✅ 3 secrets | ❌ (via GitHub Actions) |
| **Google Fit** | `update_fitness_widget.py`, `google_fit_setup.py` | `credentials.json` | ✅ 1 secret | ❌ (via GitHub Actions) |
| **IBM Quantum** | `check_ibm_quantum_jobs.py` | `.env` | ❌ | ❌ |
| **Slack Bot** | `api/slack_bot.py` | `.env` | ❌ | ✅ (siempre activo) |
| **README Update** | `Brun3y/.github/workflows/profile-update.yml` | GitHub Secrets | ✅ | ✅ (02:00 UTC) |
| **Dashboard** | `dashboard/update_dashboard.py` | - | ❌ | ✅ (09:00 UTC) |
| **System Cleanup** | (prompt en schedule) | - | ❌ | ✅ (16:00 UTC) |

## 🎯 Checklist de Backup Completo

- [ ] Código pusheado a GitHub
- [ ] Backup encriptado de secretos creado
- [ ] Backup guardado en lugar seguro (password manager)
- [ ] GitHub Secrets verificados en repo Brun3y/Brun3y
- [ ] Schedules exportados (`curl http://localhost:8080/schedules > schedules-backup.json`)
- [ ] Documentación actualizada (BACKUP_RESTORE.md)
- [ ] Verificación de que NO hay secretos en Git (`rg` ejecutado)

## ⚠️ IMPORTANTE

**NUNCA subas secretos reales a GitHub**, ni siquiera a repos privados:
- Los repos privados pueden volverse públicos accidentalmente
- Amplían el radio de compromiso si hay una brecha
- Dificultan la rotación de secretos
- Pueden ser accedidos por colaboradores no autorizados

**SIEMPRE encripta** antes de almacenar fuera de un password manager.
