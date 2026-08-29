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

## 📰 Noticias que mueven la bolsa + 🇪🇨 Ecuador

Dos pestañas adicionales alimentadas por **RSS público de Google News** (sin keys):

- **NOTICIAS**: titulares internacionales que impactan la bolsa, agrupados por categoría
  — **Big 7/Tecnología**, **Semiconductores/IA**, **Satelital/Espacio**, **Defensa/Armamento**,
  **Petróleo/Energía**, **Guerra/Geopolítica** y **Macro/Bolsa**. En cada noticia se detecta
  el **ticker afectado** (por palabras clave, con match por límite de palabra) y se estima
  una **variación aproximada a 24 h**:

  ```
  variación ≈ dirección · volatilidad_típica_del_ticker · (0.5 + |sentimiento|) · recencia
  ```

  El **sentimiento** sale de un léxico ES/EN (alcista vs bajista) y la **dirección** admite
  relaciones inversas (p. ej. una guerra: defensa ↑, petróleo ↑, bolsa general ↓). Un
  **tablero de impacto por ticker** agrega la variación neta estimada de todo el flujo.
- **ECUADOR**: noticias del mercado ecuatoriano (Bolsa de Valores BVG/BVQ, riesgo país,
  petróleo, deuda, macro) con etiquetas del factor afectado (WTI, riesgo país, dólar) y su
  dirección estimada.

> La variación a 24 h es una **estimación heurística** (sentimiento × volatilidad), **no un
> pronóstico**. Solo con fines informativos — no constituye asesoría de inversión.

`fetch_news.py` escribe `news.json` (compartido por ambas pestañas); el frontend lo carga
al abrir la pestaña y se auto-refresca cada 60 s.

## Ejecutar localmente

```bash
pip install -r requirements.txt
python fetch_data.py          # genera data.json (mercados)
python fetch_news.py          # genera news.json (noticias + Ecuador)
python -m http.server 8765    # abre http://localhost:8765
```

## Aviso

Solo con fines informativos. **No constituye asesoría de inversión.**
