# ◧ Market Terminal

Dashboard financiero en vivo con estética **Bloomberg Terminal**. Sigue 5 activos:

| Equities          | Crypto         |
|-------------------|----------------|
| AAPL · Apple      | BTC · Bitcoin  |
| TSLA · Tesla      | ETH · Ethereum |
| NVDA · NVIDIA     |                |

Muestra **precio en vivo**, **fundamentales** (market cap, P/E, EPS, dividend yield,
beta, rango 52 semanas, volumen) y **señales técnicas** COMPRA / MANTENER / VENTA
derivadas de SMA50, SMA200 y RSI-14 calculados sobre histórico de 1 año.

## Cómo funciona (sin API keys)

```
GitHub Actions (cron */15 min)
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

## Ejecutar localmente

```bash
pip install -r requirements.txt
python fetch_data.py          # genera data.json
python -m http.server 8765    # abre http://localhost:8765
```

## Aviso

Solo con fines informativos. **No constituye asesoría de inversión.**
