#!/usr/bin/env python3
"""
fetch_news.py — Noticias que mueven la bolsa → news.json

Se ejecuta del lado servidor (GitHub Actions): SIN API keys ni CORS, igual que el
resto del proyecto. Toda la data sale de feeds RSS públicos de Google News
(geo/idioma configurable, incl. Ecuador) — no se necesita ninguna clave.

Para cada noticia internacional se detecta el/los TICKER afectado(s) por palabras
clave y se estima una variación aproximada a 24 h:

    variación ≈ dirección · volatilidad_típica_del_ticker · (0.5 + |sentimiento|) · recencia

donde:
  · sentimiento ∈ [−1, 1] sale de un léxico ES/EN (palabras alcistas vs bajistas),
  · dirección = signo(sentimiento) · polaridad (la polaridad invierte la relación,
    p. ej. en una guerra: defensa ↑, petróleo ↑, bolsa general ↓),
  · recencia pondera más las noticias recientes.

Es una ESTIMACIÓN heurística (sentimiento × volatilidad), NO un pronóstico. Se
etiqueta como tal en la interfaz. La pestaña Ecuador añade etiquetas macro
(petróleo WTI, riesgo país, dólar) en vez de tickers de EE. UU.
"""

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) market-terminal/1.0"
GNEWS = "https://news.google.com/rss/search"

# ---------------------------------------------------------------------------
# Universo de tickers: símbolo -> (nombre, volatilidad diaria típica %)
# ---------------------------------------------------------------------------
TICKERS = {
    "AAPL": ("Apple", 1.6), "MSFT": ("Microsoft", 1.6), "NVDA": ("NVIDIA", 3.6),
    "AMZN": ("Amazon", 2.0), "GOOGL": ("Alphabet", 1.9), "META": ("Meta", 2.4),
    "TSLA": ("Tesla", 3.8), "TSM": ("TSMC", 2.4), "AMD": ("AMD", 3.4),
    "AVGO": ("Broadcom", 2.6), "MU": ("Micron", 3.2), "ASML": ("ASML", 2.4),
    "INTC": ("Intel", 2.8), "ARM": ("Arm Holdings", 4.0), "SMH": ("ETF Semiconductores", 2.0),
    "ASTS": ("AST SpaceMobile", 7.5), "GSAT": ("Globalstar", 6.0), "IRDM": ("Iridium", 2.6),
    "RKLB": ("Rocket Lab", 6.0), "LUNR": ("Intuitive Machines", 8.0),
    "LMT": ("Lockheed Martin", 1.4), "RTX": ("RTX (Raytheon)", 1.6),
    "NOC": ("Northrop Grumman", 1.5), "GD": ("General Dynamics", 1.4),
    "BA": ("Boeing", 2.2), "ITA": ("ETF Defensa/Aeroespacial", 1.6),
    "XOM": ("Exxon Mobil", 1.7), "CVX": ("Chevron", 1.6), "USO": ("ETF Petróleo", 2.2),
    "WTI": ("Petróleo WTI", 2.4), "SLB": ("SLB (Schlumberger)", 2.4),
    "SPY": ("S&P 500", 1.0), "QQQ": ("Nasdaq 100", 1.3), "TLT": ("Bonos 20Y", 1.2),
    "GLD": ("Oro", 1.0), "VIX": ("Índice de volatilidad", 6.0),
}

# Reglas: (palabras clave, símbolo, polaridad, broad)
#   polaridad +1 = afecta directo; −1 = relación inversa (guerra → defensa ↑, bolsa ↓).
#   broad=False = mención específica de la empresa/instrumento (siempre cuenta).
#   broad=True  = concepto sectorial (IA, chips, petróleo, guerra…); solo cuenta si la
#                 noticia tiene además contexto de mercado (evita ruido tipo lifestyle).
# El match es por LÍMITE de palabra, así "intel" no dispara en "inteligencia".
WAR_KW = ["guerra", "war", "conflicto", "conflict", "invasión", "invasion", "ataque",
          "attack", "sanciones", "sanctions", "geopolítico", "geopolitico", "geopolitical",
          "ukraine", "ucrania", "russia", "rusia", "israel", "irán", "iran", "gaza",
          "taiwan", "taiwán", "misiles", "bombardeo"]
RULES = [
    (["apple", "iphone", "tim cook", "ipad", "macbook"], "AAPL", 1, False),
    (["microsoft", "azure", "copilot", "xbox"], "MSFT", 1, False),
    (["nvidia", "jensen huang", "geforce", "blackwell"], "NVDA", 1, False),
    (["amazon", "aws", "bezos"], "AMZN", 1, False),
    (["google", "alphabet", "gemini", "deepmind", "youtube"], "GOOGL", 1, False),
    (["meta", "facebook", "instagram", "zuckerberg", "whatsapp"], "META", 1, False),
    (["tesla", "elon musk", "cybertruck", "robotaxi"], "TSLA", 1, False),
    (["tsmc", "taiwan semiconductor"], "TSM", 1, False),
    (["amd", "advanced micro"], "AMD", 1, False),
    (["broadcom"], "AVGO", 1, False),
    (["micron"], "MU", 1, False),
    (["asml"], "ASML", 1, False),
    (["intel"], "INTC", 1, False),
    (["arm holdings"], "ARM", 1, False),
    (["semiconductor", "semiconductores", "chip", "chips", "inteligencia artificial",
      "artificial intelligence", "data center", "centro de datos"], "SMH", 1, True),
    (["ast spacemobile", "spacemobile", "asts"], "ASTS", 1, False),
    (["globalstar"], "GSAT", 1, False),
    (["iridium"], "IRDM", 1, False),
    (["rocket lab", "rocketlab"], "RKLB", 1, False),
    (["intuitive machines"], "LUNR", 1, False),
    (["satélite", "satelite", "satellite", "satélites", "satelital",
      "espacial", "órbita", "orbita"], "ASTS", 1, True),
    (["lockheed"], "LMT", 1, False),
    (["raytheon", "rtx"], "RTX", 1, False),
    (["northrop"], "NOC", 1, False),
    (["general dynamics"], "GD", 1, False),
    (["boeing"], "BA", 1, False),
    (["defensa", "defense", "armamento", "armament", "misil", "missile",
      "weapons", "armas", "rearme", "gasto militar", "military spending"], "ITA", 1, True),
    (["exxon"], "XOM", 1, False),
    (["chevron"], "CVX", 1, False),
    (["schlumberger"], "SLB", 1, False),
    (["petróleo", "petroleo", "crude", "crudo", "brent", "wti", "opep", "opec",
      "barril", "barriles"], "WTI", 1, True),
    (["reserva federal", "federal reserve", "jerome powell", "tasa de interés",
      "interest rate", "inflación", "inflation", "jobs report"], "SPY", 1, True),
    (["arancel", "aranceles", "tariff", "tariffs", "trade war", "guerra comercial"], "SPY", 1, True),
    (["nasdaq", "wall street", "s&p 500", "bolsa de nueva york"], "QQQ", 1, True),
    # relación inversa: una guerra golpea la bolsa general pero impulsa defensa/petróleo
    (WAR_KW, "ITA", -1, True),
    (WAR_KW, "WTI", -1, True),
    (WAR_KW, "SPY", 1, True),
]

# Palabras que confirman que la noticia es de mercado (para matches sectoriales).
MARKET_CTX = ["acción", "acciones", "bolsa", "stock", "stocks", "shares", "wall street",
              "nasdaq", "mercado", "mercados", "cotiza", "cotización", "inversor",
              "inversionista", "etf", "índice", "indice", "s&p", "dow", "ipo", "earnings",
              "ganancias", "resultados", "analista", "billion", "millones", "millardo",
              "capitalización", "valuación", "$", "dólares", "rally", "sube", "cae"]

POS = {
    "rises", "rise", "surge", "surges", "jump", "jumps", "gain", "gains", "beat", "beats",
    "record", "soar", "soars", "rally", "rallies", "upgrade", "strong", "growth", "profit",
    "wins", "win", "deal", "approve", "approved", "breakthrough", "expand", "optimism", "boom",
    "climb", "climbs", "high", "highs", "bullish", "outperform", "raises", "boost", "rebound",
    "recover", "recovers",
    "sube", "suben", "subió", "subio", "subir", "gana", "ganan", "ganó", "gano", "récord",
    "record", "acuerdo", "crece", "crecen", "creció", "fuerte", "alza", "alcista", "repunta",
    "repuntó", "supera", "superó", "supero", "aprueba", "aprobó", "impulsa", "impulsó",
    "optimismo", "máximo", "maximo", "máximos", "ganancias", "avanza", "avanzan", "dispara",
    "disparó", "rebota", "rebote", "recupera", "recuperó", "despega",
}
NEG = {
    "falls", "fall", "drop", "drops", "plunge", "plunges", "slump", "miss", "misses", "cut",
    "cuts", "layoff", "layoffs", "ban", "bans", "sanction", "sanctions", "war", "attack",
    "crash", "weak", "loss", "losses", "decline", "downgrade", "probe", "lawsuit", "recall",
    "strike", "fear", "fears", "recession", "slowdown", "warning", "warns", "tumble", "sink",
    "sinks", "bearish", "selloff", "default", "crisis", "tariff", "tariffs", "slumps",
    "cae", "caen", "cayó", "cayo", "cayeron", "baja", "bajan", "bajó", "bajo", "pierde",
    "pierden", "perdió", "perdio", "débil", "debil", "caída", "caida", "despidos", "despide",
    "sanción", "sancion", "sanciones", "guerra", "ataque", "conflicto", "recesión", "recesion",
    "multa", "demanda", "prohíbe", "prohibe", "desplome", "desploma", "desplomó", "hunde",
    "hunden", "hundió", "derrumbe", "derrumba", "temor", "temores", "cede", "ceden", "cedió",
    "retrocede", "retroceden", "desinfla", "tensión", "tension", "amenaza",
}

# Categorías internacionales: (key, etiqueta, query Google News)
CATEGORIES = [
    ("tech", "Big 7 / Tecnología",
     "Apple OR Microsoft OR Nvidia OR Amazon OR Google OR Meta OR Tesla acciones"),
    ("semis", "Semiconductores / IA",
     "semiconductores OR chips OR inteligencia artificial OR Nvidia OR TSMC"),
    ("space", "Satelital / Espacio",
     "satélites OR SpaceX OR Starlink OR espacio empresa bolsa"),
    ("defense", "Defensa / Armamento",
     "industria de defensa OR armamento OR Lockheed OR Raytheon OR gasto militar"),
    ("oil", "Petróleo / Energía",
     "precio del petróleo OR OPEP OR crudo Brent WTI mercado"),
    ("war", "Guerra / Geopolítica",
     "guerra OR conflicto geopolítico mercados bolsa"),
    ("macro", "Macro / Bolsa",
     "Reserva Federal OR inflación OR aranceles OR Wall Street bolsa"),
]

# Ecuador: queries en español con geo EC
EC_QUERIES = [
    "Bolsa de Valores Ecuador OR BVG OR BVQ emisores",
    "economía Ecuador mercado",
    "riesgo país Ecuador EMBI",
    "petróleo Ecuador exportaciones crudo",
    "Ecuador inversión deuda bonos",
]


# ---------------------------------------------------------------------------
def fetch_rss(query, hl="es-419", gl="US", ceid="US:es-419"):
    params = urllib.parse.urlencode({"q": query, "hl": hl, "gl": gl, "ceid": ceid})
    url = f"{GNEWS}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    root = ET.fromstring(raw)
    items = []
    for it in root.findall("./channel/item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        src_el = it.find("source")
        source = (src_el.text if src_el is not None else "").strip()
        # Google News pone "Titular - Fuente" en title; separa la fuente
        clean = title
        if not source and " - " in title:
            clean, source = title.rsplit(" - ", 1)
        elif source and title.endswith(" - " + source):
            clean = title[: -(len(source) + 3)]
        ts = None
        if pub:
            try:
                ts = int(parsedate_to_datetime(pub).timestamp() * 1000)
            except Exception:  # noqa: BLE001
                ts = None
        items.append({"title": html.unescape(clean.strip()), "source": source or "—",
                      "link": link, "ts": ts})
    return items


def sentiment(text):
    words = re.findall(r"[a-záéíóúñ&]+", text.lower())
    pos = sum(1 for w in words if w in POS)
    neg = sum(1 for w in words if w in NEG)
    if pos == 0 and neg == 0:
        return 0.0
    return max(-1.0, min(1.0, (pos - neg) / (pos + neg + 1)))


def recency_weight(ts, now_ms):
    if not ts:
        return 0.7
    age_h = max(0.0, (now_ms - ts) / 3_600_000)
    if age_h <= 6:
        return 1.0
    if age_h <= 24:
        return 0.85
    if age_h <= 48:
        return 0.7
    return 0.55


def kw_hit(low, k):
    """Match por límite de palabra (así 'intel' no dispara dentro de 'inteligencia')."""
    return re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", low) is not None


def has_market_ctx(low):
    return any(c in low for c in MARKET_CTX)


def match_tickers(title):
    low = title.lower()
    ctx = has_market_ctx(low)
    found = {}
    for keys, sym, pol, broad in RULES:
        if any(kw_hit(low, k) for k in keys):
            if broad and not ctx:
                continue  # match sectorial sin contexto de mercado → se ignora
            found.setdefault(sym, pol)  # conserva la primera polaridad por símbolo
    return found  # {sym: polaridad}


def expected_move(sym, pol, sent, rec):
    name, vol = TICKERS.get(sym, (sym, 2.0))
    direction = 0
    if sent > 0.05:
        direction = 1
    elif sent < -0.05:
        direction = -1
    else:
        direction = 1  # leve sesgo al alza por defecto en noticias neutras
    direction *= pol
    mag = vol * (0.5 + abs(sent)) * rec
    mag = max(0.2, min(8.0, mag))
    pct = round(direction * mag, 1)
    return {"sym": sym, "name": name, "pct": pct, "dir": 1 if pct > 0 else -1 if pct < 0 else 0}


def build_item(raw, now_ms, require_ticker=True):
    sent = sentiment(raw["title"])
    rec = recency_weight(raw["ts"], now_ms)
    tickers = []
    for sym, pol in match_tickers(raw["title"]).items():
        tickers.append(expected_move(sym, pol, sent, rec))
    tickers.sort(key=lambda t: -abs(t["pct"]))
    if require_ticker and not tickers:
        return None
    return {
        "title": raw["title"], "source": raw["source"], "link": raw["link"],
        "ts": raw["ts"], "sentiment": round(sent, 2), "tickers": tickers[:4],
    }


def ecuador_tags(title, sent, rec):
    low = title.lower()
    tags = []
    if any(k in low for k in ["petróleo", "petroleo", "crudo", "barril", "oil", "wti", "brent"]):
        tags.append(expected_move("WTI", 1, sent, rec))
    if any(k in low for k in ["riesgo país", "riesgo pais", "embi", "bonos", "deuda", "default"]):
        d = -1 if sent < 0 else 1
        tags.append({"sym": "RIESGO PAÍS", "name": "Riesgo país (EMBI)", "pct": None, "dir": -d})
    if any(k in low for k in ["dólar", "dolar", "inflación", "inflacion", "tasa", "fmi", "imf"]):
        tags.append({"sym": "USD/MACRO", "name": "Macro / dólar", "pct": None,
                     "dir": 1 if sent >= 0 else -1})
    if any(k in low for k in ["bolsa de valores", "bvg", "bvq", "emisor", "acciones", "renta fija"]):
        tags.append({"sym": "BVG/BVQ", "name": "Bolsa de Valores", "pct": None,
                     "dir": 1 if sent >= 0 else -1})
    return tags


def dedup(items):
    seen, out = set(), []
    for it in items:
        key = re.sub(r"[^a-z0-9]", "", it["title"].lower())[:60]
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


# ---------------------------------------------------------------------------
def main():
    now_ms = int(time.time() * 1000)
    categories = []
    all_intl = []

    for key, label, query in CATEGORIES:
        try:
            raws = fetch_rss(query, hl="es-419", gl="US", ceid="US:es-419")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] cat {key}: {e}", file=sys.stderr)
            raws = []
        items = []
        for raw in raws:
            it = build_item(raw, now_ms, require_ticker=True)
            if it:
                it["category"] = key
                items.append(it)
        items = dedup(items)
        items.sort(key=lambda x: -(x["ts"] or 0))
        items = items[:10]
        all_intl.extend(items)
        categories.append({"key": key, "label": label, "items": items})
        print(f"[ok] {key}: {len(items)} noticias")
        time.sleep(0.2)

    # Tablero de tickers: variación neta estimada a 24 h agregando todas las noticias
    # (dedup global: el mismo artículo puede salir en varias categorías)
    board = {}
    for it in dedup(all_intl):
        for t in it["tickers"]:
            b = board.setdefault(t["sym"], {"sym": t["sym"], "name": t["name"], "net": 0.0, "n": 0})
            b["net"] += t["pct"]
            b["n"] += 1
    ticker_board = []
    for b in board.values():
        net = max(-12.0, min(12.0, b["net"]))
        ticker_board.append({"sym": b["sym"], "name": b["name"],
                             "net": round(net, 1), "n": b["n"]})
    ticker_board.sort(key=lambda b: -abs(b["net"]))
    ticker_board = ticker_board[:14]

    # Ecuador
    ec_items = []
    for query in EC_QUERIES:
        try:
            raws = fetch_rss(query, hl="es-419", gl="EC", ceid="EC:es-419")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] ecuador: {e}", file=sys.stderr)
            raws = []
        for raw in raws:
            sent = sentiment(raw["title"])
            rec = recency_weight(raw["ts"], now_ms)
            ec_items.append({
                "title": raw["title"], "source": raw["source"], "link": raw["link"],
                "ts": raw["ts"], "sentiment": round(sent, 2),
                "tags": ecuador_tags(raw["title"], sent, rec),
            })
        time.sleep(0.2)
    ec_items = dedup(ec_items)
    ec_items.sort(key=lambda x: -(x["ts"] or 0))
    ec_items = ec_items[:16]
    print(f"[ok] ecuador: {len(ec_items)} noticias")

    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
        "tickerBoard": ticker_board,
        "ecuador": ec_items,
    }
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    total = sum(len(c["items"]) for c in categories) + len(ec_items)
    print(f"[done] {total} noticias -> news.json")


if __name__ == "__main__":
    main()
