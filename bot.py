import os
import json
import time
from datetime import datetime, timezone
import pandas as pd
import requests

ESTADISTICAS_FILE = "estadisticas.json"
PENDIENTE_FILE = "operacion_pendiente.json"

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

def cargar_json(filepath, default_val):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return default_val
    return default_val

def guardar_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=4)

def verificar_filtro_tiempo():
    ahora = datetime.now(timezone.utc)
    segundos_en_minuto = ahora.second + (ahora.microsecond / 1_000_000)
    segundos_en_ciclo = (ahora.minute % 5) * 60 + segundos_en_minuto
    
    print(f"[{ahora.strftime('%Y-%m-%d %H:%M:%S UTC')}] Segundos transcurridos en el ciclo de 5m: {segundos_en_ciclo:.2f}s")
    
    if segundos_en_ciclo > 230:
        print("❌ Filtro de tiempo activado: Se superaron los 230 segundos. Descartando señal.")
        return False
    return True

def evaluar_operacion_anterior(precio_actual):
    pendiente = cargar_json(PENDIENTE_FILE, None)
    if not pendiente:
        return

    stats = cargar_json(ESTADISTICAS_FILE, {"wins": 0, "losses": 0, "total": 0})
    tipo = pendiente["tipo"]
    precio_entrada = pendiente["precio_entrada"]
    
    resultado = "PENDIENTE"
    if tipo == "CALL":
        if precio_actual > precio_entrada:
            resultado = "WIN (ITM) 🟢"
            stats["wins"] += 1
        else:
            resultado = "LOSS (OTM) 🔴"
            stats["losses"] += 1
    elif tipo == "PUT":
        if precio_actual < precio_entrada:
            resultado = "WIN (ITM) 🟢"
            stats["wins"] += 1
        else:
            resultado = "LOSS (OTM) 🔴"
            stats["losses"] += 1
            
    stats["total"] += 1
    winrate = (stats["wins"] / stats["total"]) * 100 if stats["total"] > 0 else 0
    
    msg_eval = (
        f"📊 *Evaluación Operación Anterior*\n"
        f"• Tipo: `{tipo}`\n"
        f"• Entrada: `{precio_entrada}`\n"
        f"• Salida actual: `{precio_actual}`\n"
        f"• Resultado: *{resultado}*\n\n"
        f"📈 *Estadísticas:* Total: {stats['total']} | Wins: {stats['wins']} | Losses: {stats['losses']} | Winrate: {winrate:.1f}%"
    )
    print(msg_eval)
    enviar_telegram(msg_eval)
    
    guardar_json(ESTADISTICAS_FILE, stats)
    if os.path.exists(PENDIENTE_FILE):
        os.remove(PENDIENTE_FILE)

def obtener_velas_binance():
    """Consulta directa a la API pública de Binance Spot para evitar bloqueos geográficos de CCXT"""
    url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=100"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if isinstance(data, list):
            return data
        else:
            print(f"Error en respuesta de Binance: {data}")
            return None
    except Exception as e:
        print(f"Error conectando a la API de Binance: {e}")
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
    if not verificar_filtro_tiempo():
        return

    raw_data = obtener_velas_binance()
    if not raw_data:
        print("No se pudieron obtener datos de Binance.")
        return

    # Convertir a DataFrame (la API devuelve [timestamp, open, high, low, close, volume, ...])
    df = pd.DataFrame(raw_data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume', 
        'close_time', 'quote_asset_volume', 'number_of_trades', 
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    
    # Convertir columnas de precios a float
    df['close'] = df['close'].astype(float)
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)

    df = calcular_indicadores(df)

    precio_actual = df['close'].iloc[-1]
    evaluar_operacion_anterior(precio_actual)

    ema20 = df['ema20'].iloc[-1]
    ema50 = df['ema50'].iloc[-1]
    rsi = df['rsi'].iloc[-1]
    
    senal = None
    if ema20 > ema50 and 40 < rsi < 55:
        if precio_actual <= ema20:
            senal = "CALL"
    elif ema20 < ema50 and 45 < rsi < 60:
        if precio_actual >= ema20:
            senal = "PUT"
            
    if not senal:
        if rsi < 35:
            senal = "CALL"
        elif rsi > 65:
            senal = "PUT"

    print(f"💡 Precio BTC: {precio_actual} | EMA20: {ema20:.2f} | EMA50: {ema50:.2f} | RSI: {rsi:.2f}")

    if senal:
        msg_senal = (
            f"🚨 *¡NUEVA SEÑAL BINARIAS (5m)*\n\n"
            f"🪙 Par: `BTC/USDT`\n"
            f"📈 Dirección: *{senal}*\n"
            f"💵 Precio sugerido: `{precio_actual}`\n"
            f"📊 RSI: `{rsi:.2f}` | EMA20: `{ema20:.2f}`"
        )
        print(msg_senal)
        enviar_telegram(msg_senal)
        
        nueva_operacion = {
            "timestamp": int(time.time()),
            "tipo": senal,
            "precio_entrada": precio_actual
        }
        guardar_json(PENDIENTE_FILE, nueva_operacion)
    else:
        print("⏳ Sin condiciones claras de entrada en este ciclo.")

if __name__ == "__main__":
    main()
    
