# ◧ Market Terminal

Dashboard financiero en vivo con estética **Bloomberg Terminal**. Sigue 5 activos:

| Equities          | Crypto         |
|-------------------|----------------|
| AAPL · Apple      | BTC · Bitcoin  |
| TSLA · Tesla      | ETH · Ethereum |
| NVDA · NVIDIA     |                |

Muestra **precio en vivo**, **fundamentales** (market cap, P/E, EPS, dividend yield,
beta, rango 52 semanas, volumen), **señales técnicas** COMPRA / MANTENER / VENTA
(SMA50, SMA200, RSI-14, MACD) y un bloque de **análisis quant**: volatilidad
anualizada, Sharpe, Sortino, máximo drawdown, VaR-95%, retornos 1M/3M/1A,
MACD y posición Bollinger (%B) — todo sobre histórico de 1 año.

### Agregar tus propios activos

Desde la página, panel **➕ AGREGAR ACTIVO**: escribe cualquier moneda de CoinGecko
(cripto) o cualquier ticker de Yahoo Finance (equity). El activo se obtiene y calcula
**en vivo en el navegador** (mismos indicadores y quant), se guarda en tu navegador
(`localStorage`) y se refresca automáticamente. Los 5 activos del núcleo vienen del
backend; los tuyos se calculan en el cliente.

## Cómo funciona (sin API keys)

```
GitHub Actions (cron */5 min)
        │  corre del lado servidor → sin CORS, sin keys
        ▼
fetch_data.py ──► yfinance (acciones)  +  CoinGecko (cripto)
        │         calcula SMA/RSI + señal
        ▼
   data.json  (commiteado al repo)
        ▼
GitHub Pages sirve index.html ──► lee data.json (mismo origen) y se auto-refresca cada 60 s
```

No requiere ningún servicio de pago ni clave de API: todo se obtiene de fuentes
públicas desde el runner de GitHub Actions.

## ⚽ Mundial FIFA 2026

Pestaña **MUNDIAL 2026** con análisis cuantitativo de la Copa del Mundo, alimentada
por la API pública de ESPN (sin keys, igual que el resto):

- **Tabla actualizada** de los 12 grupos (PJ, G/E/P, GF:GC, DG, Pts) con clasificación
  en color: clasifica · 3er lugar · eliminado.
- **Carrera de terceros**: ranking de los 12 terceros por criterios FIFA (Pts, DG, GF);
  los **8 mejores clasifican** a la ronda de 32 (formato de 48 equipos).
- **Predicción quant por partido**: la fuerza ofensiva/defensiva de cada selección se
  estima mezclando un **prior Elo** con el **rendimiento real** del torneo (shrinkage
  bayesiano según partidos jugados). Con eso se calculan goles esperados (λ) y una
  **matriz de marcadores Poisson con corrección Dixon-Coles**, de la que salen:
  - **1X2** (gana local / empate / gana visita) y doble oportunidad
  - **Total** de goles Over/Under (1.5 / 2.5 / 3.5) y **ambos anotan** (BTTS)
  - **Hándicap asiático sugerido** (línea + probabilidad de cubrir)
  - **Marcador más probable** y goles esperados
  - **Tiros a puerta** esperados por equipo (estimados desde λ)
- **Valor / EV**: cuando ESPN trae cuotas (DraftKings) se les quita el margen (de-vig) y
  se calcula `EV% = prob × cuota − 1`. Para evitar sobreconfianza, la probabilidad usada
  en el EV **mezcla modelo + mercado**. El **tablero de valor** ordena los mejores picks
  por estabilidad (`EV × probabilidad`), destacando la *predicción más estable y de buen EV*.

`fetch_worldcup.py` escribe `worldcup.json`; el frontend lo lee y se auto-refresca cada 60 s.

> Solo con fines informativos y de entretenimiento — **no es asesoría de apuestas.
> Apuesta con responsabilidad; +18.**

## Ejecutar localmente

```bash
pip install -r requirements.txt
python fetch_data.py          # genera data.json (mercados)
python fetch_worldcup.py      # genera worldcup.json (Mundial 2026)
python -m http.server 8765    # abre http://localhost:8765
```

## Aviso

Solo con fines informativos. **No constituye asesoría de inversión.**
