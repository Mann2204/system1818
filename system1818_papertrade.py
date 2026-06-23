"""
╔══════════════════════════════════════════════════════════════╗
║   SYSTEM 1818 — Paper Trade Engine                          ║
║   Live NSE prices via yfinance · Rule-based signals         ║
║   Deploy free: streamlit.io/cloud                           ║
╚══════════════════════════════════════════════════════════════╝

Deploy steps:
1. Push this file + requirements.txt to a GitHub repo
2. Go to share.streamlit.io → New app → select your repo
3. Main file: system1818_papertrade.py
4. Done — runs in browser, no local Python needed

requirements.txt contents:
    streamlit
    yfinance
    pandas
    numpy
    pytz
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, time as dtime
import math
import time
import pytz
import streamlit.components.v1 as components

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SYSTEM 1818 | Paper Trade Engine",
    layout="wide",
    initial_sidebar_state="collapsed",
    page_icon="📊",
)

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────
IST            = pytz.timezone("Asia/Kolkata")
ACCOUNT_BASE   = 100_000
MAX_TRADE_RISK = 2_000
MAX_DAILY_LOSS = 4_000
SLIPPAGE       = 0.7
LOT_SIZE       = {"NIFTY": 65, "BANKNIFTY": 30}

SYMBOLS = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
}

VIX_TICKER = "^INDIAVIX"

REGIME_META = {
    1: {
        "name":  "Range Quiet",
        "color": "#3BA7FF",
        "bg":    "#0d1e33",
        "desc":  "Accumulation/Distribution — price contained, wait for breakout",
    },
    2: {
        "name":  "Trend Momentum",
        "color": "#33FF99",
        "bg":    "#0d2b1e",
        "desc":  "Institutional breakout — directional move confirmed, ride it",
    },
    3: {
        "name":  "Range Volatile",
        "color": "#FF4D4D",
        "bg":    "#2b0d0d",
        "desc":  "Retail whipsaw trap — fakeout-prone, reduce size or skip",
    },
    4: {
        "name":  "Trend Quiet",
        "color": "#FFC93B",
        "bg":    "#2b220d",
        "desc":  "Low-vol directional grind along 20-EMA, tight SL",
    },
}

PHASE_META = {
    "PRE_MARKET":     {"label": "PRE-MARKET",     "color": "#3BA7FF"},
    "OPENING_FREEZE": {"label": "OPENING FREEZE", "color": "#FFC93B"},
    "ACTIVE":         {"label": "ACTIVE",          "color": "#33FF99"},
    "MIDDAY_FREEZE":  {"label": "MID-DAY FREEZE", "color": "#FF8C00"},
    "ACTIVE_PM":      {"label": "ACTIVE PM",       "color": "#33FF99"},
    "CLOSING":        {"label": "CLOSING",          "color": "#9B59B6"},
    "LOCKED":         {"label": "LOCKED 🛑",       "color": "#FF4D4D"},
    "CLOSED":         {"label": "MARKET CLOSED",   "color": "#6b7785"},
}

# ─────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&display=swap');
.stApp { background:#060a0f; color:#c9d1d9; }
.block-container { padding:1rem 2rem 3rem 2rem; max-width:100%; }
#MainMenu, footer, header { visibility:hidden; }
div[data-testid="stMetric"] {
    background:#0d1117; border:1px solid #1c2333;
    border-radius:8px; padding:12px 14px;
}
div[data-testid="stMetricLabel"] {
    font-family:'JetBrains Mono',monospace; font-size:0.65rem;
    color:#6b7785; text-transform:uppercase; letter-spacing:1.5px;
}
div[data-testid="stMetricValue"] {
    font-family:'JetBrains Mono',monospace; font-size:1.3rem; color:#e6edf3;
}
.drow {
    display:flex; justify-content:space-between;
    padding:4px 0; border-bottom:0.5px solid #0d1a26;
    font-family:'JetBrains Mono',monospace; font-size:0.8rem;
}
.dlbl { color:#8b949e; }
.dval { color:#e6edf3; font-weight:600; }
.section-lbl {
    font-family:'JetBrains Mono',monospace; font-size:0.62rem;
    color:#3BA7FF; text-transform:uppercase; letter-spacing:3px;
    margin:16px 0 8px 0; display:flex; align-items:center; gap:10px;
}
.section-lbl::after { content:''; flex:1; height:1px; background:#1c2333; }
.signal-card {
    border-radius:8px; padding:12px 14px;
    font-family:'JetBrains Mono',monospace; font-size:0.78rem; margin:6px 0;
}
.signal-call { background:#0d2b1e; border:1px solid #33FF9966; }
.signal-put  { background:#2b0d0d; border:1px solid #FF4D4D66; }
.signal-none { background:#111722; border:1px solid #1c2333; color:#6b7785; }
div[data-testid="stButton"] > button {
    background:#0d1e33; border:1px solid #3BA7FF; color:#3BA7FF;
    font-family:'JetBrains Mono',monospace; font-size:0.75rem;
    padding:5px 12px; border-radius:5px; letter-spacing:1px;
}
div[data-testid="stButton"] > button:hover { background:#3BA7FF; color:#060a0f; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────────────────────────
def init_state():
    ss = st.session_state
    if "initialized" in ss:
        return
    ss.initialized     = True
    ss.capital         = float(ACCOUNT_BASE)
    ss.core_pnl        = 0.0
    ss.daily_pnl       = 0.0
    ss.locked          = False
    ss.last_fetch      = None
    ss.market_data     = {}   # { symbol: {spot, vix, adx, pcr, slope, vol, regime, confidence} }
    # ss.signals stores the inner signal dict (or None) keyed by symbol
    ss.signals         = {}   # { symbol: signal_dict | None }
    ss.signal_reasons  = {}   # { symbol: reason_str }
    ss.open_trades     = []
    ss.closed_trades   = []
    ss.trade_log       = []
    ss.regime_history  = {s: [] for s in SYMBOLS}
    ss.pnl_curve       = []
    ss.validation      = {
        "regime_flips":      0,
        "sl_hits":           0,
        "target_hits":       0,
        "signals_fired":     0,
        "correct_direction": 0,
    }

init_state()
ss = st.session_state

# ─────────────────────────────────────────────────────────────
# MARKET PHASE
# ─────────────────────────────────────────────────────────────
def get_phase() -> str:
    if ss.locked:
        return "LOCKED"
    now = datetime.now(IST).time()
    if now < dtime(9, 15):  return "PRE_MARKET"
    if now < dtime(9, 45):  return "OPENING_FREEZE"
    if now < dtime(11, 30): return "ACTIVE"
    if now < dtime(13, 15): return "MIDDAY_FREEZE"
    if now < dtime(15, 20): return "ACTIVE_PM"
    if now < dtime(15, 30): return "CLOSING"
    return "CLOSED"

def can_trade(phase: str) -> bool:
    return phase in ("ACTIVE", "MIDDAY_FREEZE", "ACTIVE_PM") and not ss.locked

# ─────────────────────────────────────────────────────────────
# DATA FETCH — yfinance
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def fetch_candles(ticker: str, period: str = "2d", interval: str = "1m"):
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        df.index = df.index.tz_convert(IST)
        return df
    except Exception:
        return None

@st.cache_data(ttl=60)
def fetch_vix() -> float:
    try:
        df = yf.download(VIX_TICKER, period="1d", interval="1m",
                         progress=False, auto_adjust=True)
        if df.empty:
            return 14.0
        return float(df["Close"].iloc[-1].item())
    except Exception:
        return 14.0

# ─────────────────────────────────────────────────────────────
# SCREENER — NIFTY 50 UNIVERSE
# ─────────────────────────────────────────────────────────────
NIFTY50_STOCKS = {
    "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "HDFCBANK": "HDFCBANK.NS",
    "INFY": "INFY.NS", "ICICIBANK": "ICICIBANK.NS", "HINDUNILVR": "HINDUNILVR.NS",
    "SBIN": "SBIN.NS", "BHARTIARTL": "BHARTIARTL.NS", "KOTAKBANK": "KOTAKBANK.NS",
    "LT": "LT.NS", "HCLTECH": "HCLTECH.NS", "AXISBANK": "AXISBANK.NS",
    "ASIANPAINT": "ASIANPAINT.NS", "MARUTI": "MARUTI.NS", "SUNPHARMA": "SUNPHARMA.NS",
    "TITAN": "TITAN.NS", "ULTRACEMCO": "ULTRACEMCO.NS", "WIPRO": "WIPRO.NS",
    "ONGC": "ONGC.NS", "NTPC": "NTPC.NS", "POWERGRID": "POWERGRID.NS",
    "M&M": "M&M.NS", "BAJFINANCE": "BAJFINANCE.NS", "NESTLEIND": "NESTLEIND.NS",
    "JSWSTEEL": "JSWSTEEL.NS", "TATAMOTORS": "TATAMOTORS.NS", "TATASTEEL": "TATASTEEL.NS",
    "TECHM": "TECHM.NS", "ADANIENT": "ADANIENT.NS", "ADANIPORTS": "ADANIPORTS.NS",
    "COALINDIA": "COALINDIA.NS", "BAJAJ-AUTO": "BAJAJ-AUTO.NS", "GRASIM": "GRASIM.NS",
    "HEROMOTOCO": "HEROMOTOCO.NS", "DIVISLAB": "DIVISLAB.NS", "DRREDDY": "DRREDDY.NS",
    "CIPLA": "CIPLA.NS", "APOLLOHOSP": "APOLLOHOSP.NS", "EICHERMOT": "EICHERMOT.NS",
    "BPCL": "BPCL.NS", "TATACONSUM": "TATACONSUM.NS", "BRITANNIA": "BRITANNIA.NS",
    "SBILIFE": "SBILIFE.NS", "HDFCLIFE": "HDFCLIFE.NS", "INDUSINDBK": "INDUSINDBK.NS",
    "UPL": "UPL.NS", "SHRIRAMFIN": "SHRIRAMFIN.NS", "BAJAJFINSV": "BAJAJFINSV.NS",
    "HINDALCO": "HINDALCO.NS", "ITC": "ITC.NS",
}

@st.cache_data(ttl=300)   # refresh every 5 min — screener is heavier
def fetch_screener_data() -> pd.DataFrame:
    """
    Fetches 1-day OHLCV for all Nifty 50 stocks and computes:
    - Change %  (day return)
    - Volume ratio vs 20-day avg
    - RSI(14) on daily closes
    - Above/below 20-EMA
    - Simple regime tag (Trending / Ranging / Volatile)
    """
    rows = []
    tickers = list(NIFTY50_STOCKS.values())
    try:
        raw = yf.download(
            tickers, period="30d", interval="1d",
            progress=False, auto_adjust=True, group_by="ticker",
        )
    except Exception:
        return pd.DataFrame()

    for name, ticker in NIFTY50_STOCKS.items():
        try:
            if len(tickers) == 1:
                df = raw
            else:
                df = raw[ticker] if ticker in raw.columns.get_level_values(0) else None
            if df is None or df.empty or len(df) < 15:
                continue

            close  = df["Close"].squeeze().dropna()
            volume = df["Volume"].squeeze().dropna()

            ltp        = float(close.iloc[-1])
            prev_close = float(close.iloc[-2])
            chg_pct    = (ltp - prev_close) / prev_close * 100

            vol_ratio  = float(volume.iloc[-1] / volume.rolling(20).mean().iloc[-1] * 100)

            # RSI-14
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rs    = gain / (loss + 1e-9)
            rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

            # EMA position
            ema20      = close.ewm(span=20, adjust=False).mean()
            above_ema  = ltp > float(ema20.iloc[-1])
            ema_gap_pct = (ltp - float(ema20.iloc[-1])) / float(ema20.iloc[-1]) * 100

            # Simple regime tag
            ema_slope  = (float(ema20.iloc[-1]) - float(ema20.iloc[-3])) / float(ema20.iloc[-3]) * 100
            if abs(ema_slope) > 0.5 and vol_ratio > 120:
                regime_tag = "🟩 TRENDING"
            elif rsi > 70 or rsi < 30:
                regime_tag = "🟥 EXTREME"
            elif vol_ratio < 80:
                regime_tag = "🟦 RANGING"
            else:
                regime_tag = "🟨 WATCH"

            rows.append({
                "Stock":       name,
                "LTP":         round(ltp, 2),
                "Chg %":       round(chg_pct, 2),
                "RSI(14)":     round(rsi, 1),
                "Vol %":       round(vol_ratio, 0),
                "EMA Gap %":   round(ema_gap_pct, 2),
                "Above EMA":   "✅" if above_ema else "❌",
                "Regime":      regime_tag,
            })
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    df_out = pd.DataFrame(rows)
    df_out.sort_values("Chg %", ascending=False, inplace=True)
    df_out.reset_index(drop=True, inplace=True)
    return df_out

# ─────────────────────────────────────────────────────────────
# TECHNICAL INDICATORS
# ─────────────────────────────────────────────────────────────
def compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Average Directional Index from OHLC data."""
    try:
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()
        close = df["Close"].squeeze()

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        dm_plus  = high.diff()
        dm_minus = -low.diff()
        dm_plus  = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0), 0.0)
        dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0.0)

        atr   = tr.ewm(alpha=1 / period, adjust=False).mean()
        di_p  = 100 * dm_plus.ewm(alpha=1 / period, adjust=False).mean() / atr
        di_m  = 100 * dm_minus.ewm(alpha=1 / period, adjust=False).mean() / atr
        dx    = 100 * (di_p - di_m).abs() / (di_p + di_m + 1e-9)
        adx   = dx.ewm(alpha=1 / period, adjust=False).mean()
        return float(adx.iloc[-1].item())
    except Exception:
        return 20.0

def compute_ema_slope(df: pd.DataFrame, period: int = 20) -> float:
    """Slope of EMA normalised by price (returns small float, e.g. 0.0003)."""
    try:
        close = df["Close"].squeeze()
        ema   = close.ewm(span=period, adjust=False).mean()
        val   = (ema.iloc[-1] - ema.iloc[-2]) / ema.iloc[-2]
        return float(val.item() if hasattr(val, "item") else val)
    except Exception:
        return 0.0

def compute_volume_ratio(df: pd.DataFrame, period: int = 20) -> float:
    """Current bar volume as % of rolling average (100 = average)."""
    try:
        vol = df["Volume"].squeeze()
        avg = vol.rolling(period).mean()
        ratio = float(vol.iloc[-1].item() / avg.iloc[-1].item()) * 100
        return min(ratio, 500.0)
    except Exception:
        return 100.0

def compute_pcr_proxy(adx: float, vix: float) -> float:
    """
    Synthetic PCR proxy (real OI data not freely available in real-time).
    Higher VIX → more put buying → PCR rises.
    Higher ADX → trending → less protective put buying → PCR falls.
    Replace with real NSE options-chain OI data for production use.
    """
    base  = 1.0
    base += (vix - 14) * 0.02
    base -= (adx - 20) * 0.01
    return float(np.clip(base, 0.6, 1.6))

# ─────────────────────────────────────────────────────────────
# REGIME CLASSIFIER
# ─────────────────────────────────────────────────────────────
def classify_regime(vix: float, adx: float, pcr: float,
                    slope: float, vol: float) -> tuple[int, str]:
    r1 = vix < 12.5 and adx < 18 and 0.85 <= pcr <= 1.15
    r2 = adx > 25 and vol > 200 and vix > 14
    r3 = vix > 18 and adx < 20
    r4 = adx > 22 and vix < 15 and abs(slope) > 0.00015   # slope is normalised

    near = (
        abs(vix - 12.5) < 0.5 or abs(adx - 18) < 1.2
        or abs(adx - 25) < 1.2 or abs(vix - 18) < 0.5
    )
    active = [r for r, hit in zip([1, 2, 3, 4], [r1, r2, r3, r4]) if hit]

    if len(active) == 1:
        return active[0], ("Transitional" if near else "Confirmed")
    if len(active) > 1:
        for priority in [2, 3, 4, 1]:
            if priority in active:
                return priority, "Overlap"

    # Fallback heuristic
    fallback = 4 if adx >= 22 else (3 if vix > 15 else 1)
    return fallback, "Heuristic"

# ─────────────────────────────────────────────────────────────
# SIGNAL GENERATOR
# ─────────────────────────────────────────────────────────────
def generate_signal(
    symbol: str,
    spot: float,
    regime: int,
    adx: float,
    vix: float,
    pcr: float,
    slope: float,
    vol: float,
    phase: str,
) -> dict:
    """
    Returns {"signal": dict | None, "reason": str}.

    signal dict keys: symbol, direction, strike, sl_points,
                      regime, spot_entry, ts, reasoning
    """
    if not can_trade(phase):
        return {"signal": None, "reason": "Market phase inactive or locked."}

    step = 100 if symbol == "BANKNIFTY" else 50
    atm  = round(spot / step) * step

    direction  = None
    strike     = None
    sl_points  = None
    reasoning  = ""

    # ── Trend strategies ──────────────────────────────────────
    if regime == 2 and vol > 150 and adx > 25:
        direction = "CALL" if slope > 0 else "PUT"
        strike    = atm + (step if direction == "CALL" else -step)
        sl_points = max(round(spot * 0.0035 / LOT_SIZE[symbol], 1), 15.0)
        reasoning = (
            f"R2 Momentum ({symbol}): Vol {vol:.0f}%, ADX {adx:.1f}. "
            f"Trade: {direction}"
        )

    elif regime == 4 and abs(slope) > 0.0001:
        direction = "CALL" if slope > 0 else "PUT"
        strike    = atm
        sl_points = max(round(spot * 0.002 / LOT_SIZE[symbol], 1), 12.0)
        reasoning = (
            f"R4 Quiet Trend ({symbol}): Slope {slope:+.5f}. Trade: {direction}"
        )

    # ── Mean-reversion strategies ─────────────────────────────
    elif regime == 1 and abs(slope) > 0.00005:
        direction = "CALL" if slope < 0 else "PUT"
        strike    = atm + (step if direction == "CALL" else -step)
        sl_points = 8.0
        reasoning = (
            f"R1 Range ({symbol}): Bounce at support/resistance. Trade: {direction}"
        )

    elif regime == 3 and abs(slope) > 0.0002:
        direction = "CALL" if slope < 0 else "PUT"
        strike    = atm + (step if direction == "CALL" else -step)
        sl_points = 12.0
        reasoning = (
            f"R3 Volatile ({symbol}): Mean reversion at extreme. Trade: {direction}"
        )

    if direction:
        return {
            "signal": {
                "symbol":     symbol,
                "direction":  direction,
                "strike":     strike,
                "sl_points":  sl_points,
                "regime":     regime,
                "spot_entry": spot,
                "ts":         datetime.now(IST).strftime("%H:%M:%S"),
                "reasoning":  reasoning,   # ← stored on signal dict, not outer dict
            },
            "reason": reasoning,
        }

    return {
        "signal": None,
        "reason": f"No trade: {symbol} in R{regime} — conditions not met.",
    }

# ─────────────────────────────────────────────────────────────
# POSITION SIZING
# ─────────────────────────────────────────────────────────────
def compute_size(symbol: str, sl_pts: float) -> tuple[int, float, bool]:
    """Returns (lots, actual_risk_₹, forced_minimum)."""
    lot       = LOT_SIZE[symbol]
    total_pts = sl_pts + SLIPPAGE
    lots      = math.floor(MAX_TRADE_RISK / (total_pts * lot))
    forced    = False

    if lots < 1:
        if (total_pts * lot) <= MAX_TRADE_RISK:
            lots, forced = 1, True
        else:
            lots = 0

    actual_risk = lots * total_pts * lot
    return lots, actual_risk, forced

# ─────────────────────────────────────────────────────────────
# PAPER TRADE EXECUTION
# ─────────────────────────────────────────────────────────────
def paper_enter(signal: dict, lots: int, actual_risk: float,
                entry_premium: float | None = None) -> None:
    """
    Open a paper trade from a signal dict.

    Entry premium is estimated as ~0.4% of spot (typical ATM index option).
    Replace with real options LTP from NSE options-chain API for production.
    """
    spot       = signal["spot_entry"]
    ep         = entry_premium or round(spot * 0.004, 1)
    sl_premium = round(ep - signal["sl_points"], 1)
    target     = round(ep + signal["sl_points"] * 2.0, 1)   # 2:1 RR

    trade = {
        "id":           len(ss.closed_trades) + len(ss.open_trades) + 1,
        "symbol":       signal["symbol"],
        "direction":    signal["direction"],
        "strike":       signal["strike"],
        "regime":       signal["regime"],
        "entry_time":   signal["ts"],
        "entry_spot":   signal["spot_entry"],
        "entry_prem":   ep,
        "sl_prem":      sl_premium,
        "sl_points":    signal["sl_points"],
        "target_prem":  target,
        "lots":         lots,
        "actual_risk":  actual_risk,
        "current_prem": ep,
        "pnl":          0.0,
        "status":       "OPEN",
        "reasoning":    signal["reasoning"],   # ← correctly taken from signal dict
        "exit_reason":  None,
        "exit_time":    None,
        "exit_prem":    None,
    }
    ss.open_trades.append(trade)
    ss.validation["signals_fired"] += 1
    log_event(
        f"ENTER {signal['direction']} {signal['symbol']} {signal['strike']} "
        f"@ ₹{ep} · SL ₹{sl_premium} · Target ₹{target} · {lots} lot(s)"
    )

def paper_exit(trade: dict, exit_premium: float, reason: str) -> None:
    lot  = LOT_SIZE[trade["symbol"]]
    pnl  = (exit_premium - trade["entry_prem"]) * trade["lots"] * lot

    trade.update({
        "current_prem": exit_premium,
        "pnl":          pnl,
        "status":       "CLOSED",
        "exit_reason":  reason,
        "exit_time":    datetime.now(IST).strftime("%H:%M:%S"),
        "exit_prem":    exit_premium,
    })

    ss.core_pnl  += pnl
    ss.daily_pnl += pnl
    ss.capital   += pnl
    ss.closed_trades.append(trade)
    ss.pnl_curve.append({"ts": trade["exit_time"], "pnl": ss.core_pnl})

    # ── Validation counters (counted here only, not in update_open_trades) ──
    if reason == "SL":
        ss.validation["sl_hits"] += 1
    elif reason == "TARGET":
        ss.validation["target_hits"] += 1

    if ss.core_pnl <= -MAX_DAILY_LOSS:
        ss.locked = True

    log_event(
        f"EXIT {trade['direction']} {trade['symbol']} {trade['strike']} "
        f"@ ₹{exit_premium} · PnL {fmt_pnl(pnl)} · Reason: {reason}"
    )

def update_open_trades(symbol: str, current_spot: float) -> None:
    """
    Simulate option-premium movement proportional to spot move.
    Delta approximation: 0.5 for ATM options.
    Replace with real options LTP from NSE options-chain API for production.
    """
    to_close: list[tuple[dict, float, str]] = []

    for trade in ss.open_trades:
        if trade["symbol"] != symbol:
            continue

        delta          = 0.5
        spot_move      = current_spot - trade["entry_spot"]
        direction_mult = 1 if trade["direction"] == "CALL" else -1
        prem_move      = direction_mult * delta * spot_move / LOT_SIZE[symbol]
        current_p      = max(round(trade["entry_prem"] + prem_move, 1), 0.1)

        trade["current_prem"] = current_p
        trade["pnl"] = (current_p - trade["entry_prem"]) * trade["lots"] * LOT_SIZE[symbol]

        if current_p <= trade["sl_prem"]:
            to_close.append((trade, trade["sl_prem"], "SL"))
        elif current_p >= trade["target_prem"]:
            to_close.append((trade, trade["target_prem"], "TARGET"))

    # Close outside the loop to avoid mutating the list while iterating
    for trade, exit_p, reason in to_close:
        ss.open_trades.remove(trade)
        paper_exit(trade, exit_p, reason)   # paper_exit handles validation counters

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def log_event(msg: str) -> None:
    ts = datetime.now(IST).strftime("%H:%M:%S")
    ss.trade_log.append(f"[{ts}] {msg}")
    ss.trade_log = ss.trade_log[-100:]

def fmt_pnl(v: float) -> str:
    return f"+₹{abs(v):,.0f}" if v >= 0 else f"-₹{abs(v):,.0f}"

# ─────────────────────────────────────────────────────────────
# MAIN FETCH + PROCESS CYCLE
# ─────────────────────────────────────────────────────────────
def run_cycle() -> None:
    """Called every refresh. Fetches data, classifies regimes, generates signals."""
    phase = get_phase()
    vix   = fetch_vix()

    for symbol, ticker in SYMBOLS.items():
        df = fetch_candles(ticker, period="2d", interval="1m")
        if df is None or len(df) < 21:
            continue

        spot  = float(df["Close"].iloc[-1].item())   # fixed: was `spot = spot = ...`
        adx   = compute_adx(df)
        slope = compute_ema_slope(df)
        vol   = compute_volume_ratio(df)
        pcr   = compute_pcr_proxy(adx, vix)

        regime_id, confidence = classify_regime(vix, adx, pcr, slope, vol)

        # Track regime history for validation
        history = ss.regime_history[symbol]
        if history and history[-1]["regime"] != regime_id:
            ss.validation["regime_flips"] += 1
        history.append({
            "ts":     datetime.now(IST).strftime("%H:%M:%S"),
            "regime": regime_id,
            "vix":    vix,
            "adx":    adx,
            "pcr":    pcr,
            "slope":  slope,
            "vol":    vol,
        })
        ss.regime_history[symbol] = history[-500:]

        ss.market_data[symbol] = {
            "spot":       spot,
            "vix":        vix,
            "adx":        adx,
            "pcr":        pcr,
            "slope":      slope,
            "vol":        vol,
            "regime":     regime_id,
            "confidence": confidence,
        }

        # Update existing open trades for this symbol
        update_open_trades(symbol, spot)

        # Generate new signal only if no open trade for this symbol
        already_open = any(t["symbol"] == symbol for t in ss.open_trades)
        if not already_open:
            result = generate_signal(
                symbol, spot, regime_id, adx, vix, pcr, slope, vol, phase
            )
            signal = result["signal"]   # inner dict or None
            reason = result["reason"]   # human-readable reason string

            ss.signals[symbol]       = signal   # store only the signal dict (or None)
            ss.signal_reasons[symbol] = reason

            if signal is not None:
                lots, actual_risk, forced = compute_size(symbol, signal["sl_points"])
                if lots > 0 and actual_risk <= MAX_TRADE_RISK:
                    paper_enter(signal, lots, actual_risk)
        else:
            ss.signals[symbol]        = None
            ss.signal_reasons[symbol] = f"Trade already open for {symbol}."

    ss.last_fetch = datetime.now(IST).strftime("%H:%M:%S")

# ─────────────────────────────────────────────────────────────
# ══════════  DASHBOARD RENDER  ══════════
# ─────────────────────────────────────────────────────────────
phase   = get_phase()
phase_m = PHASE_META[phase]
now_ist = datetime.now(IST).strftime("%d %b %Y  %H:%M:%S IST")

# ── Header ───────────────────────────────────────────────────
st.markdown(f"""
<div style="background:#080c12;border-bottom:1px solid #1c2333;
     padding:10px 4px;margin-bottom:14px;display:flex;
     align-items:center;justify-content:space-between;">
  <div>
    <span style="font-family:'JetBrains Mono',monospace;font-size:1.2rem;
          font-weight:700;color:#e6edf3;letter-spacing:2px;">📊 SYSTEM 1818</span>
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;
          color:#6b7785;margin-left:12px;letter-spacing:1px;">
      PAPER TRADE ENGINE · LIVE NSE
    </span>
  </div>
  <div style="display:flex;align-items:center;gap:12px;">
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#6b7785;">
      {now_ist}
    </span>
    <span style="background:{phase_m['color']}22;border:1px solid {phase_m['color']};
          color:{phase_m['color']};padding:3px 10px;border-radius:4px;
          font-family:'JetBrains Mono',monospace;font-size:0.68rem;font-weight:700;">
      {phase_m['label']}
    </span>
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.65rem;
          color:#33FF99;border:1px solid #33FF9944;padding:2px 8px;border-radius:3px;">
      ● PAPER ONLY
    </span>
  </div>
</div>
""", unsafe_allow_html=True)

if ss.locked:
    st.error("🛑 DAILY LOSS CIRCUIT BREAKER TRIPPED — Paper Engine Halted. Reset to continue.")

# ── Controls ─────────────────────────────────────────────────
ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1, 1, 1, 2])
with ctrl1:
    if st.button("▶ Refresh Now"):
        run_cycle()
        st.rerun()
with ctrl2:
    auto = st.checkbox("⚡ Auto (1-min)", value=False)
with ctrl3:
    if st.button("🔄 Reset All"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
with ctrl4:
    if ss.last_fetch:
        st.markdown(
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.72rem;'
            f'color:#6b7785;">Last fetch: {ss.last_fetch} · '
            f'{len(ss.closed_trades)} trades closed · {len(ss.open_trades)} open</span>',
            unsafe_allow_html=True,
        )

# Run once on first load
if not ss.market_data:
    run_cycle()

# ── Account row ───────────────────────────────────────────────
st.markdown('<div class="section-lbl">Paper Account</div>', unsafe_allow_html=True)
a1, a2, a3, a4, a5 = st.columns(5)
with a1: st.metric("Starting Capital", f"₹{ACCOUNT_BASE:,.0f}")
with a2: st.metric("Current Capital",  f"₹{ss.capital:,.0f}", f"{ss.capital - ACCOUNT_BASE:+,.0f}")
with a3: st.metric("Total Paper PnL",  f"₹{ss.core_pnl:+,.0f}")
with a4: st.metric("Open Trades",      len(ss.open_trades))
with a5: st.metric("Closed Trades",    len(ss.closed_trades))

loss_pct = max(0.0, -ss.core_pnl) / MAX_DAILY_LOSS
bar_color = "#FF4D4D" if loss_pct > 0.7 else ("#FFC93B" if loss_pct > 0.4 else "#33FF99")
st.markdown(f"""
<div style="margin:6px 0 10px;">
  <div style="display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;
       font-size:0.62rem;color:#6b7785;margin-bottom:3px;">
    <span>DAILY LOSS METER</span>
    <span>{loss_pct * 100:.1f}% of ₹{MAX_DAILY_LOSS:,} breaker</span>
  </div>
  <div style="background:#1c2333;border-radius:3px;height:5px;">
    <div style="width:{min(loss_pct * 100, 100):.1f}%;background:{bar_color};
         height:100%;border-radius:3px;transition:width 0.5s;"></div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── TradingView Charts ────────────────────────────────────────
st.markdown('<div class="section-lbl">TradingView Live Charts</div>', unsafe_allow_html=True)

tv_interval_map = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "1h": "60", "1D": "D"}
tc1, tc2 = st.columns([3, 1])
with tc2:
    tv_interval = st.selectbox(
        "Interval", list(tv_interval_map.keys()), index=2, label_visibility="collapsed"
    )
iv = tv_interval_map[tv_interval]

chart_col1, chart_col2 = st.columns(2)

NIFTY_TV_HTML = f"""
<div id="tv_nifty" style="border:1px solid #1c2333;border-radius:8px;overflow:hidden;">
<div class="tradingview-widget-container" style="height:420px;width:100%;">
  <div class="tradingview-widget-container__widget" style="height:100%;width:100%;"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
  {{
    "autosize": true,
    "symbol": "NSE:NIFTY",
    "interval": "{iv}",
    "timezone": "Asia/Kolkata",
    "theme": "dark",
    "style": "1",
    "locale": "en",
    "backgroundColor": "#060a0f",
    "gridColor": "#1c2333",
    "hide_top_toolbar": false,
    "hide_legend": false,
    "save_image": false,
    "studies": ["RSI@tv-basicstudies", "MAExp@tv-basicstudies", "Volume@tv-basicstudies"],
    "show_popup_button": false
  }}
  </script>
</div>
</div>
"""

BNF_TV_HTML = f"""
<div id="tv_bnf" style="border:1px solid #1c2333;border-radius:8px;overflow:hidden;">
<div class="tradingview-widget-container" style="height:420px;width:100%;">
  <div class="tradingview-widget-container__widget" style="height:100%;width:100%;"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
  {{
    "autosize": true,
    "symbol": "NSE:BANKNIFTY",
    "interval": "{iv}",
    "timezone": "Asia/Kolkata",
    "theme": "dark",
    "style": "1",
    "locale": "en",
    "backgroundColor": "#060a0f",
    "gridColor": "#1c2333",
    "hide_top_toolbar": false,
    "hide_legend": false,
    "save_image": false,
    "studies": ["RSI@tv-basicstudies", "MAExp@tv-basicstudies", "Volume@tv-basicstudies"],
    "show_popup_button": false
  }}
  </script>
</div>
</div>
"""

with chart_col1:
    st.markdown(
        '<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.68rem;'
        'color:#3BA7FF;letter-spacing:2px;margin-bottom:6px;">NIFTY 50</div>',
        unsafe_allow_html=True,
    )
    components.html(NIFTY_TV_HTML, height=430, scrolling=False)

with chart_col2:
    st.markdown(
        '<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.68rem;'
        'color:#3BA7FF;letter-spacing:2px;margin-bottom:6px;">BANK NIFTY</div>',
        unsafe_allow_html=True,
    )
    components.html(BNF_TV_HTML, height=430, scrolling=False)

# ── Live Market Matrix ────────────────────────────────────────
st.markdown('<div class="section-lbl">Live Market Matrix</div>', unsafe_allow_html=True)
if ss.market_data:
    for symbol, md in ss.market_data.items():
        rm = REGIME_META[md["regime"]]
        icon = {"1": "🟦", "2": "🟩", "3": "🟥", "4": "🟨"}.get(str(md["regime"]), "⬜")
        with st.expander(
            f"{icon}  {symbol}  ·  ₹{md['spot']:,.2f}  ·  "
            f"Regime {md['regime']}: {rm['name']}  [{md['confidence']}]",
            expanded=True,
        ):
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            with m1: st.metric("Spot",         f"₹{md['spot']:,.2f}")
            with m2: st.metric("India VIX",    f"{md['vix']:.2f}")
            with m3: st.metric("ADX",          f"{md['adx']:.2f}")
            with m4: st.metric("PCR (proxy)",  f"{md['pcr']:.3f}")
            with m5: st.metric("EMA Slope",    f"{md['slope']:+.5f}")
            with m6: st.metric("Volume %",     f"{md['vol']:.0f}%")
            st.markdown(f"""
            <div style="background:{rm['bg']};border:1px solid {rm['color']}44;border-radius:6px;
                 padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:0.75rem;
                 color:{rm['color']};margin-top:8px;">
              <b>Regime {md['regime']} — {rm['name']}</b> · {rm['desc']}
            </div>""", unsafe_allow_html=True)
else:
    st.info("No market data yet — click ▶ Refresh Now or wait for auto-refresh.")

# ── Signals ───────────────────────────────────────────────────
st.markdown('<div class="section-lbl">Current Signals</div>', unsafe_allow_html=True)
sig_cols = st.columns(len(SYMBOLS))
for i, symbol in enumerate(SYMBOLS):
    sig    = ss.signals.get(symbol)       # inner signal dict or None
    reason = ss.signal_reasons.get(symbol, "")
    with sig_cols[i]:
        if sig is not None:
            dc = "#33FF99" if sig["direction"] == "CALL" else "#FF4D4D"
            lots, actual_risk, _ = compute_size(symbol, sig["sl_points"])
            st.markdown(f"""
            <div class="signal-card {'signal-call' if sig['direction'] == 'CALL' else 'signal-put'}">
              <div style="font-size:1.1rem;font-weight:700;color:{dc};margin-bottom:8px;">
                {sig['direction']} · {symbol} {sig['strike']}
              </div>
              <div class="drow"><span class="dlbl">Regime</span>
                  <span class="dval">R{sig['regime']}</span></div>
              <div class="drow"><span class="dlbl">SL Points</span>
                  <span class="dval">{sig['sl_points']} pts</span></div>
              <div class="drow"><span class="dlbl">Lots</span>
                  <span class="dval">{lots}</span></div>
              <div class="drow"><span class="dlbl">Risk</span>
                  <span class="dval">₹{actual_risk:,.0f}</span></div>
              <div style="font-size:0.7rem;color:#8b949e;margin-top:8px;line-height:1.5;">
                {sig['reasoning']}
              </div>
              <div style="margin-top:8px;font-size:0.65rem;color:{dc};opacity:0.7;">
                @ {sig['ts']}
              </div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="signal-card signal-none">
              <div style="font-size:0.8rem;">⬜ {symbol}</div>
              <div style="font-size:0.72rem;margin-top:6px;">{reason or 'No signal — waiting for regime confirmation.'}</div>
            </div>""", unsafe_allow_html=True)

# ── Stock Screener ────────────────────────────────────────────
st.markdown('<div class="section-lbl">Nifty 50 Stock Screener</div>', unsafe_allow_html=True)

scr_tab1, scr_tab2 = st.tabs(["📊 Custom Screener (yfinance)", "🌐 TradingView Screener"])

with scr_tab1:
    sf1, sf2, sf3, sf4 = st.columns([1, 1, 1, 1])
    with sf1:
        scr_regime = st.multiselect(
            "Regime Filter",
            ["🟩 TRENDING", "🟦 RANGING", "🟥 EXTREME", "🟨 WATCH"],
            default=["🟩 TRENDING"],
        )
    with sf2:
        scr_ema = st.selectbox("EMA Position", ["All", "Above EMA ✅", "Below EMA ❌"])
    with sf3:
        scr_rsi_min, scr_rsi_max = st.slider("RSI Range", 0, 100, (40, 75))
    with sf4:
        scr_vol_min = st.slider("Min Volume %", 0, 300, 100)

    if st.button("🔍 Run Screener", key="run_screener"):
        with st.spinner("Fetching Nifty 50 data… (5–15s)"):
            fetch_screener_data.clear()
            scr_df = fetch_screener_data()
    else:
        scr_df = fetch_screener_data()

    if scr_df.empty:
        st.warning("Screener data unavailable — check network or try again.")
    else:
        # Apply filters
        filtered = scr_df.copy()
        if scr_regime:
            filtered = filtered[filtered["Regime"].isin(scr_regime)]
        if scr_ema == "Above EMA ✅":
            filtered = filtered[filtered["Above EMA"] == "✅"]
        elif scr_ema == "Below EMA ❌":
            filtered = filtered[filtered["Above EMA"] == "❌"]
        filtered = filtered[
            (filtered["RSI(14)"] >= scr_rsi_min) &
            (filtered["RSI(14)"] <= scr_rsi_max) &
            (filtered["Vol %"] >= scr_vol_min)
        ]

        # Colour-code Chg% column
        def style_chg(val):
            color = "#33FF99" if val > 0 else ("#FF4D4D" if val < 0 else "#8b949e")
            return f"color: {color}; font-weight: 600;"

        def style_rsi(val):
            if val >= 70: return "color:#FF4D4D;font-weight:600;"
            if val <= 30: return "color:#33FF99;font-weight:600;"
            return "color:#e6edf3;"

        styled = (
            filtered.style
            .applymap(style_chg, subset=["Chg %"])
            .applymap(style_rsi, subset=["RSI(14)"])
            .set_properties(**{"font-family": "JetBrains Mono, monospace", "font-size": "0.8rem"})
        )

        total_shown = len(filtered)
        st.caption(
            f"{total_shown} / {len(scr_df)} stocks match filters  ·  "
            f"Data cached 5 min · Click '🔍 Run Screener' to force refresh"
        )
        st.dataframe(styled, use_container_width=True, hide_index=True, height=420)

        # Movers summary
        if not scr_df.empty:
            top3    = scr_df.nlargest(3, "Chg %")[["Stock", "Chg %", "Regime"]]
            bottom3 = scr_df.nsmallest(3, "Chg %")[["Stock", "Chg %", "Regime"]]
            mv1, mv2 = st.columns(2)
            with mv1:
                st.markdown(
                    '<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.65rem;'
                    'color:#33FF99;letter-spacing:2px;margin-bottom:4px;">TOP GAINERS</div>',
                    unsafe_allow_html=True,
                )
                for _, row in top3.iterrows():
                    st.markdown(
                        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.8rem;'
                        f'padding:3px 0;color:#e6edf3;">'
                        f'<span style="color:#33FF99;font-weight:700;">{row["Stock"]}</span>'
                        f'  <span style="color:#33FF99;">+{row["Chg %"]:.2f}%</span>'
                        f'  <span style="color:#6b7785;font-size:0.7rem;">{row["Regime"]}</span></div>',
                        unsafe_allow_html=True,
                    )
            with mv2:
                st.markdown(
                    '<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.65rem;'
                    'color:#FF4D4D;letter-spacing:2px;margin-bottom:4px;">TOP LOSERS</div>',
                    unsafe_allow_html=True,
                )
                for _, row in bottom3.iterrows():
                    st.markdown(
                        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.8rem;'
                        f'padding:3px 0;color:#e6edf3;">'
                        f'<span style="color:#FF4D4D;font-weight:700;">{row["Stock"]}</span>'
                        f'  <span style="color:#FF4D4D;">{row["Chg %"]:.2f}%</span>'
                        f'  <span style="color:#6b7785;font-size:0.7rem;">{row["Regime"]}</span></div>',
                        unsafe_allow_html=True,
                    )

with scr_tab2:
    TV_SCREENER_HTML = """
    <div class="tradingview-widget-container" style="height:600px;width:100%;">
      <div class="tradingview-widget-container__widget" style="height:calc(100% - 32px);width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-screener.js" async>
      {
        "width": "100%",
        "height": 600,
        "defaultColumn": "overview",
        "defaultScreen": "most_capitalized",
        "market": "india",
        "showToolbar": true,
        "colorTheme": "dark",
        "locale": "en",
        "isTransparent": true
      }
      </script>
    </div>
    """
    components.html(TV_SCREENER_HTML, height=620, scrolling=False)

# ── Open Trades ───────────────────────────────────────────────
st.markdown('<div class="section-lbl">Open Paper Trades</div>', unsafe_allow_html=True)
if ss.open_trades:
    rows = []
    for t in ss.open_trades:
        rows.append({
            "Symbol":     t["symbol"],
            "Direction":  t["direction"],
            "Strike":     t["strike"],
            "Regime":     f"R{t['regime']}",
            "Entry Time": t["entry_time"],
            "Entry Prem": f"₹{t['entry_prem']}",
            "CMP":        f"₹{t['current_prem']}",
            "SL":         f"₹{t['sl_prem']}",
            "Target":     f"₹{t['target_prem']}",
            "Lots":       t["lots"],
            "Paper PnL":  fmt_pnl(t["pnl"]),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.markdown(
        '<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.78rem;'
        'color:#6b7785;padding:10px;">No open trades right now.</div>',
        unsafe_allow_html=True,
    )

# ── Validation Dashboard ──────────────────────────────────────
st.markdown('<div class="section-lbl">Validation Dashboard</div>', unsafe_allow_html=True)
total = len(ss.closed_trades)
wins  = sum(1 for t in ss.closed_trades if t["pnl"] > 0)
v1, v2, v3, v4, v5 = st.columns(5)
with v1: st.metric("Signals Fired",  ss.validation["signals_fired"])
with v2: st.metric("SL Hits",        ss.validation["sl_hits"])
with v3: st.metric("Target Hits",    ss.validation["target_hits"])
with v4: st.metric("Win Rate",       f"{wins / total * 100:.0f}%" if total else "—")
with v5: st.metric("Regime Flips",   ss.validation["regime_flips"])

if ss.closed_trades:
    rows = []
    for t in ss.closed_trades:
        rows.append({
            "Symbol":      t["symbol"],
            "Direction":   t["direction"],
            "Strike":      t["strike"],
            "Entry":       t["entry_time"],
            "Exit":        t["exit_time"],
            "Entry Prem":  f"₹{t['entry_prem']}",
            "Exit Prem":   f"₹{t['exit_prem']}",
            "Exit Reason": t["exit_reason"],
            "Lots":        t["lots"],
            "PnL":         fmt_pnl(t["pnl"]),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ── PnL Curve ─────────────────────────────────────────────────
if len(ss.pnl_curve) >= 2:
    st.markdown('<div class="section-lbl">Paper PnL Curve</div>', unsafe_allow_html=True)
    curve_df = pd.DataFrame(ss.pnl_curve)
    st.line_chart(curve_df.set_index("ts")["pnl"], use_container_width=True)

# ── Regime History ────────────────────────────────────────────
st.markdown('<div class="section-lbl">Regime History (Classifier Validation)</div>', unsafe_allow_html=True)
for symbol in SYMBOLS:
    hist = ss.regime_history.get(symbol, [])
    if hist:
        df_hist = pd.DataFrame(hist[-50:])
        st.caption(f"{symbol} — last {len(df_hist)} readings")
        st.dataframe(
            df_hist[["ts", "regime", "vix", "adx", "pcr", "slope", "vol"]].rename(
                columns={"ts": "Time", "regime": "Regime", "vix": "VIX",
                         "adx": "ADX", "pcr": "PCR", "slope": "Slope", "vol": "Vol%"}
            ),
            use_container_width=True,
            hide_index=True,
        )

# ── Activity Log ──────────────────────────────────────────────
st.markdown('<div class="section-lbl">Activity Log</div>', unsafe_allow_html=True)
if ss.trade_log:
    st.code("\n".join(reversed(ss.trade_log[-30:])), language=None)
else:
    st.markdown(
        '<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.75rem;'
        'color:#6b7785;">No activity yet.</div>',
        unsafe_allow_html=True,
    )

# ── Footer ────────────────────────────────────────────────────
st.markdown("""
<div style="margin-top:24px;padding:12px 0;border-top:1px solid #1c2333;
     font-family:'JetBrains Mono',monospace;font-size:0.62rem;
     color:#4b5563;text-align:center;line-height:2;">
  SYSTEM 1818 Paper Trade Engine · Data: yfinance (Yahoo Finance / NSE) · No real orders placed<br>
  PCR is a proxy estimate — replace with NSE options-chain OI data for production use<br>
  ⚠ Paper trading results do not guarantee live performance. All trading involves risk.
</div>
""", unsafe_allow_html=True)

# ── Auto Refresh ──────────────────────────────────────────────
if auto and phase in ("ACTIVE", "MIDDAY_FREEZE", "ACTIVE_PM", "OPENING_FREEZE"):
    time.sleep(60)
    run_cycle()
    st.rerun()
