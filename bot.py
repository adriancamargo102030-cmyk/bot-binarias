import os
import json
import time
from datetime import datetime, timezone
import pandas as pd
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Credenciales de Telegram no configuradas. Omitiendo mensaje.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error enviando mensaje a Telegram: {e}")

def obtener_velas_kraken():
    url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=5"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if "result" in data and "XXBTZUSD" in data["result"]:
            return data["result"]["XXBTZUSD"]
        else:
            print(f"Error en respuesta de Kraken: {data}")
            return None
    except Exception as e:
        print(f"Error conectando a la API de Kraken: {e}")
        return None

def calcular_indicadores(df):
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def main():
    raw_data = obtener_velas_kraken()
    if not raw_data:
        print("No se pudieron obtener datos de mercado.")
        return

    df = pd.DataFrame(raw_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'])
    df['close'] = df['close'].astype(float)
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)

    precio_actual = df['close'].iloc[-1]

    # FILTRO DE TIEMPO (Primeros 230 segundos del ciclo de 5 minutos)
    ahora = datetime.now(timezone.utc)
    segundos_en_minuto = ahora.second + (ahora.microsecond / 1_000_000)
    segundos_en_ciclo = (ahora.minute % 5) * 60 + segundos_en_minuto
    
    print(f"[{ahora.strftime('%Y-%m-%d %H:%M:%S UTC')}] Segundos transcurridos en el ciclo de 5m: {segundos_en_ciclo:.2f}s")
    
    if segundos_en_ciclo > 230:
        print("❌ Filtro de tiempo activado: Se superaron los 230 segundos. Omitiendo búsqueda de señal.")
        return

    # FILTROS TÉCNICOS DE ALTA CERTEZA
    df = calcular_indicadores(df)
    ema20 = df['ema20'].iloc[-1]
    ema50 = df['ema50'].iloc[-1]
    rsi = df['rsi'].iloc[-1]
    
    vela_anterior_verde = df['close'].iloc[-2] > df['open'].iloc[-2]
    vela_anterior_roja = df['close'].iloc[-2] < df['open'].iloc[-2]
    
    senal = None
    
    # REGLA DE ALTA CERTEZA PARA CALL (COMPRA)
    if ema20 > ema50 and 42 < rsi < 58:
        if precio_actual <= ema20 * 1.0015 and vela_anterior_verde:
            senal = "CALL"
            
    # REGLA DE ALTA CERTEZA PARA PUT (VENTA)
    elif ema20 < ema50 and 42 < rsi < 58:
        if precio_actual >= ema20 * 0.9985 and vela_anterior_roja:
            senal = "PUT"

    print(f"💡 Precio BTC: {precio_actual} | EMA20: {ema20:.2f} | EMA50: {ema50:.2f} | RSI: {rsi:.2f} | Señal Detectada: {senal}")

    if senal:
        if senal == "CALL":
            precio_ideal = ema20 - 1.5
            op_texto = "CALL 🟢 (SUBIR / VERDE)"
            consejo = "Tendencia alcista confirmada. Espera 15-30s un micro-retroceso hacia la EMA antes de entrar."
        else:
            precio_ideal = ema20 + 1.5
            op_texto = "PUT 🔴 (BAJAR / ROJA)"
            consejo = "Tendencia bajista confirmada. Espera 15-30s un micro-retroceso hacia la EMA antes de entrar."

        msg_senal = (
            f"OPCIONES BINARIAS BTC (PRO) 🎯\n\n"
            f"Señal de Alta Certeza: {op_texto}\n\n"
            f"• Expiración: Vela de 5 Minutos\n"
            f"• Precio Apertura: ${precio_actual:,.2f}\n"
            f"🎯 ENTRADA IDEAL: ${precio_ideal:,.2f}\n\n"
            f"💡 CONSEJO:\n"
            f"{consejo}"
        )
        print(msg_senal)
        enviar_telegram(msg_senal)
    else:
        print("⏳ Mercado en rango o sin confirmación estricta. No se emite señal.")

if __name__ == "__main__":
    main()
    
