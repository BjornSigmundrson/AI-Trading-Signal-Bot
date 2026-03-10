import os
import json
import time
import datetime
import pandas as pd
import ta
import ccxt
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv(override=False)

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    print("ANTHROPIC_API_KEY not found in .env")
    exit(1)
print("Anthropic API key found")


def make_exchange():
    for ex in [ccxt.okx(), ccxt.kraken(), ccxt.kucoin()]:
        try:
            ex.fetch_ticker("BTC/USDT")
            print("Exchange: " + ex.id)
            return ex
        except Exception:
            continue
    raise Exception("All exchanges unavailable")


exchange = make_exchange()
llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)


def get_market_data(symbol):
    ohlcv = exchange.fetch_ohlcv(symbol, "1h", limit=200)
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])

    # RSI
    rsi = float(ta.momentum.RSIIndicator(df["close"], window=14).rsi().iloc[-1])

    # Stochastic RSI
    stoch_rsi = ta.momentum.StochRSIIndicator(df["close"], window=14)
    stoch_k = float(stoch_rsi.stochrsi_k().iloc[-1])
    stoch_d = float(stoch_rsi.stochrsi_d().iloc[-1])

    # MACD
    macd_obj = ta.trend.MACD(df["close"])
    macd_val = float(macd_obj.macd().iloc[-1])
    macd_signal = float(macd_obj.macd_signal().iloc[-1])
    macd_hist = float(macd_obj.macd_diff().iloc[-1])
    macd_bullish = macd_val > macd_signal

    # EMA 9 / 21 / 50 / 200
    ema9 = float(df["close"].ewm(span=9).mean().iloc[-1])
    ema21 = float(df["close"].ewm(span=21).mean().iloc[-1])
    ema50 = float(df["close"].ewm(span=50).mean().iloc[-1])
    ema200 = float(df["close"].ewm(span=200).mean().iloc[-1])
    price = float(df["close"].iloc[-1])

    if ema9 > ema21 > ema50:
        trend = "STRONG_UP"
    elif ema9 > ema21:
        trend = "UP"
    elif ema9 < ema21 < ema50:
        trend = "STRONG_DOWN"
    elif ema9 < ema21:
        trend = "DOWN"
    else:
        trend = "FLAT"

    above_ema200 = price > ema200

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    bb_upper = float(bb.bollinger_hband().iloc[-1])
    bb_lower = float(bb.bollinger_lband().iloc[-1])
    bb_mid = float(bb.bollinger_mavg().iloc[-1])
    bb_width = round((bb_upper - bb_lower) / bb_mid * 100, 2)
    if price >= bb_upper:
        bb_position = "ABOVE_UPPER"
    elif price <= bb_lower:
        bb_position = "BELOW_LOWER"
    elif price > bb_mid:
        bb_position = "UPPER_HALF"
    else:
        bb_position = "LOWER_HALF"

    # ATR (volatility)
    atr = float(ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range().iloc[-1])
    atr_pct = round(atr / price * 100, 2)

    # Williams %R
    williams_r = float(ta.momentum.WilliamsRIndicator(df["high"], df["low"], df["close"], lbp=14).williams_r().iloc[-1])

    # CCI
    cci = float(ta.trend.CCIIndicator(df["high"], df["low"], df["close"], window=20).cci().iloc[-1])

    # Volume analysis
    vol_avg = float(df["vol"].tail(20).mean())
    vol_current = float(df["vol"].iloc[-1])
    vol_ratio = round(vol_current / vol_avg, 2)
    if vol_ratio > 1.5:
        vol_signal = "HIGH"
    elif vol_ratio < 0.5:
        vol_signal = "LOW"
    else:
        vol_signal = "NORMAL"

    # Support / Resistance (simple)
    high_20 = round(float(df["high"].tail(20).max()), 2)
    low_20 = round(float(df["low"].tail(20).min()), 2)

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "rsi": round(rsi, 1),
        "stoch_rsi_k": round(stoch_k * 100, 1),
        "stoch_rsi_d": round(stoch_d * 100, 1),
        "macd": "BULLISH" if macd_bullish else "BEARISH",
        "macd_histogram": round(macd_hist, 4),
        "trend": trend,
        "above_ema200": above_ema200,
        "ema9": round(ema9, 2),
        "ema21": round(ema21, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "bb_position": bb_position,
        "bb_width_pct": bb_width,
        "bb_upper": round(bb_upper, 2),
        "bb_lower": round(bb_lower, 2),
        "atr_pct": atr_pct,
        "williams_r": round(williams_r, 1),
        "cci": round(cci, 1),
        "volume": vol_signal,
        "volume_ratio": vol_ratio,
        "resistance_20": high_20,
        "support_20": low_20,
    }


def run_cycle(symbol):
    try:
        market = get_market_data(symbol)
    except Exception as e:
        return {"symbol": symbol, "action": "HOLD", "confidence": 0, "reason": "Error: " + str(e)}

    lines = [
        "You are a professional crypto trader. Analyze ALL indicators and give a signal.",
        "",
        "MARKET DATA (" + market["symbol"] + ", 1h timeframe):",
        "Price: $" + str(market["price"]),
        "",
        "MOMENTUM:",
        "RSI(14): " + str(market["rsi"]),
        "Stoch RSI K/D: " + str(market["stoch_rsi_k"]) + " / " + str(market["stoch_rsi_d"]),
        "Williams %R: " + str(market["williams_r"]),
        "CCI(20): " + str(market["cci"]),
        "",
        "TREND:",
        "MACD: " + market["macd"] + " (histogram: " + str(market["macd_histogram"]) + ")",
        "EMA Trend: " + market["trend"],
        "Above EMA200: " + str(market["above_ema200"]),
        "EMA9/21/50/200: " + str(market["ema9"]) + " / " + str(market["ema21"]) + " / " + str(market["ema50"]) + " / " + str(market["ema200"]),
        "",
        "VOLATILITY:",
        "Bollinger Bands: " + market["bb_position"] + " (width: " + str(market["bb_width_pct"]) + "%)",
        "BB Upper/Lower: " + str(market["bb_upper"]) + " / " + str(market["bb_lower"]),
        "ATR%: " + str(market["atr_pct"]) + "% (volatility)",
        "",
        "VOLUME:",
        "Volume: " + market["volume"] + " (ratio vs avg: " + str(market["volume_ratio"]) + "x)",
        "",
        "KEY LEVELS:",
        "20h Resistance: $" + str(market["resistance_20"]),
        "20h Support: $" + str(market["support_20"]),
        "",
        "Reply ONLY with valid JSON, no markdown:",
        '{"action":"HOLD","confidence":0.7,"stop_loss":0,"take_profit":0,"reason":"detailed reason in Russian, mention key indicators"}',
        "",
        "action: BUY, SELL or HOLD only",
        "confidence: 0.0 to 1.0",
        "stop_loss and take_profit: price levels",
    ]
    prompt = "\n".join(lines)

    response = llm.invoke([{"role": "user", "content": prompt}])
    try:
        decision = json.loads(response.content.strip())
    except Exception:
        decision = {
            "action": "HOLD",
            "confidence": 0.0,
            "stop_loss": 0,
            "take_profit": 0,
            "reason": "Parse error",
        }

    result = {}
    result.update(market)
    result.update(decision)
    result["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return result


def save_to_db(symbol, signal):
    import psycopg2
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS signals "
        "(id SERIAL PRIMARY KEY, symbol VARCHAR(20), data JSONB, created_at TIMESTAMP DEFAULT NOW())"
    )
    try:
        cur.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS symbol VARCHAR(20)")
    except Exception:
        pass
    cur.execute(
        "INSERT INTO signals (symbol, data) VALUES (%s, %s)",
        [symbol, json.dumps(signal)],
    )
    conn.commit()
    cur.close()
    conn.close()


def save_signal(symbol, signal):
    key = symbol.replace("/", "_")
    with open("signal_" + key + ".json", "w", encoding="utf-8") as f:
        json.dump(signal, f, ensure_ascii=False, indent=2)
    if symbol == "BTC/USDT":
        with open("last_signal.json", "w", encoding="utf-8") as f:
            json.dump(signal, f, ensure_ascii=False, indent=2)
    print("Saved to file: signal_" + key + ".json")
    try:
        save_to_db(symbol, signal)
        print("Saved to DB: " + symbol)
    except Exception as e:
        print("DB error: " + str(e))


def wait_until_next_hour():
    now = datetime.datetime.now()
    next_hour = now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
    wait = (next_hour - now).total_seconds()
    print("Next cycle at " + next_hour.strftime("%H:00") + " (wait " + str(int(wait)) + " sec / " + str(int(wait // 60)) + " min)")
    time.sleep(wait)


if __name__ == "__main__":
    print("=" * 50)
    print("Agent started")
    print("Pairs: " + ", ".join(SYMBOLS))
    print("Cycle: every hour at :00")
    print("=" * 50)

    cycle = 0
    while True:
        cycle += 1
        print("\n=== Cycle #" + str(cycle) + " ===")
        for symbol in SYMBOLS:
            print("\n--- " + symbol + " ---")
            signal = run_cycle(symbol)
            print("Price: $" + str(signal.get("price", 0)))
            print("RSI=" + str(signal.get("rsi")) + " | StochRSI=" + str(signal.get("stoch_rsi_k")) + " | MACD=" + str(signal.get("macd")))
            print("Trend=" + str(signal.get("trend")) + " | BB=" + str(signal.get("bb_position")) + " | Vol=" + str(signal.get("volume")))
            print("Williams%R=" + str(signal.get("williams_r")) + " | CCI=" + str(signal.get("cci")) + " | ATR%=" + str(signal.get("atr_pct")))
            print("Signal: " + str(signal.get("action")) + " | Confidence: " + str(int(signal.get("confidence", 0) * 100)) + "%")
            print(str(signal.get("reason", "")))
            save_signal(symbol, signal)
        wait_until_next_hour()
