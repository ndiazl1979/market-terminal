"""Control de la barrera / talanquera.

Adaptadores:
  - dahua : abre el relé a bordo de la cámara Dahua ITC vía CGI (Digest auth).
  - http  : GET a una URL genérica (otros relés de red / Shelly / Sonoff, etc.).
  - dummy : no hace nada físico, solo devuelve OK (para desarrollo).

La cámara Dahua ITC413 expone la apertura de barrera en:
    GET /cgi-bin/trafficSnap.cgi?action=openStrobe&channel=<n>&info.openType=Normal
También se deja un respaldo por salida de alarma:
    GET /cgi-bin/alarm.cgi?action=setAlarm&type=all&state=on
"""
import logging

import httpx

from .config import settings

log = logging.getLogger("gate")


def _dahua_open() -> tuple[bool, str]:
    base = f"http://{settings.dahua_host}/cgi-bin"
    auth = httpx.DigestAuth(settings.dahua_user, settings.dahua_password)
    ch = settings.dahua_channel
    urls = [
        f"{base}/trafficSnap.cgi?action=openStrobe&channel={ch}&info.openType=Normal",
        # respaldo: pulso en la salida de alarma
        f"{base}/alarm.cgi?action=setAlarm&type=all&state=on",
    ]
    last = ""
    for url in urls:
        try:
            r = httpx.get(url, auth=auth, timeout=5.0)
            if r.status_code == 200 and "Error" not in r.text:
                return True, f"dahua OK ({url.split('?')[0]})"
            last = f"HTTP {r.status_code}: {r.text[:120]}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
    return False, f"dahua falló: {last}"


def _http_open() -> tuple[bool, str]:
    if not settings.gate_http_url:
        return False, "GATE_HTTP_URL no configurada"
    try:
        r = httpx.get(settings.gate_http_url, timeout=5.0)
        return (r.status_code < 400), f"http {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def open_gate() -> tuple[bool, str]:
    """Abre la barrera según GATE_MODE. Devuelve (éxito, detalle)."""
    mode = settings.gate_mode.lower()
    if mode == "dahua":
        ok, detail = _dahua_open()
    elif mode == "http":
        ok, detail = _http_open()
    else:
        ok, detail = True, "dummy (sin hardware)"
    log.info("open_gate mode=%s ok=%s detail=%s", mode, ok, detail)
    return ok, detail
