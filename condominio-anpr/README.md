# 🚧 Condominio ANPR

Sistema de **control de acceso vehicular por lectura de placas (ANPR)** para
condominios, pensado para la cámara **Dahua ITC413-PW4D-IZ1** (y compatibles de
la serie ITC / DHI que hacen reconocimiento de placas a bordo).

Hace tres cosas:

1. **Lee y registra placas** — la cámara reconoce la matrícula y envía el evento
   al sistema, que la busca en la **lista blanca** y decide.
2. **Gestiona el condominio** — unidades (departamentos), residentes, vehículos
   autorizados y una **bitácora** de todos los accesos con foto.
3. **Abre la barrera** — automáticamente para placas autorizadas, por **QR** para
   visitantes, o manualmente desde el panel.

> ⚠️ **Importante:** esto **no** corre en GitHub Pages. Necesita un servidor
> (un mini‑PC / NUC / Raspberry Pi) conectado a la **misma red LAN** que la
> cámara y la barrera. Se entrega listo para Docker.

---

## Arquitectura

```
   Cámara Dahua ITC413 (ANPR a bordo)
        │  1) lee placa  ──POST evento HTTP──►  ┌─────────────────────┐
        │                                       │  Backend FastAPI     │
        │  ◄── 3) abrir barrera (CGI relé) ──── │  + SQLite            │
        ▼                                       │                      │
   Barrera / talanquera                         │  · lista blanca      │
                                                │  · bitácora + fotos  │
   Visitante  ──escanea QR──► /api/qr/validate ►│  · pases QR          │
                                                └──────────┬───────────┘
                                                           │  panel web
                                                     Administración / Portería
```

- **Backend:** FastAPI + SQLAlchemy + SQLite (`app/`).
- **Panel:** SPA en un solo archivo (`web/index.html`), estética terminal.
- **Control de barrera:** adaptadores `dahua` (CGI de la cámara), `http`
  (relé de red genérico) o `dummy` (pruebas) — ver `app/gate.py`.

---

## Puesta en marcha

```bash
cd condominio-anpr
cp .env.example .env          # edita SECRET_KEY, ADMIN_PASSWORD, cámara…

# opción A — Docker (recomendado)
docker compose up --build

# opción B — local
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abre **http://localhost:8000** e ingresa con el usuario/clave de `.env`.

---

## Configurar la cámara Dahua para que envíe las placas

En la interfaz web de la cámara ITC413:

1. **Configuración ▸ Red ▸ HTTP / Plataforma / "Push"** (el nombre varía por
   firmware; busca *HTTP Post*, *ANPR Upload* o *Plataforma de acceso*).
2. Apunta el destino a tu servidor:
   ```
   http://<IP-del-servidor>:8000/api/anpr/event
   ```
   Si defines `ANPR_INGEST_TOKEN` en `.env`, agrega `?token=EL_TOKEN` a la URL.
3. Activa el envío de **evento de matrícula (Traffic Snapshot / ANPR)** con
   imagen. El endpoint es tolerante al formato (JSON, form-data o multipart) y
   guarda la foto que llegue.

> ¿No sabes el formato exacto que envía tu firmware? Haz una lectura de prueba y
> revisa los logs del contenedor: el sistema imprime `Evento ANPR: placa=… campos=[…]`
> para que veas en qué clave viene la placa y ajustar si hiciera falta.

### Apertura de barrera (Dahua)

Con `GATE_MODE=dahua`, el sistema abre el relé a bordo con:

```
GET /cgi-bin/trafficSnap.cgi?action=openStrobe&channel=1&info.openType=Normal
```

(usa autenticación Digest con `DAHUA_USER` / `DAHUA_PASSWORD`). El relé de la
cámara debe estar cableado a la entrada de la talanquera. Si usas otro relé de
red, pon `GATE_MODE=http` y `GATE_HTTP_URL`.

---

## Flujo de visitantes (QR)

1. En el panel ▸ **Visitas QR** generas un pase (nombre, placa opcional, horas de
   vigencia y número de usos). Se crea un QR.
2. Compartes la imagen del QR (o el token) con el visitante.
3. En la barrera, el guardia lo escanea con el celular o un lector de red que
   haga `POST /api/qr/validate` con `{"token": "..."}`. El sistema valida
   vigencia y usos, **abre la barrera** y lo registra en la bitácora.

---

## API principal

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/anpr/event` | Recibe la lectura de placa de la cámara (whitelist + abre) |
| POST | `/api/qr/validate` | Valida un QR de visita y abre la barrera |
| POST | `/api/qr/visitors` | Crea un pase de visita |
| GET  | `/api/qr/visitors/{id}/image` | PNG del QR |
| POST | `/api/gate/open` | Apertura manual (portería) |
| CRUD | `/api/units` · `/api/residents` · `/api/vehicles` | Gestión |
| GET  | `/api/logs` · `/api/stats` | Bitácora e indicadores |
| POST | `/api/auth/login` · `/logout` · `GET /me` | Sesión |

---

## Seguridad (léelo antes de producción)

- Cambia `SECRET_KEY` y `ADMIN_PASSWORD`. El admin se crea solo al primer arranque.
- Mantén el servidor y la cámara en una **red aislada**; no expongas
  `/api/anpr/event` ni `/api/qr/validate` a internet sin protección adicional
  (VPN, token, o proxy con TLS). El endpoint ANPR admite un `ANPR_INGEST_TOKEN`.
- SQLite sirve para un condominio; para varios sitios migra a PostgreSQL
  cambiando `DATABASE_URL`.

---

## Estado y siguientes pasos

Incluido (MVP funcional): ingesta ANPR + lista blanca, apertura por QR de visita,
CRUD de condominio, bitácora con fotos, control de barrera Dahua/HTTP, panel web y
Docker.

Ideas para extender: notificaciones (WhatsApp/Telegram al residente cuando llega
su visita), reportes por unidad, roles más finos, reconocimiento propio por si la
cámara no trae ANPR, e integración con el NVR **DHI-NVR5208-EI** del presupuesto
para archivar video de cada evento.
