# Guía: Configurar Google Fit API desde Google Cloud Console

## Paso 1: Acceder a Google Cloud Console

1. Ve a: https://console.cloud.google.com
2. Inicia sesión con tu cuenta de Google
3. Selecciona o crea un proyecto

## Paso 2: Habilitar Google Fit API

### Opción A: Desde la interfaz web
1. En el menú lateral, ve a **APIs & Services** > **Library**
2. Busca "**Fitness API**" o "**Google Fit API**"
3. Haz clic en la API
4. Presiona el botón **"Enable"** (Habilitar)

### Opción B: Usando gcloud CLI (desde terminal)
```bash
# Instalar gcloud CLI si no lo tienes
curl https://sdk.cloud.google.com | bash
exec -l $SHELL

# Iniciar sesión
gcloud auth login

# Configurar proyecto (reemplaza PROJECT_ID con tu ID de proyecto)
gcloud config set project PROJECT_ID

# Habilitar la API de Fitness
gcloud services enable fitness.googleapis.com
```

## Paso 3: Crear Credenciales OAuth 2.0

### Desde la interfaz web:
1. Ve a **APIs & Services** > **Credentials**
2. Clic en **"Create Credentials"** > **"OAuth client ID"**
3. Si es la primera vez, configura la pantalla de consentimiento:
   - Tipo: **External** (para uso personal)
   - Nombre de la app: "Mi App de Fitness"
   - Email de soporte: tu email
   - Scopes: Agregar los siguientes:
     - `https://www.googleapis.com/auth/fitness.activity.read`
     - `https://www.googleapis.com/auth/fitness.location.read`
     - `https://www.googleapis.com/auth/fitness.body.read`
4. Vuelve a **Credentials** > **Create OAuth client ID**
5. Tipo de aplicación: **Desktop app**
6. Nombre: "Google Fit Desktop Client"
7. Clic en **Create**
8. **Descarga el archivo JSON** (credentials.json)

### Usando gcloud CLI:
```bash
# Crear credenciales OAuth (requiere configuración manual posterior en la consola web)
gcloud auth application-default login
```

## Paso 4: Usar el Script Python

1. **Instalar dependencias:**
```bash
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

2. **Colocar credentials.json:**
   - Coloca el archivo `credentials.json` descargado en el mismo directorio que `google_fit_setup.py`

3. **Ejecutar el script:**
```bash
python3 google_fit_setup.py
```

4. **Primera ejecución:**
   - Se abrirá tu navegador
   - Inicia sesión con tu cuenta de Google
   - Autoriza el acceso a tus datos de Fitness
   - El script guardará un `token.json` para futuras ejecuciones

## Paso 5: Verificar que funciona

El script mostrará un resumen como:
```
==================================================
RESUMEN DE ACTIVIDAD FÍSICA (últimos 7 días)
==================================================
👟 Pasos totales: 45,230
🔥 Calorías quemadas: 2,150 kcal
📏 Distancia recorrida: 32.5 km
⏱️  Minutos activos: 180 min
==================================================
```

## Comandos útiles de gcloud

```bash
# Ver proyecto actual
gcloud config get-value project

# Listar APIs habilitadas
gcloud services list --enabled

# Ver información de la API de Fitness
gcloud services describe fitness.googleapis.com

# Deshabilitar la API (si necesitas)
gcloud services disable fitness.googleapis.com
```

## Solución de problemas

### Error: "API not enabled"
```bash
gcloud services enable fitness.googleapis.com
```

### Error: "Invalid credentials"
- Verifica que `credentials.json` esté en el directorio correcto
- Elimina `token.json` y vuelve a autenticarte

### Error: "Access denied"
- Verifica que agregaste los scopes correctos en la pantalla de consentimiento
- Elimina `token.json` y autoriza nuevamente

## Archivos creados

- `google_fit_setup.py` - Script principal para obtener datos
- `credentials.json` - Credenciales OAuth (NO compartir)
- `token.json` - Token de acceso (se genera automáticamente)

## Seguridad

⚠️ **IMPORTANTE:**
- Nunca compartas `credentials.json` o `token.json`
- Agrega estos archivos a `.gitignore`:
```
credentials.json
token.json
```
