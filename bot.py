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
    df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
    df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
    
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

    # FILTRO DE TIEMPO (Primeros 200 segundos del ciclo de 5 minutos para dar margen de entrada)
    ahora = datetime.now(timezone.utc)
    segundos_en_minuto = ahora.second + (ahora.microsecond / 1_000_000)
    segundos_en_ciclo = (ahora.minute % 5) * 60 + segundos_en_minuto
    
    print(f"[{ahora.strftime('%Y-%m-%d %H:%M:%S UTC')}] Segundos transcurridos en el ciclo de 5m: {segundos_en_ciclo:.2f}s")
    
    if segundos_en_ciclo > 200:
        print("❌ Filtro de tiempo activado: Fuera del tiempo óptimo de entrada. Omitiendo búsqueda.")
        return

    # INDICADORES ÁGILES
    df = calcular_indicadores(df)
    ema10 = df['ema10'].iloc[-1]
    ema30 = df['ema30'].iloc[-1]
    rsi = df['rsi'].iloc[-1]
    
    senal = None
    
    # ESTRATEGIA DE MOMENTUM RÁPIDO Y REVERSIÓN EN ZONAS CLAVE
    # 1. Si la EMA rápida cruza o está por encima y el RSI no está sobrecomprado extremo
    if ema10 > ema30 and rsi < 65 and rsi > 35:
        if precio_actual >= ema10:  # Rebote alcista sobre la media rápida
            senal = "CALL"
            
    # 2. Si la EMA rápida está por debajo y el RSI no está sobrevendido extremo
    elif ema10 < ema30 and rsi > 35 and rsi < 65:
        if precio_actual <= ema10:  # Rebote bajista bajo la media rápida
            senal = "PUT"

    # 3. Respaldo por extremos puros de RSI (Sobreventa / Sobrecompra para giros rápidos de 5m)
    if not senal:
        if rsi < 32:
            senal = "CALL"
        elif rsi > 68:
            senal = "PUT"

    print(f"💡 Precio BTC: {precio_actual} | EMA10: {ema10:.2f} | EMA30: {ema30:.2f} | RSI: {rsi:.2f} | Señal: {senal}")

    if senal:
        if senal == "CALL":
            op_texto = "CALL 🟢 (SUBIR / VERDE)"
            consejo = "Impulso alcista detectado. Entra buscando el rebote de la vela."
        else:
            op_texto = "PUT 🔴 (BAJAR / ROJA)"
            consejo = "Impulso bajista detectado. Entra buscando el retroceso a la baja."

        msg_senal = (
            f"OPCIONES BINARIAS BTC (FAST) 🎯\n\n"
            f"Señal Detectada: {op_texto}\n\n"
            f"• Expiración: Vela de 5 Minutos\n"
            f"• Precio Actual: ${precio_actual:,.2f}\n"
            f"• RSI Actual: {rsi:.1f}\n\n"
            f"💡 CONSEJO:\n"
            f"{consejo}"
        )
        print(msg_senal)
        enviar_telegram(msg_senal)
    else:
        print("⏳ Mercado en consolidación. Buscando en el siguiente ciclo...")

if __name__ == "__main__":
    main()
    
