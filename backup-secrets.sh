#!/bin/bash
# backup-secrets.sh - Crear backup encriptado de todos los secretos
# Uso: ./backup-secrets.sh

set -e

BACKUP_DIR="/tmp/backup-$(date +%Y%m%d-%H%M%S)"
OUTPUT_FILE="secrets-backup-$(date +%Y%m%d-%H%M%S).tar.gz.age"

echo "🔐 Creando backup de secretos..."
mkdir -p "$BACKUP_DIR"

# Copiar archivos con secretos
echo "📋 Recopilando archivos..."
cp .env "$BACKUP_DIR/" 2>/dev/null || echo "⚠️  .env no encontrado"
cp credentials.json "$BACKUP_DIR/" 2>/dev/null || echo "⚠️  credentials.json no encontrado"
cp strava-setup/strava_tokens.json "$BACKUP_DIR/" 2>/dev/null || echo "⚠️  strava_tokens.json no encontrado"
cp workspace/schedules.json "$BACKUP_DIR/" 2>/dev/null || echo "⚠️  schedules.json no encontrado"

# Exportar schedules actuales desde la API
if curl -s http://localhost:8080/schedules > "$BACKUP_DIR/schedules-api.json" 2>/dev/null; then
    echo "✅ Schedules exportados desde API"
else
    echo "⚠️  No se pudo exportar schedules desde API"
fi

# Crear tarball
echo "📦 Comprimiendo..."
cd /tmp
tar czf "$(basename $BACKUP_DIR).tar.gz" "$(basename $BACKUP_DIR)"

# Verificar si age está instalado
if command -v age &> /dev/null; then
    echo "🔒 Encriptando con age..."
    age -p -o "$OUTPUT_FILE" "$(basename $BACKUP_DIR).tar.gz"
    rm "$(basename $BACKUP_DIR).tar.gz"
    echo ""
    echo "✅ Backup encriptado creado: /tmp/$OUTPUT_FILE"
    echo ""
    echo "📋 Contenido del backup:"
    ls -lh "$BACKUP_DIR"
    echo ""
    echo "⚠️  IMPORTANTE:"
    echo "   1. Guarda /tmp/$OUTPUT_FILE en un lugar seguro"
    echo "   2. Anota la contraseña que usaste para encriptar"
    echo "   3. NO subas este archivo a GitHub"
    echo "   4. Guárdalo en: password manager, almacenamiento encriptado, o USB offline"
elif command -v gpg &> /dev/null; then
    echo "🔒 Encriptando con GPG..."
    OUTPUT_FILE="secrets-backup-$(date +%Y%m%d-%H%M%S).tar.gz.gpg"
    gpg --symmetric --cipher-algo AES256 -o "/tmp/$OUTPUT_FILE" "$(basename $BACKUP_DIR).tar.gz"
    rm "$(basename $BACKUP_DIR).tar.gz"
    echo ""
    echo "✅ Backup encriptado creado: /tmp/$OUTPUT_FILE"
    echo ""
    echo "📋 Contenido del backup:"
    ls -lh "$BACKUP_DIR"
    echo ""
    echo "⚠️  IMPORTANTE:"
    echo "   1. Guarda /tmp/$OUTPUT_FILE en un lugar seguro"
    echo "   2. Anota la contraseña que usaste para encriptar"
    echo "   3. NO subas este archivo a GitHub"
    echo "   4. Guárdalo en: password manager, almacenamiento encriptado, o USB offline"
else
    echo "❌ ERROR: ni age ni gpg están instalados"
    echo "   Instala uno de ellos para encriptar el backup:"
    echo "   - age: apt-get install age"
    echo "   - gpg: apt-get install gnupg"
    echo ""
    echo "⚠️  Backup SIN ENCRIPTAR creado en: /tmp/$(basename $BACKUP_DIR).tar.gz"
    echo "   NO lo subas a ningún lado sin encriptarlo primero"
    exit 1
fi

# Limpiar archivos temporales
rm -rf "$BACKUP_DIR"

echo ""
echo "🎯 Siguiente paso: Descargar el archivo encriptado desde /tmp/"
echo "   docker cp bob-harness:/tmp/$OUTPUT_FILE ."
