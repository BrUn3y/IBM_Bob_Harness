# Workshop — Configurar Slack para el agente Bob (paso a paso)

Guía de taller **desde cero**: crear el **workspace** en Slack, crear la **app**
del agente, obtener los **tokens** e **invitar a Bob** al canal. Enfocada **solo
en dejar Slack configurado y listo**.

---

## Cómo funciona (en 30 segundos)

- Bob se conecta a Slack por **Socket Mode**: una conexión WebSocket **saliente**.
- Por eso **NO necesitas** servidor público, dominio, puertos abiertos ni
  "Request URL". Todo sale desde tu máquina/contenedor hacia Slack.

Solo necesitas **dos tokens** de Slack:

| Token | Empieza con | Para qué sirve | Variable |
|---|---|---|---|
| **Bot User OAuth Token** | `xoxb-` | Que el bot **lea y responda** mensajes | `SLACK_BOT_TOKEN` |
| **App-Level Token** | `xapp-` | Habilita la conexión **Socket Mode** | `SLACK_APP_TOKEN` |

---

## Paso 0 — Crear el Workspace de Slack

Si ya tienes un workspace donde puedes crear apps, **salta al Paso 1**.

1. Entra a 👉 **https://slack.com/get-started#/createnew**
2. Escribe tu **correo** y confirma con el **código** que te llega.
3. Ponle **nombre** al workspace (ej. `Workshop-Bob`).
4. Crea (o salta) el **primer canal** — ej. `#general` o `#bob-lab`.
5. Ya dentro del workspace, crea el canal del taller si aún no existe:
   botón **➕ → Create a channel** → nombre `#bob-lab` → **Create**.

> Para crear/instalar apps necesitas permiso en el workspace. En muchos
> workspaces cualquiera puede; en otros lo aprueba un admin. Si te bloquea,
> pide a un admin que apruebe la app.

---

## Paso 1 — Crear la App desde el *manifest*

El *manifest* configura la app **de un solo golpe** (nombre, permisos, eventos y
Socket Mode). En este repo está en `slack/manifest.yaml`.

1. Abre 👉 **https://api.slack.com/apps**
2. Clic en **"Create New App"** (arriba a la derecha).
3. Elige **"From a manifest"**.
4. Selecciona tu **workspace** en el desplegable → **"Next"**.
5. Verás un editor con pestañas **JSON / YAML**. Elige **YAML**, **borra** el
   contenido de ejemplo y **pega** exactamente esto:

   ```yaml
   display_information:
     name: Bob
     description: Talk to the Bob Shell harness from Slack — no @-mention needed.
     background_color: "#1f2937"

   features:
     bot_user:
       display_name: Bob
       always_online: true

   oauth_config:
     scopes:
       bot:
         - chat:write         # publicar respuestas
         - channels:history   # leer mensajes en canales donde está el bot

   settings:
     event_subscriptions:
       bot_events:
         - message.channels   # cada mensaje nuevo en un canal donde está el bot
     socket_mode_enabled: true
     org_deploy_enabled: false
     token_rotation_enabled: false
   ```

6. Clic en **"Next"** y luego **"Create"**.

> **Qué acaba de configurar el manifest:**
> - Un bot llamado **Bob**.
> - Permisos (*scopes*): `chat:write` (responder) y `channels:history` (leer).
> - El evento `message.channels` (Bob "escucha" mensajes nuevos).
> - **Socket Mode activado** (por eso no hace falta URL pública).

---

## Paso 2 — Instalar la App y copiar el **Bot Token** (`xoxb-`)

1. Menú izquierdo → **"OAuth & Permissions"** (o **"Install App"**).
2. Clic en **"Install to Workspace"** → **"Allow"**.
3. Ya instalada, aparece el **"Bot User OAuth Token"**, empieza con **`xoxb-...`**.
4. Clic en **"Copy"**. 👉 Este valor va en **`SLACK_BOT_TOKEN`**.

---

## Paso 3 — Generar el **App-Level Token** (`xapp-`)

Este token habilita **Socket Mode** (la conexión en tiempo real).

1. Menú izquierdo → **"Basic Information"**.
2. Baja a **"App-Level Tokens"** → clic en **"Generate Token and Scopes"**.
3. Ponle un **nombre** (ej. `socket`).
4. Clic en **"Add Scope"** y agrega **`connections:write`**. ⚠️ Este scope es
   **obligatorio**; sin él, Socket Mode no conecta.
5. Clic en **"Generate"**.
6. Copia el token que aparece — empieza con **`xapp-...`**.
   👉 Este valor va en **`SLACK_APP_TOKEN`**.

> ⚠️ **No confundas los dos tokens:**
> - `xoxb-` = **Bot Token** → `SLACK_BOT_TOKEN`
> - `xapp-` = **App-Level Token** → `SLACK_APP_TOKEN`

---

## Paso 4 — (Opcional) Obtener el **Channel ID**

Solo lo necesitas si quieres **restringir** el bot a ciertos canales o fijar un
canal por defecto para tareas programadas. Si lo dejas vacío, el bot responde en
**todos** los canales donde lo invites.

Para obtener el **Channel ID** (empieza con `C...`):

1. En Slack, **clic en el nombre del canal** (arriba) para abrir sus detalles.
2. Baja al fondo del panel **"Channel details"**.
3. Verás el **"Channel ID"**, algo como `C0123ABCD45`. Cópialo.

> Para varios canales, sepáralos con **comas**, sin espacios:
> `C0123ABCD45,C0987ZYXW65`

---

## Paso 5 — Invitar a Bob al canal

Bob **solo ve mensajes en canales donde es miembro**. En el canal del taller
(ej. `#bob-lab`) escribe:

```
/invite @Bob
```

> Con los scopes del manifest, el bot funciona en **canales públicos**. Los
> canales privados requerirían scopes extra (`groups:history` y el evento
> `message.groups`).

Con esto, **Slack ya quedó configurado**: la app existe, está instalada, tienes
los dos tokens y Bob es miembro del canal. ✅

---

## Enlaces útiles

- Dashboard de apps de Slack: **https://api.slack.com/apps**
- Crear app desde manifest (docs): **https://api.slack.com/reference/manifests**
- Socket Mode (docs): **https://api.slack.com/apis/socket-mode**
- App-Level Tokens (docs): **https://api.slack.com/authentication/token-types#app-level**
- Manifest de este proyecto: [`slack/manifest.yaml`](slack/manifest.yaml)
