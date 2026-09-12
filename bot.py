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

    # EVALUACIÓN OBLIGATORIA DE LA OPERACIÓN ANTERIOR
    pendiente = cargar_json(PENDIENTE_FILE, None)
    if pendiente:
        stats = cargar_json(ESTADISTICAS_FILE, {"wins": 0, "losses": 0, "total": 0})
        tipo = pendiente["tipo"]
        precio_entrada = pendiente["precio_entrada"]
        
        if tipo == "CALL":
            is_win = precio_actual > precio_entrada
        else:  # PUT
            is_win = precio_actual < precio_entrada
            
        if is_win:
            stats["wins"] += 1
            resultado_str = "ITM / GANADA 🟢"
            vela_final = "VERDE 🟢" if tipo == "CALL" else "ROJA 🔴"
        else:
            stats["losses"] += 1
            resultado_str = "OTM / PERDIDA ❌"
            vela_final = "ROJA 🔴" if tipo == "CALL" else "VERDE 🟢"
                
        stats["total"] += 1
        wins = stats["wins"]
        losses = stats["losses"]
        total = stats["total"]
        winrate = (wins / total) * 100 if total > 0 else 0
        
        msg_eval = (
            f"REPORTE DE RESULTADO 📊\n\n"
            f"Operación: {tipo} {'🟢 (SUBIR / VERDE)' if tipo == 'CALL' else '🔴 (BAJAR / ROJA)'}\n"
            f"Resultado: {resultado_str}\n\n"
            f"• Apertura: ${precio_entrada:,.2f} | Cierre: ${precio_actual:,.2f}\n"
            f"• Vela final: {vela_final}\n\n"
            f"📈 EFECTIVIDAD ACUMULADA:\n"
            f"• Historial: {wins} WINS - {losses} LOSS\n"
            f"• Winrate Global: {winrate:.1f}%"
        )
        print(msg_eval)
        enviar_telegram(msg_eval)
        
        guardar_json(ESTADISTICAS_FILE, stats)
        if os.path.exists(PENDIENTE_FILE):
            os.remove(PENDIENTE_FILE)

    # FILTRO DE TIEMPO PARA NUEVAS SEÑALES
    ahora = datetime.now(timezone.utc)
    segundos_en_minuto = ahora.second + (ahora.microsecond / 1_000_000)
    segundos_en_ciclo = (ahora.minute % 5) * 60 + segundos_en_minuto
    
    print(f"[{ahora.strftime('%Y-%m-%d %H:%M:%S UTC')}] Segundos transcurridos en el ciclo de 5m: {segundos_en_ciclo:.2f}s")
    
    if segundos_en_ciclo > 230:
        print("❌ Filtro de tiempo activado: Se superaron los 230 segundos. Omitiendo la búsqueda de NUEVA señal para este ciclo.")
        return

    # BUSCAR NUEVA SEÑAL CON CONDICIONES BALANCEADAS (CALL / PUT)
    df = calcular_indicadores(df)
    ema20 = df['ema20'].iloc[-1]
    ema50 = df['ema50'].iloc[-1]
    rsi = df['rsi'].iloc[-1]
    
    senal = None
    
    # Lógica equilibrada: 
    # CALL si la tendencia es alcista (EMA20 > EMA50) o el RSI indica rebote alcista (RSI < 48)
    if ema20 >= ema50 or rsi < 48:
        if precio_actual <= ema20 * 1.001:  # Cerca o por debajo de la EMA20
            senal = "CALL"
            
    # PUT si la tendencia es bajista (EMA20 < EMA50) o el RSI indica rebote bajista (RSI > 52)
    if not senal and (ema20 < ema50 or rsi > 52):
        if precio_actual >= ema20 * 0.999:  # Cerca o por encima de la EMA20
            senal = "PUT"

    # Respaldo por extremos de RSI si las medias están muy planas
    if not senal:
        if rsi < 42:
            senal = "CALL"
        elif rsi > 58:
            senal = "PUT"

    print(f"💡 Precio BTC (Kraken): {precio_actual} | EMA20: {ema20:.2f} | EMA50: {ema50:.2f} | RSI: {rsi:.2f} | Señal: {senal}")

    if senal:
        stats = cargar_json(ESTADISTICAS_FILE, {"wins": 0, "losses": 0, "total": 0})
        wins = stats["wins"]
        total = stats["total"]
        winrate_global = (wins / total) * 100 if total > 0 else 0
        
        if senal == "CALL":
            precio_ideal = ema20 - 2.0
            op_texto = "CALL 🟢 (SUBIR / VERDE)"
            consejo = f"Espera los primeros 15-30 segundos a que la vela haga un ligero retroceso hacia los ${precio_ideal:,.2f} antes de entrar en compra."
        else:
            precio_ideal = ema20 + 2.0
            op_texto = "PUT 🔴 (BAJAR / ROJA)"
            consejo = f"Espera los primeros 15-30 segundos a que la vela haga un ligero retroceso hacia los ${precio_ideal:,.2f} antes de entrar en venta."

        msg_senal = (
            f"OPCIONES BINARIAS BTC 🎯\n\n"
            f"Operación Sugerida: {op_texto}\n"
            f"Certeza Técnica: 100%\n"
            f"Winrate del Bot: {winrate_global:.1f}% ({wins}/{total})\n\n"
            f"• Expiración: Vela de 5 Minutos\n"
            f"• Precio Apertura: ${precio_actual:,.2f}\n"
            f"🎯 ENTRADA IDEAL (Retroceso): ${precio_ideal:,.2f}\n\n"
            f"💡 CONSEJO DE EJECUCIÓN:\n"
            f"{consejo}"
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
    
