"""
Bybit Futures - Candle Pattern Signal Scanner
Kondisi:
- Hijau → Hijau + Volume naik 10% → SINYAL BELI (konfirmasi tren naik)
- Merah → Merah + Volume naik 10% → SINYAL JUAL (konfirmasi tren turun)
- Hijau → Merah → BATALKAN (pembalikan arah)
- Merah → Hijau → BATALKAN (pembalikan arah)
- Timeframe: 1 Jam
- Filter koin: Volume 24 jam ≥ $10,000,000 (tidak ada batasan volume per candle)
- Data source: Bybit Public API (tanpa API key)
"""

import requests
import time
from datetime import datetime, timezone

# ─── KONFIGURASI ────────────────────────────────────────────────────────────────
BASE_URL             = "https://api.bybit.com"
CATEGORY             = "linear"      # USDT Perpetual Futures
TIMEFRAME            = "60"          # 1 jam
MIN_VOLUME_24H_USD   = 10_000_000    # Filter koin: volume 24 jam minimal $10 juta
VOLUME_INCREASE      = 0.10          # Kenaikan volume candle minimal 10%
REQUEST_DELAY        = 0.3           # Jeda antar request (detik)

# ─── HELPER FUNCTIONS ────────────────────────────────────────────────────────────

def get_tickers() -> dict:
    """Ambil semua ticker sekaligus."""
    url = f"{BASE_URL}/v5/market/tickers"
    params = {"category": CATEGORY}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        result = {}
        for item in data["result"]["list"]:
            result[item["symbol"]] = {
                "vol24h"    : float(item.get("turnover24h", 0)),
                "last_price": float(item.get("lastPrice", 0)),
            }
        return result
    except Exception as e:
        print(f"[ERROR] Gagal mengambil ticker: {e}")
        return {}


from typing import List, Union

def get_klines(symbol: str, limit: int = 3) -> Union[List, None]:
    """
    Ambil data OHLCV terbaru dari Bybit.
    Indeks 0 = Candle berjalan (belum closed)
    Indeks 1 = Candle tertutup terbaru (N-1)
    Indeks 2 = Candle tertutup sebelumnya (N-2)
    """
    url = f"{BASE_URL}/v5/market/kline"
    params = {
        "category": CATEGORY,
        "symbol"  : symbol,
        "interval": TIMEFRAME,
        "limit"   : limit,
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data["retCode"] != 0:
            return None
        return data["result"]["list"]
    except Exception as e:
        print(f"[ERROR] {symbol}: {e}")
        return None


def parse_candle(raw: list) -> dict:
    """Konversi raw candle ke dict."""
    return {
        "time"    : datetime.fromtimestamp(int(raw[0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "open"    : float(raw[1]),
        "high"    : float(raw[2]),
        "low"     : float(raw[3]),
        "close"   : float(raw[4]),
        "volume"  : float(raw[5]),
        "turnover": float(raw[6]),   # Nilai nominal transaksi dalam USD
        "is_green": float(raw[4]) >= float(raw[1]),
    }


def analyze_symbol(symbol: str) -> dict | None:
    """Analisis pola dua candle terakhir yang sudah closed (Indeks 2 dan Indeks 1)."""
    klines = get_klines(symbol, limit=3)
    if not klines or len(klines) < 3:
        return None

    # Mengabaikan klines[0] karena merupakan candle yang sedang berjalan.
    prev2 = parse_candle(klines[2]) # Candle terlama (N-2)
    prev1 = parse_candle(klines[1]) # Candle terbaru yang sudah closed (N-1)

    if prev2["turnover"] == 0:
        return None
        
    vol_change = (prev1["turnover"] - prev2["turnover"]) / prev2["turnover"]

    # ─── LOGIKA SINYAL ─────────────────────────────────────────────────────────
    both_green = prev2["is_green"] and prev1["is_green"]
    both_red   = (not prev2["is_green"]) and (not prev1["is_green"])
    reversal   = (prev2["is_green"] != prev1["is_green"])

    signal    = None
    reason    = ""
    cancelled = False

    if reversal:
        cancelled = True
        if prev2["is_green"] and not prev1["is_green"]:
            reason = "Reversal: Hijau → Merah (dibatalkan)"
        else:
            reason = "Reversal: Merah → Hijau (dibatalkan)"
    elif both_green and vol_change >= VOLUME_INCREASE:
        signal = "BUY 📈"
        reason = f"Hijau → Hijau | Volume naik {vol_change*100:.1f}%"
    elif both_red and vol_change >= VOLUME_INCREASE:
        signal = "SELL 📉"
        reason = f"Merah → Merah | Volume naik {vol_change*100:.1f}%"
    else:
        return None   # Tidak memenuhi kriteria dasar kenaikan volume atau kesamaan warna

    return {
        "symbol"    : symbol,
        "signal"    : signal,
        "cancelled" : cancelled,
        "reason"    : reason,
        "vol_change": vol_change,
        "prev2"     : prev2,
        "prev1"     : prev1,
    }


def format_usd(value: float) -> str:
    if value >= 1_000_000_000:
        return f"${value/1_000_000_000:.2f}B"
    elif value >= 1_000_000:
        return f"${value/1_000_000:.2f}M"
    elif value >= 1_000:
        return f"${value/1_000:.1f}K"
    return f"${value:.2f}"


# ─── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    scan_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print("=" * 65)
    print("  BYBIT FUTURES — CANDLE PATTERN SIGNAL SCANNER")
    print(f"  Timeframe: 1 Jam  |  Filter Koin: Vol 24j ≥ {format_usd(MIN_VOLUME_24H_USD)}")
    print(f"  Scan Time : {scan_time}")
    print("=" * 65)

    print("\n⏳ Mengambil data ticker...")
    tickers = get_tickers()
    print(f"   Total koin ditemukan: {len(tickers)}")

    qualified = {
        sym: info
        for sym, info in tickers.items()
        if sym.endswith("USDT") and info["vol24h"] >= MIN_VOLUME_24H_USD
    }
    
    qualified_sorted = sorted(qualified.keys(), key=lambda s: qualified[s]["vol24h"], reverse=True)
    print(f"   Koin lolos filter Vol 24j ≥ {format_usd(MIN_VOLUME_24H_USD)}: {len(qualified_sorted)} koin")
    print(f"   Memulai scan pola candle...\n")

    buy_signals    = []
    sell_signals   = []
    cancelled_list = []

    for i, symbol in enumerate(qualified_sorted, 1):
        print(f"\r   Progress: {i}/{len(qualified_sorted)} — {symbol:<20}", end="", flush=True)
        result = analyze_symbol(symbol)
        if result:
            result["vol24h"] = qualified[symbol]["vol24h"]
            if result["cancelled"]:
                cancelled_list.append(result)
            elif result["signal"] == "BUY 📈":
                buy_signals.append(result)
            elif result["signal"] == "SELL 📉":
                sell_signals.append(result)
        time.sleep(REQUEST_DELAY)

    print(f"\r   ✅ Selesai memindai {len(qualified_sorted)} koin{' ' * 20}")

    print("\n" + "=" * 65)
    print("  📊 RINGKASAN HASIL")
    print("=" * 65)
    print(f"  🟢 Sinyal BUY  : {len(buy_signals)}")
    print(f"  🔴 Sinyal SELL : {len(sell_signals)}")
    print(f"  ⚠️  Dibatalkan  : {len(cancelled_list)}")

    def print_signal(r, color_emoji):
        p2, p1 = r["prev2"], r["prev1"]
        print(f"\n  📌 {r['symbol']}  (Vol 24j: {format_usd(r['vol24h'])})")
        print(f"     {r['reason']}")
        print(f"     Candle N-2 [{p2['time']}]")
        print(f"       O:{p2['open']:.4f}  C:{p2['close']:.4f}  Vol:{format_usd(p2['turnover'])}  {color_emoji}")
        print(f"     Candle N-1 [{p1['time']}]")
        print(f"       O:{p1['open']:.4f}  C:{p1['close']:.4f}  Vol:{format_usd(p1['turnover'])}  {color_emoji}")
        print(f"     Δ Volume Candle : {'+' if r['vol_change']>=0 else ''}{r['vol_change']*100:.1f}%")

    if buy_signals:
        print("\n" + "─" * 65)
        print("  🟢 SINYAL BUY (Hijau → Hijau + Volume Candle Naik ≥10%)")
        print("─" * 65)
        for r in buy_signals:
            print_signal(r, "🟢")

    if sell_signals:
        print("\n" + "─" * 65)
        print("  🔴 SINYAL SELL (Merah → Merah + Volume Candle Naik ≥10%)")
        print("─" * 65)
        for r in sell_signals:
            print_signal(r, "🔴")

    if cancelled_list:
        print("\n" + "─" * 65)
        print("  ⚠️  REVERSAL / DIBATALKAN (Pembalikan Arah Warna)")
        print("─" * 65)
        for r in cancelled_list:
            # Menggunakan emoji dinamis berdasarkan kondisi lilin terakhirnya
            emoji = "🟢" if r["prev1"]["is_green"] else "🔴"
            print_signal(r, emoji)

if __name__ == "__main__":
    main()
