import os
import json
import time
import datetime
import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd
import ta
import ccxt
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv(override=False)

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT",
    "AVAX/USDT", "LINK/USDT", "DOGE/USDT", "XRP/USDT"
]

NEWS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
]

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    print("ANTHROPIC_API_KEY not found")
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


def fetch_news(coin):
    headlines = []
    coin_name = coin.split("/")[0].lower()
    name_map = {
        "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
        "avax": "avalanche", "link": "chainlink", "doge": "dogecoin", "xrp": "ripple"
    }
    keywords = [coin_name, name_map.get(coin_name, coin_name)]

    for feed_url in NEWS_FEEDS:
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                content = resp.read()
            root = ET.fromstring(content)
            for item in root.iter("item"):
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    title = title_el.text.strip()
                    if any(kw in title.lower() for kw in keywords + ["crypto", "market", "bitcoin"]):
                        headlines.append(title)
                if len(headlines) >= 10:
                    break
        except Exception:
            continue
        if len(headlines) >= 10:
            break

    return headlines[:8]


def analyze_timeframe(df):
    rsi = float(ta.momentum.RSIIndicator(df["close"], window=14).rsi().iloc[-1])

    stoch_rsi = ta.momentum.StochRSIIndicator(df["close"], window=14)
    stoch_k = float(stoch_rsi.stochrsi_k().iloc[-1])
    stoch_d = float(stoch_rsi.stochrsi_d().iloc[-1])

    macd_obj = ta.trend.MACD(df["close"])
    macd_val = float(macd_obj.macd().iloc[-1])
    macd_signal_val = float(macd_obj.macd_signal().iloc[-1])
    macd_hist = float(macd_obj.macd_diff().iloc[-1])
    macd_bullish = macd_val > macd_signal_val

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

    atr = float(ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14
    ).average_true_range().iloc[-1])
    atr_pct = round(atr / price * 100, 2)

    williams_r = float(ta.momentum.WilliamsRIndicator(
        df["high"], df["low"], df["close"], lbp=14
    ).williams_r().iloc[-1])
    cci = float(ta.trend.CCIIndicator(
        df["high"], df["low"], df["close"], window=20
    ).cci().iloc[-1])

    vol_avg = float(df["vol"].tail(20).mean())
    vol_current = float(df["vol"].iloc[-1])
    vol_ratio = round(vol_current / vol_avg, 2)
    if vol_ratio > 1.5:
        vol_signal = "HIGH"
    elif vol_ratio < 0.5:
        vol_signal = "LOW"
    else:
        vol_signal = "NORMAL"

    return {
        "price": round(price, 6),
        "rsi": round(rsi, 1),
        "stoch_k": round(stoch_k * 100, 1),
        "stoch_d": round(stoch_d * 100, 1),
        "macd": "BULLISH" if macd_bullish else "BEARISH",
        "macd_hist": round(macd_hist, 6),
        "trend": trend,
        "above_ema200": price > ema200,
        "ema9": round(ema9, 6),
        "ema21": round(ema21, 6),
        "ema50": round(ema50, 6),
        "ema200": round(ema200, 6),
        "bb_position": bb_position,
        "bb_width": bb_width,
        "bb_upper": round(bb_upper, 6),
        "bb_lower": round(bb_lower, 6),
        "atr_pct": atr_pct,
        "williams_r": round(williams_r, 1),
        "cci": round(cci, 1),
        "volume": vol_signal,
        "vol_ratio": vol_ratio,
        "resistance": round(float(df["high"].tail(20).max()), 6),
        "support": round(float(df["low"].tail(20).min()), 6),
    }


def get_market_data(symbol):
    result = {"symbol": symbol}

    ohlcv_1h = exchange.fetch_ohlcv(symbol, "1h", limit=200)
    df_1h = pd.DataFrame(ohlcv_1h, columns=["ts", "open", "high", "low", "close", "vol"])
    result["tf_1h"] = analyze_timeframe(df_1h)
    result["price"] = result["tf_1h"]["price"]

    try:
        ohlcv_4h = exchange.fetch_ohlcv(symbol, "4h", limit=200)
        df_4h = pd.DataFrame(ohlcv_4h, columns=["ts", "open", "high", "low", "close", "vol"])
        result["tf_4h"] = analyze_timeframe(df_4h)
    except Exception as e:
        print("4h error: " + str(e))
        result["tf_4h"] = None

    try:
        ohlcv_1d = exchange.fetch_ohlcv(symbol, "1d", limit=200)
        df_1d = pd.DataFrame(ohlcv_1d, columns=["ts", "open", "high", "low", "close", "vol"])
        result["tf_1d"] = analyze_timeframe(df_1d)
    except Exception as e:
        print("1d error: " + str(e))
        result["tf_1d"] = None

    return result


def tf_summary(tf_data, name):
    if not tf_data:
        return name + ": unavailable"
    lines = [
        name + " (price: $" + str(tf_data["price"]) + "):",
        "  RSI=" + str(tf_data["rsi"]) + " | StochRSI K/D=" + str(tf_data["stoch_k"]) + "/" + str(tf_data["stoch_d"]),
        "  MACD=" + tf_data["macd"] + " (hist=" + str(tf_data["macd_hist"]) + ")",
        "  Trend=" + tf_data["trend"] + " | Above EMA200=" + str(tf_data["above_ema200"]),
        "  BB=" + tf_data["bb_position"] + " (width=" + str(tf_data["bb_width"]) + "%)",
        "  ATR%=" + str(tf_data["atr_pct"]) + " | Williams%R=" + str(tf_data["williams_r"]) + " | CCI=" + str(tf_data["cci"]),
        "  Volume=" + tf_data["volume"] + " (" + str(tf_data["vol_ratio"]) + "x avg)",
        "  Support=$" + str(tf_data["support"]) + " | Resistance=$" + str(tf_data["resistance"]),
    ]
    return "\n".join(lines)


def run_cycle(symbol):
    try:
        market = get_market_data(symbol)
    except Exception as e:
        return {"symbol": symbol, "action": "HOLD", "confidence": 0, "reason": "Error: " + str(e)}

    # Fetch news
    news = []
    try:
        news = fetch_news(symbol)
        print("News fetched: " + str(len(news)) + " headlines")
    except Exception as e:
        print("News error: " + str(e))

    news_block = ""
    if news:
        news_block = "\nRECENT NEWS HEADLINES:\n" + "\n".join("- " + h for h in news) + "\n"

    lines = [
        "You are a professional crypto trader. Analyze ALL timeframes and recent news, then give a signal.",
        "Use multi-timeframe confluence — higher timeframes (4h, 1d) confirm direction,",
        "lower timeframe (1h) gives entry point. News can confirm or contradict technical signals.",
        "",
        "SYMBOL: " + market["symbol"],
        "CURRENT PRICE: $" + str(market["price"]),
        "",
        tf_summary(market["tf_1h"], "1H TIMEFRAME"),
        "",
        tf_summary(market["tf_4h"], "4H TIMEFRAME"),
        "",
        tf_summary(market["tf_1d"], "1D TIMEFRAME"),
        news_block,
        "CONFLUENCE RULES:",
        "- If 1d and 4h trend is UP and 1h gives BUY signal → STRONG BUY",
        "- If timeframes conflict → HOLD or reduce confidence",
        "- Positive news + bullish technicals = higher confidence",
        "- Negative news + bearish technicals = higher confidence for SELL",
        "- News alone without technical confirmation = lower confidence",
        "",
        "Reply ONLY with valid JSON, no markdown:",
        '{"action":"HOLD","confidence":0.7,"stop_loss":0,"take_profit":0,"reason":"detailed reason in Russian mentioning timeframes and news if relevant"}',
        "",
        "action: BUY, SELL or HOLD only",
        "confidence: 0.0 to 1.0",
        "stop_loss and take_profit: exact price levels",
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

    result = {
        "symbol": symbol,
        "price": market["price"],
        "tf_1h": market["tf_1h"],
        "tf_4h": market["tf_4h"],
        "tf_1d": market["tf_1d"],
        "news": news,
    }
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
    print("Saved: signal_" + key + ".json")
    try:
        save_to_db(symbol, signal)
        print("Saved to DB: " + symbol)
    except Exception as e:
        print("DB error: " + str(e))


def wait_until_next_hour():
    now = datetime.datetime.now()
    next_hour = now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
    wait = (next_hour - now).total_seconds()
    print("Next cycle at " + next_hour.strftime("%H:00") + " (wait " + str(int(wait // 60)) + " min)")
    time.sleep(wait)


if __name__ == "__main__":
    print("=" * 50)
    print("Agent started — Multi-Timeframe + News")
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
            tf1 = signal.get("tf_1h") or {}
            tf4 = signal.get("tf_4h") or {}
            tf1d = signal.get("tf_1d") or {}
            print("Price: $" + str(signal.get("price", 0)))
            print("1H: RSI=" + str(tf1.get("rsi")) + " MACD=" + str(tf1.get("macd")) + " Trend=" + str(tf1.get("trend")))
            print("4H: RSI=" + str(tf4.get("rsi")) + " MACD=" + str(tf4.get("macd")) + " Trend=" + str(tf4.get("trend")))
            print("1D: RSI=" + str(tf1d.get("rsi")) + " MACD=" + str(tf1d.get("macd")) + " Trend=" + str(tf1d.get("trend")))
            print("News: " + str(len(signal.get("news", []))) + " headlines")
            print("Signal: " + str(signal.get("action")) + " | Confidence: " + str(int(signal.get("confidence", 0) * 100)) + "%")
            print(str(signal.get("reason", "")))
            save_signal(symbol, signal)
        wait_until_next_hour()
