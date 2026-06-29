#!/usr/bin/env python3
"""
fetch_worldcup.py — Análisis quant del Mundial FIFA 2026 → worldcup.json

Se ejecuta del lado servidor (GitHub Actions): SIN API keys y SIN CORS, igual que
fetch_data.py. Toda la data sale de la API pública (no documentada) de ESPN:

  - Standings : tabla de los 12 grupos (PJ, G/E/P, GF/GC, DG, Pts, rank).
  - Scoreboard: calendario/resultados de partidos (estados pre/in/post, marcador).
  - Summary   : cuotas de mercado (DraftKings vía ESPN) para EV.

MODELO QUANT
------------
Fuerza ofensiva/defensiva de cada selección = mezcla bayesiana de:
  (a) prior Elo (ratings aproximados pre-torneo), y
  (b) rendimiento real en el torneo (GF/GC por partido de la tabla),
ponderada por nº de partidos jugados (shrinkage hacia el prior cuando hay pocos).

Con eso se estiman goles esperados (λ) por equipo en cada partido y se construye
una matriz de marcadores Poisson con corrección Dixon-Coles para marcadores bajos.
De la matriz salen TODOS los mercados:
  · 1X2 (gana local / empate / gana visita)        · Doble oportunidad
  · Total de goles Over/Under (1.5 / 2.5 / 3.5)     · Ambos anotan (BTTS)
  · Hándicap asiático sugerido (línea + prob.)      · Marcador más probable
  · Tiros a puerta esperados (estimados desde λ)    · Goles esperados

Si ESPN trae cuotas, se quita el margen (de-vig) y se calcula el VALOR (EV) de cada
apuesta: EV% = prob_modelo · cuota_decimal − 1. La "predicción más estable y de buen
EV" maximiza un score = EV · prob_modelo (premia ventaja real + baja varianza).
"""

import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) market-terminal/1.0"
BASE = "https://site.api.espn.com/apis"
LEAGUE = "soccer/fifa.world"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

# Ventana de partidos a predecir (desde hoy). El Mundial 2026 va ~jun 11 – jul 19.
PREDICT_DAYS_AHEAD = 30        # cubre desde 16avos hasta la final
PREDICT_DAYS_BACK = 2          # para mostrar también resultados recientes

# Etiquetas de etapa (slug de ESPN -> nombre mostrado) para el cuadro de eliminatorias.
STAGE_LABELS = {
    "round-of-32": "Ronda de 32",
    "round-of-16": "Octavos",
    "quarterfinals": "Cuartos",
    "semifinals": "Semifinal",
    "3rd-place-match": "3er puesto",
    "final": "Final",
}
MAX_ODDS_FETCH = 22            # tope de summaries (cuotas) por corrida

# Parámetros del modelo
PRIOR_GAMES = 5.0             # fuerza del shrinkage hacia el prior Elo (estabilidad temprana)
MARKET_BLEND = 0.5            # peso del modelo vs mercado al calcular EV (anti-sobreconfianza)
BASE_GOALS = 1.32             # goles esperados por equipo vs rival promedio
ELO_BETA = 0.18               # sensibilidad goles ↔ Elo (por 100 pts de Elo)
DC_RHO = 0.06                 # corrección Dixon-Coles (marcadores bajos)
SOT_CONV = 0.32               # goles por tiro a puerta (conversión típica)
SOT_SHARE = 0.42              # fracción de tiros que van a puerta
MAX_GOALS = 8                 # tope de la matriz de marcadores

# Prior Elo aproximado por abreviatura ESPN. Las desconocidas usan BASE_ELO; el
# rendimiento real del torneo corrige el rating vía shrinkage.
BASE_ELO = 1675
ELO = {
    "ARG": 2145, "FRA": 2100, "ESP": 2085, "ENG": 2055, "BRA": 2045, "POR": 2010,
    "NED": 1995, "BEL": 1965, "GER": 1965, "ITA": 1940, "URU": 1915, "CRO": 1900,
    "COL": 1880, "MAR": 1865, "SUI": 1820, "JPN": 1815, "USA": 1810, "DEN": 1810,
    "MEX": 1805, "SEN": 1805, "IRN": 1795, "AUT": 1795, "ECU": 1785, "KOR": 1775,
    "SRB": 1770, "UKR": 1765, "CAN": 1760, "POL": 1745, "AUS": 1730, "EGY": 1715,
    "WAL": 1755, "TUR": 1780, "NOR": 1790, "SWE": 1770, "SCO": 1740, "TUN": 1700,
    "NGA": 1740, "CIV": 1715, "ALG": 1730, "CMR": 1700, "GHA": 1690, "RSA": 1680,
    "QAT": 1665, "SAU": 1660, "IRQ": 1630, "JOR": 1600, "UZB": 1640, "PAN": 1660,
    "CRC": 1690, "PAR": 1720, "VEN": 1700, "PER": 1710, "CHI": 1735, "BOL": 1590,
    "HAI": 1560, "JAM": 1640, "HON": 1620, "NZL": 1560, "BIH": 1700, "CZE": 1760,
    "SVN": 1700, "SVK": 1690, "ROU": 1700, "HUN": 1720, "GRE": 1715, "NIR": 1650,
    "CPV": 1610, "ANG": 1560, "ZAM": 1580, "MTN": 1500, "BEN": 1560, "GAB": 1570,
    "UAE": 1630, "OMA": 1600, "BHR": 1530, "PLE": 1500, "SYR": 1560, "LBN": 1480,
    "IDN": 1500, "CUW": 1560, "SUR": 1520, "GUA": 1560, "SLV": 1560, "TRI": 1560,
    "NCL": 1380, "COD": 1640, "MLI": 1640, "BFA": 1640, "UGA": 1560, "TAN": 1500,
}


# ---------------------------------------------------------------------------
# Utilidades de red
# ---------------------------------------------------------------------------
def api_get(path, params=None):
    r = SESSION.get(f"{BASE}/{path}", params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def yyyymmdd(dt):
    return dt.strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Extracción de equipos / tablas
# ---------------------------------------------------------------------------
def team_brief(team):
    """Normaliza el objeto 'team' de ESPN a campos mínimos."""
    logos = team.get("logos") or []
    logo = logos[0].get("href") if logos else team.get("logo")
    return {
        "abbr": team.get("abbreviation") or team.get("shortDisplayName") or "?",
        "name": team.get("displayName") or team.get("name") or team.get("abbreviation") or "?",
        "logo": logo,
        "id": team.get("id"),
    }


def stat(entry_stats, name, default=None):
    for s in entry_stats:
        if s.get("name") == name:
            v = s.get("value")
            return v if v is not None else default
    return default


def fetch_standings():
    """Devuelve (grupos, índice equipo→datos). Cada grupo: nombre + filas ordenadas."""
    data = api_get(f"v2/sports/{LEAGUE}/standings")
    groups = []
    index = {}  # abbr -> {atk/def insumos + grupo + rank}
    for child in data.get("children", []):
        gname = child.get("name", "Grupo")
        entries = (child.get("standings") or {}).get("entries", [])
        rows = []
        for e in entries:
            t = team_brief(e.get("team", {}))
            st = e.get("stats", [])
            gp = int(stat(st, "gamesPlayed", 0) or 0)
            gf = int(stat(st, "pointsFor", 0) or 0)
            ga = int(stat(st, "pointsAgainst", 0) or 0)
            row = {
                "abbr": t["abbr"], "name": t["name"], "logo": t["logo"],
                "pj": gp,
                "w": int(stat(st, "wins", 0) or 0),
                "d": int(stat(st, "ties", 0) or 0),
                "l": int(stat(st, "losses", 0) or 0),
                "gf": gf, "ga": ga,
                "gd": int(stat(st, "pointDifferential", gf - ga) or 0),
                "pts": int(stat(st, "points", 0) or 0),
                "rank": int(stat(st, "rank", 0) or 0),
                "group": gname,
            }
            rows.append(row)
            index[t["abbr"]] = row
        # ordena por rank si existe, si no por (pts, dg, gf)
        if all(r["rank"] for r in rows):
            rows.sort(key=lambda r: r["rank"])
        else:
            rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"]))
        for i, r in enumerate(rows):
            r["pos"] = i + 1
        groups.append({"name": gname, "teams": rows})
    return groups, index


def compute_strengths(index):
    """atk/def esperados (goles vs rival promedio) por equipo, prior Elo + datos."""
    strengths = {}
    for abbr, row in index.items():
        gp = row["pj"]
        k = gp / (gp + PRIOR_GAMES) if gp > 0 else 0.0
        elo = ELO.get(abbr, BASE_ELO)
        elo_off = BASE_GOALS * math.exp(ELO_BETA * (elo - BASE_ELO) / 100.0)
        elo_def = BASE_GOALS * math.exp(-ELO_BETA * (elo - BASE_ELO) / 100.0)
        atk_data = (row["gf"] / gp) if gp > 0 else BASE_GOALS
        def_data = (row["ga"] / gp) if gp > 0 else BASE_GOALS
        atk = k * atk_data + (1 - k) * elo_off
        deff = k * def_data + (1 - k) * elo_def
        strengths[abbr] = {"atk": max(0.25, atk), "def": max(0.25, deff), "elo": elo}
    return strengths


def default_strength(abbr):
    elo = ELO.get(abbr, BASE_ELO)
    return {
        "atk": BASE_GOALS * math.exp(ELO_BETA * (elo - BASE_ELO) / 100.0),
        "def": BASE_GOALS * math.exp(-ELO_BETA * (elo - BASE_ELO) / 100.0),
        "elo": elo,
    }


# ---------------------------------------------------------------------------
# Modelo Poisson / Dixon-Coles
# ---------------------------------------------------------------------------
def pois_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def dc_tau(x, y, lam, mu, rho):
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def score_matrix(lam, mu):
    m = [[0.0] * (MAX_GOALS + 1) for _ in range(MAX_GOALS + 1)]
    total = 0.0
    for x in range(MAX_GOALS + 1):
        px = pois_pmf(x, lam)
        for y in range(MAX_GOALS + 1):
            p = px * pois_pmf(y, mu) * dc_tau(x, y, lam, mu, DC_RHO)
            m[x][y] = p
            total += p
    if total > 0:
        for x in range(MAX_GOALS + 1):
            for y in range(MAX_GOALS + 1):
                m[x][y] /= total
    return m


def market_probs(m):
    p_home = p_draw = p_away = 0.0
    p_over = {1.5: 0.0, 2.5: 0.0, 3.5: 0.0}
    p_btts = 0.0
    best_p, best_s = 0.0, (0, 0)
    scores = []
    for x in range(MAX_GOALS + 1):
        for y in range(MAX_GOALS + 1):
            p = m[x][y]
            if x > y:
                p_home += p
            elif x == y:
                p_draw += p
            else:
                p_away += p
            tot = x + y
            for line in p_over:
                if tot > line:
                    p_over[line] += p
            if x >= 1 and y >= 1:
                p_btts += p
            if p > best_p:
                best_p, best_s = p, (x, y)
            scores.append(((x, y), p))
    scores.sort(key=lambda s: -s[1])
    top = [{"score": f"{a}-{b}", "p": round(p * 100, 1)} for (a, b), p in scores[:3]]
    return {
        "pHome": round(p_home * 100, 1),
        "pDraw": round(p_draw * 100, 1),
        "pAway": round(p_away * 100, 1),
        "over": {str(k): round(v * 100, 1) for k, v in p_over.items()},
        "under": {str(k): round((1 - v) * 100, 1) for k, v in p_over.items()},
        "btts": round(p_btts * 100, 1),
        "topScores": top,
        "likely": f"{best_s[0]}-{best_s[1]}",
    }


def asian_handicap(m, lam, mu):
    """Sugerencia de hándicap asiático: línea ~ supremacía esperada y prob. de cubrir."""
    sup = lam - mu
    # redondea a la línea .25 más cercana, lado del favorito
    line = round(sup * 4) / 4.0
    if line == 0:
        line = 0.25 if sup >= 0 else -0.25
    fav_home = line > 0 if sup >= 0 else line >= 0
    # prob. de que el LOCAL cubra el hándicap 'line' (local recibe -line en goles)
    # Si line>0 el local da 'line' goles; cubre si (x - y) > line (cuartos → mitad push/half)

    def cover(handicap_home):
        win = push = 0.0
        for x in range(MAX_GOALS + 1):
            for y in range(MAX_GOALS + 1):
                margin = (x - y) + handicap_home
                if abs(margin) < 1e-9:
                    push += m[x][y]
                elif margin > 0:
                    win += m[x][y]
        denom = 1 - push
        return (win / denom) if denom > 0 else 0.0

    # El favorito da la línea (handicap negativo para el favorito).
    if sup >= 0:
        home_line = -abs(line)
        cov_home = cover(home_line)
        return {
            "fav": "home", "line": round(home_line, 2),
            "coverFav": round(cov_home * 100, 1),
            "lineAway": round(abs(line), 2),
            "coverDog": round((1 - cov_home) * 100, 1),
        }
    else:
        away_line = -abs(line)  # hándicap para la visita (favorita)
        cov_home = cover(abs(line))  # local recibe +line
        return {
            "fav": "away", "line": round(away_line, 2),
            "coverFav": round((1 - cov_home) * 100, 1),
            "lineAway": round(abs(line), 2),
            "coverDog": round(cov_home * 100, 1),
        }


def shots_on_target(lam, mu, sh_home, sh_away):
    """Tiros a puerta esperados a partir de los goles esperados (estimación)."""
    sot_h = lam / SOT_CONV
    sot_a = mu / SOT_CONV
    return {
        "home": round(sot_h, 1),
        "away": round(sot_a, 1),
        "total": round(sot_h + sot_a, 1),
        "shotsHome": round(sot_h / SOT_SHARE, 1),
        "shotsAway": round(sot_a / SOT_SHARE, 1),
    }


# ---------------------------------------------------------------------------
# Cuotas / EV
# ---------------------------------------------------------------------------
def american_to_decimal(ml):
    try:
        ml = float(ml)
    except (TypeError, ValueError):
        return None
    if ml == 0:
        return None
    return 1 + (ml / 100.0) if ml > 0 else 1 + (100.0 / abs(ml))


def devig(probs):
    s = sum(p for p in probs if p)
    if s <= 0:
        return probs
    return [(p / s if p else None) for p in probs]


def parse_odds(summary):
    """Extrae moneyline 1X2, spread (hándicap) y total O/U del primer proveedor."""
    odds = summary.get("odds") or []
    if not odds:
        return None
    o = odds[0]
    home = o.get("homeTeamOdds", {}) or {}
    away = o.get("awayTeamOdds", {}) or {}
    draw = o.get("drawOdds", {}) or {}
    out = {
        "source": (o.get("provider") or {}).get("name", "—"),
        "details": o.get("details"),
        "mlHome": home.get("moneyLine"),
        "mlAway": away.get("moneyLine"),
        "mlDraw": draw.get("moneyLine"),
        "spread": o.get("spread"),
        "spreadHome": home.get("spreadOdds"),
        "spreadAway": away.get("spreadOdds"),
        "total": o.get("overUnder"),
        "overOdds": o.get("overOdds"),
        "underOdds": o.get("underOdds"),
    }
    return out


def _bet(market, label, sel, p_model, implied, dec):
    """Construye una apuesta. EV usa prob. mezclada modelo+mercado (anti-sobreconfianza)."""
    p_blend = MARKET_BLEND * p_model + (1 - MARKET_BLEND) * (implied if implied else p_model)
    return {
        "market": market, "label": label, "sel": sel,
        "pModel": round(p_model * 100, 1),
        "pFair": round(p_blend * 100, 1),
        "implied": round((implied or 0) * 100, 1),
        "odds": round(dec, 2),
        "ev": round((p_blend * dec - 1) * 100, 1),
    }


def build_value(pred, odds):
    """Lista de apuestas con cuota, prob. modelo/justa, prob. implícita y EV%."""
    if not odds:
        return [], None

    bets = []

    # --- 1X2 con de-vig ---
    dh = american_to_decimal(odds.get("mlHome"))
    dd = american_to_decimal(odds.get("mlDraw"))
    da = american_to_decimal(odds.get("mlAway"))
    imp = devig([1 / dh if dh else None, 1 / dd if dd else None, 1 / da if da else None])
    for label, sel, p_model, dec, imp_p in [
        ("Gana local", "1", pred["pHome"] / 100.0, dh, imp[0]),
        ("Empate", "X", pred["pDraw"] / 100.0, dd, imp[1]),
        ("Gana visita", "2", pred["pAway"] / 100.0, da, imp[2]),
    ]:
        if dec:
            bets.append(_bet("1X2", label, sel, p_model, imp_p, dec))

    # --- Total Over/Under (línea del libro) ---
    if odds.get("total") is not None:
        line = float(odds["total"])
        key = next((c for c in ("1.5", "2.5", "3.5") if abs(float(c) - line) < 0.01), None)
        do = american_to_decimal(odds.get("overOdds"))
        du = american_to_decimal(odds.get("underOdds"))
        if key and do and du:
            po = pred["over"][key] / 100.0
            pu = pred["under"][key] / 100.0
            imp_ou = devig([1 / do, 1 / du])
            bets.append(_bet(f"Total {line}", f"Más de {line}", "O", po, imp_ou[0], do))
            bets.append(_bet(f"Total {line}", f"Menos de {line}", "U", pu, imp_ou[1], du))

    # --- Hándicap / spread del libro ---
    spread = odds.get("spread")
    if spread is not None:
        dsh = american_to_decimal(odds.get("spreadHome"))
        dsa = american_to_decimal(odds.get("spreadAway"))
        if dsh or dsa:
            ph_cov, pa_cov = cover_prob(pred["_matrix"], float(spread))
            imp_sp = devig([1 / dsh if dsh else None, 1 / dsa if dsa else None])
            if dsh:
                bets.append(_bet(f"Hándicap {spread:+g} L", f"Local {spread:+g}", "H", ph_cov, imp_sp[0], dsh))
            if dsa:
                bets.append(_bet(f"Hándicap {-spread:+g} V", f"Visita {-spread:+g}", "A", pa_cov, imp_sp[1], dsa))

    # recomendación: maximiza EV·prob (ventaja real + baja varianza), EV>0, prob≥42%
    rec = None
    cand = [b for b in bets if b["ev"] > 0 and b["pFair"] >= 42]
    pool = cand or [b for b in bets if b["ev"] > 0]
    if pool:
        rec = dict(max(pool, key=lambda b: b["ev"] * b["pFair"] / 100.0))
        rec["stability"] = round(rec["ev"] * rec["pFair"] / 100.0, 1)
    return bets, rec


def cover_prob(m, spread_home):
    """Prob. de cubrir spread (handicap aplicado al LOCAL = spread_home)."""
    win = push = 0.0
    for x in range(MAX_GOALS + 1):
        for y in range(MAX_GOALS + 1):
            margin = (x - y) + spread_home
            if abs(margin) < 1e-9:
                push += m[x][y]
            elif margin > 0:
                win += m[x][y]
    denom = 1 - push
    ph = (win / denom) if denom > 0 else 0.0
    return ph, 1 - ph


# ---------------------------------------------------------------------------
# Partidos
# ---------------------------------------------------------------------------
def fetch_scoreboard(start, end):
    events = []
    seen = set()
    # ESPN acepta rangos; troceamos en ventanas de 7 días por robustez.
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=6), end)
        try:
            data = api_get(f"site/v2/sports/{LEAGUE}/scoreboard",
                           {"dates": f"{yyyymmdd(cur)}-{yyyymmdd(chunk_end)}"})
            for e in data.get("events", []):
                if e["id"] not in seen:
                    seen.add(e["id"])
                    events.append(e)
        except Exception as ex:  # noqa: BLE001
            print(f"[warn] scoreboard {cur}: {ex}", file=sys.stderr)
        cur = chunk_end + timedelta(days=1)
        time.sleep(0.2)
    return events


def event_competitors(ev):
    comp = (ev.get("competitions") or [{}])[0]
    home = away = None
    for c in comp.get("competitors", []):
        brief = team_brief(c.get("team", {}))
        brief["score"] = c.get("score")
        if c.get("homeAway") == "home":
            home = brief
        else:
            away = brief
    return comp, home, away


def fetch_summary_odds(event_id):
    try:
        s = api_get(f"site/v2/sports/{LEAGUE}/summary", {"event": event_id})
        return parse_odds(s)
    except Exception as ex:  # noqa: BLE001
        print(f"[warn] summary {event_id}: {ex}", file=sys.stderr)
        return None


def predict_match(home, away, strengths):
    sh = strengths.get(home["abbr"], default_strength(home["abbr"]))
    sa = strengths.get(away["abbr"], default_strength(away["abbr"]))
    avg = BASE_GOALS
    lam = sh["atk"] * sa["def"] / avg     # goles esperados local
    mu = sa["atk"] * sh["def"] / avg      # goles esperados visita
    lam = max(0.15, min(5.0, lam))
    mu = max(0.15, min(5.0, mu))
    m = score_matrix(lam, mu)
    mk = market_probs(m)
    mk["_matrix"] = m
    mk["lamHome"] = round(lam, 2)
    mk["lamAway"] = round(mu, 2)
    mk["expTotal"] = round(lam + mu, 2)
    mk["ah"] = asian_handicap(m, lam, mu)
    mk["sot"] = shots_on_target(lam, mu, sh, sa)
    mk["eloHome"] = sh["elo"]
    mk["eloAway"] = sa["elo"]
    # confianza: qué tan marcado está el resultado
    mk["confidence"] = round(max(mk["pHome"], mk["pDraw"], mk["pAway"]), 1)
    return mk


# ---------------------------------------------------------------------------
# Tercer lugar
# ---------------------------------------------------------------------------
def third_place_race(groups):
    thirds = []
    for g in groups:
        if len(g["teams"]) >= 3:
            t = g["teams"][2]  # ya ordenado por posición
            thirds.append({
                "abbr": t["abbr"], "name": t["name"], "logo": t["logo"],
                "group": g["name"], "pj": t["pj"], "pts": t["pts"],
                "gd": t["gd"], "gf": t["gf"],
            })
    # criterios FIFA: Pts, DG, GF
    thirds.sort(key=lambda t: (-t["pts"], -t["gd"], -t["gf"]))
    for i, t in enumerate(thirds):
        t["pos"] = i + 1
        t["status"] = "Clasifica" if i < 8 else "Fuera"  # 8 mejores terceros (formato 48)
    return thirds


def annotate_group_status(groups):
    for g in groups:
        for t in g["teams"]:
            if t["pos"] <= 2:
                t["status"] = "Clasifica"
            elif t["pos"] == 3:
                t["status"] = "3er lugar"
            else:
                t["status"] = "Eliminado"


# ---------------------------------------------------------------------------
def main():
    now = datetime.now(timezone.utc)

    # 1) Tablas + fuerzas
    try:
        groups, index = fetch_standings()
    except Exception as ex:  # noqa: BLE001
        print(f"[err] standings: {ex}", file=sys.stderr)
        groups, index = [], {}
    strengths = compute_strengths(index)
    annotate_group_status(groups)
    thirds = third_place_race(groups)
    print(f"[ok] standings: {len(groups)} grupos, {len(index)} equipos")

    # 2) Partidos (ventana recientes + próximos)
    start = now - timedelta(days=PREDICT_DAYS_BACK)
    end = now + timedelta(days=PREDICT_DAYS_AHEAD)
    events = fetch_scoreboard(start, end)
    events.sort(key=lambda e: e.get("date", ""))
    print(f"[ok] {len(events)} partidos en ventana")

    matches = []
    odds_budget = MAX_ODDS_FETCH
    for ev in events:
        comp, home, away = event_competitors(ev)
        if not home or not away:
            continue
        status = ev.get("status", {}).get("type", {})
        state = status.get("state", "pre")  # pre / in / post
        slug = (ev.get("season") or {}).get("slug", "") or ""

        # Etiqueta de ronda: en eliminatorias usa la etapa real (ESPN season slug);
        # en fase de grupos, el grupo del equipo (o el headline si lo trae).
        if slug in STAGE_LABELS:
            note = STAGE_LABELS[slug]
        else:
            note = ""
            notes = comp.get("notes") or []
            if notes:
                note = notes[0].get("headline", "")
            if not note:
                note = (index.get(home["abbr"], {}) or {}).get("group", "") or "Mundial 2026"

        match = {
            "id": ev.get("id"),
            "date": ev.get("date"),
            "state": state,
            "stage": slug,
            "detail": status.get("shortDetail") or status.get("description"),
            "round": note,
            "home": home,
            "away": away,
        }

        if state != "post":
            pred = predict_match(home, away, strengths)
            odds = None
            if state == "pre" and odds_budget > 0:
                odds = fetch_summary_odds(ev["id"])
                odds_budget -= 1
                time.sleep(0.25)
            bets, rec = build_value(pred, odds) if odds else ([], None)
            pred.pop("_matrix", None)
            match["pred"] = pred
            match["odds"] = odds
            match["bets"] = bets
            match["rec"] = rec
        matches.append(match)

    # 3) Tablero de valor: mejores recomendaciones +EV ordenadas por estabilidad
    value_board = []
    for mt in matches:
        rec = mt.get("rec")
        if rec:
            value_board.append({
                "id": mt["id"], "date": mt["date"], "round": mt["round"],
                "home": mt["home"]["abbr"], "away": mt["away"]["abbr"],
                "homeName": mt["home"]["name"], "awayName": mt["away"]["name"],
                "market": rec["market"], "label": rec["label"],
                "odds": rec["odds"], "pModel": rec["pModel"], "pFair": rec.get("pFair"),
                "ev": rec["ev"], "stability": rec["stability"],
            })
    value_board.sort(key=lambda b: -b["stability"])

    out = {
        "updated": now.isoformat(),
        "tournament": "FIFA World Cup 2026",
        "groups": groups,
        "thirdPlace": thirds,
        "matches": matches,
        "valueBoard": value_board[:12],
    }
    with open("worldcup.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[done] {len(matches)} partidos, {len(value_board)} picks -> worldcup.json")


if __name__ == "__main__":
    main()
