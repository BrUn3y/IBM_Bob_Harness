# Huawei Health API Setup

Configuración para integrar Huawei Health Kit con tu perfil de GitHub.

## 📋 Requisitos Previos

1. **Cuenta de Desarrollador Huawei**
   - Regístrate en: https://developer.huawei.com/
   - Acepta los términos de servicio

2. **Crear Aplicación en Huawei Console**
   - Ve a: https://developer.huawei.com/consumer/en/console
   - Crea un nuevo proyecto
   - Habilita "Health Kit" en APIs
   - Obtén tu `Client ID` y `Client Secret`

## 🔑 Scopes Necesarios

Para obtener datos de fitness, necesitas estos permisos:

```
https://www.huawei.com/healthkit/step.read
https://www.huawei.com/healthkit/calories.read
https://www.huawei.com/healthkit/distance.read
https://www.huawei.com/healthkit/activity.read
```

## 🚀 Configuración Inicial

### 1. Instalar Dependencias

```bash
pip install -r requirements.txt
```

### 2. Configurar Credenciales

Crea un archivo `.env` con tus credenciales:

```env
HUAWEI_CLIENT_ID=tu_client_id_aqui
HUAWEI_CLIENT_SECRET=tu_client_secret_aqui
HUAWEI_REDIRECT_URI=http://localhost:8080/callback
```

### 3. Ejecutar Setup OAuth

```bash
python huawei_health_setup.py
```

Este script:
- Abrirá tu navegador para autorizar la aplicación
- Guardará el token en `token.json`
- Verificará que puedes acceder a los datos

## 📊 Actualizar Widget de Fitness

Una vez configurado, ejecuta:

```bash
python update_fitness_widget.py
```

Esto actualizará tu `README.md` con:
- 👟 Pasos del mes actual
- 🔥 Calorías quemadas
- 📏 Distancia recorrida
- ⏱️ Minutos activos

## 🔄 Automatización con GitHub Actions

El workflow `.github/workflows/profile-update.yml` ejecutará automáticamente la actualización.

### Configurar Secrets en GitHub

1. Ve a tu repositorio → Settings → Secrets and variables → Actions
2. Agrega estos secrets:
   - `HUAWEI_HEALTH_TOKEN`: contenido completo de `token.json`

## 🔧 Troubleshooting

### Token Expirado

Si el token expira, vuelve a ejecutar:

```bash
python huawei_health_setup.py
```

### Sin Datos

Verifica que:
- Tu dispositivo Huawei está sincronizado con Huawei Health
- Has dado permisos correctos en la app
- Los datos están disponibles en la app de Huawei Health

## 📚 Referencias

- [Huawei Health Kit Documentation](https://developer.huawei.com/consumer/en/doc/HMSCore-Guides/health-introduction-0000001050071661)
- [OAuth 2.0 Guide](https://developer.huawei.com/consumer/en/doc/HMSCore-Guides/open-platform-oauth-0000001053629189)
- [REST API Reference](https://developer.huawei.com/consumer/en/doc/HMSCore-References/rest-overview-0000001254420693)

## ⚠️ Nota Importante

Este script requiere que tengas:
- Un dispositivo Huawei o la app Huawei Health instalada
- Datos de fitness sincronizados en Huawei Health
- Permisos de desarrollador activos en Huawei Developer Console
