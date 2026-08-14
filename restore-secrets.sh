#!/bin/bash
# restore-secrets.sh - Restaurar secretos desde backup encriptado
# Uso: ./restore-secrets.sh <archivo-backup-encriptado>

set -e

if [ $# -eq 0 ]; then
    echo "❌ ERROR: Debes proporcionar el archivo de backup"
    echo "Uso: ./restore-secrets.sh secrets-backup-YYYYMMDD-HHMMSS.tar.gz.age"
    echo "   o: ./restore-secrets.sh secrets-backup-YYYYMMDD-HHMMSS.tar.gz.gpg"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ ERROR: Archivo no encontrado: $BACKUP_FILE"
    exit 1
fi

echo "🔓 Restaurando secretos desde: $BACKUP_FILE"

# Detectar tipo de encriptación y desencriptar
if [[ "$BACKUP_FILE" == *.age ]]; then
    if ! command -v age &> /dev/null; then
        echo "❌ ERROR: age no está instalado"
        echo "   Instala con: apt-get install age"
        exit 1
    fi
    echo "🔑 Desencriptando con age..."
    DECRYPTED_FILE="${BACKUP_FILE%.age}"
    age -d "$BACKUP_FILE" > "$DECRYPTED_FILE"
elif [[ "$BACKUP_FILE" == *.gpg ]]; then
    if ! command -v gpg &> /dev/null; then
        echo "❌ ERROR: gpg no está instalado"
        echo "   Instala con: apt-get install gnupg"
        exit 1
    fi
    echo "🔑 Desencriptando con GPG..."
    DECRYPTED_FILE="${BACKUP_FILE%.gpg}"
    gpg -d "$BACKUP_FILE" > "$DECRYPTED_FILE"
else
    echo "❌ ERROR: Formato de archivo no reconocido"
    echo "   Debe terminar en .age o .gpg"
    exit 1
fi

# Extraer tarball
echo "📦 Extrayendo archivos..."
TEMP_DIR=$(mktemp -d)
tar xzf "$DECRYPTED_FILE" -C "$TEMP_DIR"

# Encontrar el directorio extraído
BACKUP_DIR=$(find "$TEMP_DIR" -maxdepth 1 -type d -name "backup-*" | head -1)

if [ -z "$BACKUP_DIR" ]; then
    echo "❌ ERROR: No se encontró directorio de backup en el archivo"
    rm -rf "$TEMP_DIR" "$DECRYPTED_FILE"
    exit 1
fi

echo "📋 Restaurando archivos..."

# Restaurar .env
if [ -f "$BACKUP_DIR/.env" ]; then
    cp "$BACKUP_DIR/.env" .
    echo "✅ .env restaurado"
else
    echo "⚠️  .env no encontrado en backup"
fi

# Restaurar credentials.json
if [ -f "$BACKUP_DIR/credentials.json" ]; then
    cp "$BACKUP_DIR/credentials.json" .
    echo "✅ credentials.json restaurado"
else
    echo "⚠️  credentials.json no encontrado en backup"
fi

# Restaurar strava_tokens.json
if [ -f "$BACKUP_DIR/strava_tokens.json" ]; then
    mkdir -p strava-setup
    cp "$BACKUP_DIR/strava_tokens.json" strava-setup/
    echo "✅ strava_tokens.json restaurado"
else
    echo "⚠️  strava_tokens.json no encontrado en backup"
fi

# Restaurar schedules.json
if [ -f "$BACKUP_DIR/schedules.json" ]; then
    mkdir -p workspace
    cp "$BACKUP_DIR/schedules.json" workspace/
    echo "✅ schedules.json restaurado"
else
    echo "⚠️  schedules.json no encontrado en backup"
fi

# Restaurar schedules desde API export si existe
if [ -f "$BACKUP_DIR/schedules-api.json" ]; then
    mkdir -p workspace
    cp "$BACKUP_DIR/schedules-api.json" workspace/
    echo "✅ schedules-api.json restaurado (para referencia)"
fi

# Limpiar archivos temporales
rm -rf "$TEMP_DIR" "$DECRYPTED_FILE"

echo ""
echo "✅ Secretos restaurados exitosamente"
echo ""
echo "📋 Verificación de archivos restaurados:"
echo "----------------------------------------"
[ -f .env ] && echo "✅ .env" || echo "❌ .env"
[ -f credentials.json ] && echo "✅ credentials.json" || echo "❌ credentials.json"
[ -f strava-setup/strava_tokens.json ] && echo "✅ strava-setup/strava_tokens.json" || echo "❌ strava-setup/strava_tokens.json"
[ -f workspace/schedules.json ] && echo "✅ workspace/schedules.json" || echo "❌ workspace/schedules.json"
echo ""
echo "🎯 Próximos pasos:"
echo "   1. Verificar que los secretos son correctos"
echo "   2. Configurar GitHub Secrets en repo Brun3y/Brun3y"
echo "   3. Levantar el contenedor: docker-compose up -d"
echo "   4. Verificar integraciones (ver BACKUP_RESTORE.md)"
