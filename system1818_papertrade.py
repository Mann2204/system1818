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
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, date, time as dtime, timedelta
import math
import json
import time
import pytz

# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SYSTEM 1818 | Paper Trade Engine",
    layout="wide",
    initial_sidebar_state="collapsed",
    page_icon="📊"
)

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")
ACCOUNT_BASE   = 100_000
MAX_TRADE_RISK = 2_000
MAX_DAILY_LOSS = 4_000
SLIPPAGE       = 0.7
LOT_SIZE       = {"NIFTY": 65, "BANKNIFTY": 30}

SYMBOLS = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
}

# VIX proxy — use India VIX ticker
VIX_TICKER = "^INDIAVIX"

REGIME_META = {
    1: {"name": "Range Quiet",    "color": "#3BA7FF", "bg": "#0d1e33",
        "desc": "Accumulation/Distribution — price contained, wait for breakout"},
    2: {"name": "Trend Momentum", "color": "#33FF99", "bg": "#0d2b1e",
        "desc": "Institutional breakout — directional move confirmed, ride it"},
    3: {"name": "Range Volatile", "color": "#FF4D4D", "bg": "#2b0d0d",
        "desc": "Retail whipsaw trap — fakeout-prone, reduce size or skip"},
    4: {"name": "Trend Quiet",    "color": "#FFC93B", "bg": "#2b220d",
        "desc": "Low-vol directional grind along 20-EMA, tight SL"},
}

PHASE_META = {
    "PRE_MARKET":     {"label": "PRE-MARKET",    "color": "#3BA7FF"},
    "OPENING_FREEZE": {"label": "OPENING FREEZE","color": "#FFC93B"},
    "ACTIVE":         {"label": "ACTIVE",         "color": "#33FF99"},
    "MIDDAY_FREEZE":  {"label": "MID-DAY FREEZE","color": "#FF8C00"},
    "ACTIVE_PM":      {"label": "ACTIVE PM",      "color": "#33FF99"},
    "CLOSING":        {"label": "CLOSING",         "color": "#9B59B6"},
    "LOCKED":         {"label": "LOCKED 🛑",      "color": "#FF4D4D"},
    "CLOSED":         {"label": "MARKET CLOSED",  "color": "#6b7785"},
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
div[data-testid="stMetric"] { background:#0d1117; border:1px solid #1c2333; border-radius:8px; padding:12px 14px; }
div[data-testid="stMetricLabel"] { font-family:'JetBrains Mono',monospace; font-size:0.65rem; color:#6b7785; text-transform:uppercase; letter-spacing:1.5px; }
div[data-testid="stMetricValue"] { font-family:'JetBrains Mono',monospace; font-size:1.3rem; color:#e6edf3; }
.card { background:#0d1117; border:1px solid #1c2333; border-radius:8px; padding:14px 16px; }
.card-bl { border-left:3px solid #3BA7FF; }
.card-bg { border-left:3px solid #33FF99; }
.card-br { border-left:3px solid #FF4D4D; }
.card-ba { border-left:3px solid #FFC93B; }
.clbl { font-family:'JetBrains Mono',monospace; font-size:0.62rem; color:#6b7785; text-transform:uppercase; letter-spacing:2px; margin-bottom:8px; }
.mono { font-family:'JetBrains Mono',monospace; }
.drow { display:flex; justify-content:space-between; padding:4px 0; border-bottom:0.5px solid #0d1a26; font-family:'JetBrains Mono',monospace; font-size:0.8rem; }
.dlbl { color:#8b949e; }
.dval { color:#e6edf3; font-weight:600; }
.pos { color:#33FF99 !important; font-weight:600; }
.neg { color:#FF4D4D !important; font-weight:600; }
.warn { color:#FFC93B !important; font-weight:600; }
.section-lbl { font-family:'JetBrains Mono',monospace; font-size:0.62rem; color:#3BA7FF; text-transform:uppercase; letter-spacing:3px; margin:16px 0 8px 0; display:flex; align-items:center; gap:10px; }
.section-lbl::after { content:''; flex:1; height:1px; background:#1c2333; }
.tok-a { background:#0d2b1e; border:1px solid #33FF99; color:#33FF99; padding:5px 12px; border-radius:5px; font-family:'JetBrains Mono',monospace; font-size:0.82rem; font-weight:700; letter-spacing:1.5px; }
.tok-r { background:#2b0d0d; border:1px solid #FF4D4D; color:#FF4D4D; padding:5px 12px; border-radius:5px; font-family:'JetBrains Mono',monospace; font-size:0.82rem; font-weight:700; letter-spacing:1.5px; }
.signal-card { border-radius:8px; padding:12px 14px; font-family:'JetBrains Mono',monospace; font-size:0.78rem; margin:6px 0; }
.signal-call { background:#0d2b1e; border:1px solid #33FF9966; }
.signal-put  { background:#2b0d0d; border:1px solid #FF4D4D66; }
.signal-none { background:#111722; border:1px solid #1c2333; color:#6b7785; }
div[data-testid="stButton"] > button { background:#0d1e33; border:1px solid #3BA7FF; color:#3BA7FF; font-family:'JetBrains Mono',monospace; font-size:0.75rem; padding:5px 12px; border-radius:5px; letter-spacing:1px; }
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
    ss.initialized   = True
    ss.capital       = float(ACCOUNT_BASE)
    ss.core_pnl      = 0.0
    ss.daily_pnl     = 0.0
    ss.locked        = False
    ss.last_fetch    = None
    ss.market_data   = {}          # { symbol: {spot, vix, adx, pcr, slope, vol, candles} }
    ss.signals       = {}          # { symbol: {direction, strike, sl, regime, ts} }
    ss.open_trades   = []          # list of dicts
    ss.closed_trades = []          # list of dicts
    ss.trade_log     = []          # full log for display
    ss.regime_history = {s: [] for s in SYMBOLS}
    ss.pnl_curve     = []          # [{ts, pnl}]
    ss.validation    = {
        "regime_flips": 0,
        "sl_hits": 0,
        "target_hits": 0,
        "signals_fired": 0,
        "correct_direction": 0,
    }

init_state()
ss = st.session_state

# ─────────────────────────────────────────────────────────────
# MARKET PHASE
# ─────────────────────────────────────────────────────────────
def get_phase():
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

def can_trade(phase):
    return phase in ("ACTIVE", "ACTIVE_PM") and not ss.locked

# ─────────────────────────────────────────────────────────────
# DATA FETCH — yfinance (real NSE prices)
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)   # cache 60s so 1-min refresh doesn't hammer yfinance
def fetch_candles(ticker, period="2d", interval="1m"):
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        df.index = df.index.tz_convert(IST)
        return df
    except Exception as e:
        return None

@st.cache_data(ttl=60)
def fetch_vix():
    try:
        df = yf.download(VIX_TICKER, period="1d", interval="1m",
                         progress=False, auto_adjust=True)
        if df.empty:
            return 14.0
        return float(df["Close"].iloc[-1].item())
    except:
        return 14.0

# ─────────────────────────────────────────────────────────────
# TECHNICAL INDICATORS
# ─────────────────────────────────────────────────────────────
def compute_adx(df, period=14):
    """Average Directional Index from OHLC data."""
    try:
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()
        close = df["Close"].squeeze()

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs()
        ], axis=1).max(axis=1)

        dm_plus  = high.diff()
        dm_minus = -low.diff()
        dm_plus  = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0), 0)
        dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0)

        atr    = tr.ewm(alpha=1/period, adjust=False).mean()
        di_p   = 100 * dm_plus.ewm(alpha=1/period, adjust=False).mean() / atr
        di_m   = 100 * dm_minus.ewm(alpha=1/period, adjust=False).mean() / atr
        dx     = (100 * (di_p - di_m).abs() / (di_p + di_m + 1e-9))
        adx    = dx.ewm(alpha=1/period, adjust=False).mean()
        return float(adx.iloc[-1].item())
    except:
        return 20.0

def compute_ema_slope(df, period=20):
    """Slope of 20-EMA normalised by price."""
    try:
        close = df["Close"].squeeze()
        ema   = close.ewm(span=period, adjust=False).mean()
        slope = (ema.iloc[-1] - ema.iloc[-2]) / ema.iloc[-2]
        return float(slope.item() if hasattr(slope, 'item') else slope)
    except:
        return 0.0

def compute_volume_ratio(df, period=20):
    """Current bar volume vs rolling average."""
    try:
        vol = df["Volume"].squeeze()
        avg = vol.rolling(period).mean()
        ratio = float(vol.iloc[-1].item() / avg.iloc[-1].item()) * 100
        return min(ratio, 500.0)
    except:
        return 100.0

def compute_pcr_proxy(spot, adx, vix):
    """
    PCR isn't available free from NSE in real-time.
    We synthesise a proxy: when VIX is high and ADX low → put-heavy → PCR > 1.2
    When VIX low and ADX high → call-heavy → PCR < 0.9
    This is a simplification — replace with real OI data when available.
    """
    base = 1.0
    base += (vix - 14) * 0.02       # higher VIX → more puts
    base -= (adx - 20) * 0.01       # trending market → less put protection
    return float(np.clip(base, 0.6, 1.6))

# ─────────────────────────────────────────────────────────────
# REGIME CLASSIFIER
# ─────────────────────────────────────────────────────────────
def classify_regime(vix, adx, pcr, slope, vol):
    r1 = vix < 12.5 and adx < 18 and 0.85 <= pcr <= 1.15
    r2 = adx > 25 and vol > 200 and vix > 14
    r3 = vix > 18 and adx < 20
    r4 = adx > 22 and vix < 15 and abs(slope) > 0.15

    near = (abs(vix-12.5) < 0.5 or abs(adx-18) < 1.2 or
            abs(adx-25) < 1.2 or abs(vix-18) < 0.5)
    active = [r for r, hit in zip([1,2,3,4], [r1,r2,r3,r4]) if hit]

    if len(active) == 1:
        return active[0], ("Transitional" if near else "Confirmed")
    elif len(active) > 1:
        for p in [2, 3, 4, 1]:
            if p in active:
                return p, "Overlap"
    fallback = 4 if adx >= 22 else (3 if vix > 15 else 1)
    return fallback, "Heuristic"

# ─────────────────────────────────────────────────────────────
# SIGNAL GENERATOR (rule-based)
# ─────────────────────────────────────────────────────────────
def generate_signal(symbol, spot, regime, adx, vix, pcr, slope, vol, phase):
    """
    Generates trading signals based on regime-specific rules.
    Returns a dict with signal details or None.
    """
    # Verify trading phase
    if not can_trade(phase):
        return None

    direction = None
    sl_points = None
    reasoning = ""

    lot = LOT_SIZE[symbol]
    step = 50 if symbol == "NIFTY" else 100
    atm = round(spot / step) * step

    elif regime == 1:
        # Range Trading Logic: Sell at Resistance, Buy at Support
        # In a real setup, you would use Bollinger Bands or RSI
        # Here we use the price proximity to the mean as a proxy
        if slope < -0.05:  # Price hit the bottom of the range
            direction = "CALL"
            strike    = atm - step
            sl_points = max(round(spot * 0.0015 / lot, 1), 8.0)
            reasoning = f"R1 Range Trading: Price at support (Slope {slope:+.4f}). Buying {strike} CALL."
        elif slope > 0.05: # Price hit the top of the range
            direction = "PUT"
            strike    = atm + step
            sl_points = max(round(spot * 0.0015 / lot, 1), 8.0)
            reasoning = f"R1 Range Trading: Price at resistance (Slope {slope:+.4f}). Buying {strike} PUT."
            
    # RULE SET: Regime 2 (Trend Momentum)
    # CALL: Rising slope, high volume (>150%), strong trend (ADX > 25)
    # PUT: Falling slope, high volume (>150%), strong trend (ADX > 25)
    if regime == 2:
        if slope > 0 and vol > 150 and adx > 25:
            direction = "CALL"
            strike    = atm + step
            sl_points = max(round(spot * 0.0035 / lot, 1), 15.0)
            reasoning = f"R2 Momentum: Vol {vol:.0f}%, ADX {adx:.1f}, Slope {slope:+.4f}. Buying {strike} CALL."
        elif slope < 0 and vol > 150 and adx > 25:
            direction = "PUT"
            strike    = atm - step
            sl_points = max(round(spot * 0.0035 / lot, 1), 15.0)
            reasoning = f"R2 Momentum: Vol {vol:.0f}%, ADX {adx:.1f}, Slope {slope:+.4f}. Buying {strike} PUT."

elif regime == 3:
        # Mean Reversion Logic: Trade the reversal at extremes
        # We define extremes using the slope (velocity of price change)
        # If the slope is too steep, it suggests an exhaustion move
        if slope < -0.2:  # Oversold: Price dropped too fast
            direction = "CALL"
            strike    = atm - step
            sl_points = max(round(spot * 0.0025 / lot, 1), 10.0)
            reasoning = (f"R3 Mean Reversion: Extreme drop (Slope {slope:+.4f}). "
                         f"Market oversold, buying {strike} CALL.")
        elif slope > 0.2:  # Overbought: Price rose too fast
            direction = "PUT"
            strike    = atm + step
            sl_points = max(round(spot * 0.0025 / lot, 1), 10.0)
            reasoning = (f"R3 Mean Reversion: Extreme rise (Slope {slope:+.4f}). "
                         f"Market overbought, buying {strike} PUT.")

    # RULE SET: Regime 4 (Trend Quiet)
    # Logic: Lower volatility trend grinding with 20-EMA slope
    elif regime == 4:
        if slope > 0.1:
            direction = "CALL"
            strike    = atm
            sl_points = max(round(spot * 0.002 / lot, 1), 12.0)
            reasoning = f"R4 Quiet: Slope {slope:+.4f}, VIX {vix:.1f}. Buying ATM {strike} CALL."
        elif slope < -0.1:
            direction = "PUT"
            strike    = atm
            sl_points = max(round(spot * 0.002 / lot, 1), 12.0)
            reasoning = f"R4 Quiet: Slope {slope:+.4f}, VIX {vix:.1f}. Buying ATM {strike} PUT."

    return {
        "symbol":     symbol,
        "direction":  direction,
        "strike":     strike,
        "sl_points":  sl_points,
        "regime":     regime,
        "spot_entry": spot,
        "reasoning":  reasoning,
        "ts":         datetime.now(IST).strftime("%H:%M:%S"),
    }

# ─────────────────────────────────────────────────────────────
# POSITION SIZING
# ─────────────────────────────────────────────────────────────
def compute_size(symbol, sl_pts):
    lot       = LOT_SIZE[symbol]
    total_pts = sl_pts + SLIPPAGE
    lots      = math.floor(MAX_TRADE_RISK / (total_pts * lot))
    forced    = False
    if lots < 1:
        if (1 * total_pts * lot) <= MAX_TRADE_RISK:
            lots, forced = 1, True
        else:
            lots = 0
    actual_risk = lots * total_pts * lot
    return lots, actual_risk, forced

# ─────────────────────────────────────────────────────────────
# PAPER TRADE EXECUTION
# ─────────────────────────────────────────────────────────────
def paper_enter(signal, lots, actual_risk, entry_premium=None):
    """
    Entry premium is unknown without options chain — we estimate it as
    ATM premium ≈ 0.4% of spot (typical for liquid index options).
    Replace with real options LTP when options chain API available.
    """
    spot = signal["spot_entry"]
    ep   = entry_premium or round(spot * 0.004, 1)
    sl_premium = round(ep - signal["sl_points"], 1)
    target     = round(ep + signal["sl_points"] * 2, 1)   # 2:1 RR target

    trade = {
        "id":          len(ss.closed_trades) + len(ss.open_trades) + 1,
        "symbol":      signal["symbol"],
        "direction":   signal["direction"],
        "strike":      signal["strike"],
        "regime":      signal["regime"],
        "entry_time":  signal["ts"],
        "entry_spot":  signal["spot_entry"],
        "entry_prem":  ep,
        "sl_prem":     sl_premium,
        "sl_points":   signal["sl_points"],
        "target_prem": target,
        "lots":        lots,
        "actual_risk": actual_risk,
        "current_prem":ep,
        "pnl":         0.0,
        "status":      "OPEN",
        "reasoning":   signal["reasoning"],
        "exit_reason": None,
        "exit_time":   None,
        "exit_prem":   None,
    }
    ss.open_trades.append(trade)
    ss.validation["signals_fired"] += 1
    log_event(f"ENTER {signal['direction']} {signal['symbol']} {signal['strike']} "
              f"@ ₹{ep} · SL ₹{sl_premium} · Target ₹{target} · {lots} lot(s)")

def paper_exit(trade, exit_premium, reason):
    lot  = LOT_SIZE[trade["symbol"]]
    pnl  = (exit_premium - trade["entry_prem"]) * trade["lots"] * lot
    trade["current_prem"] = exit_premium
    trade["pnl"]          = pnl
    trade["status"]       = "CLOSED"
    trade["exit_reason"]  = reason
    trade["exit_time"]    = datetime.now(IST).strftime("%H:%M:%S")
    trade["exit_prem"]    = exit_premium

    ss.core_pnl  += pnl
    ss.daily_pnl += pnl
    ss.capital   += pnl
    ss.closed_trades.append(trade)
    ss.pnl_curve.append({"ts": trade["exit_time"], "pnl": ss.core_pnl})

    if reason == "SL":
        ss.validation["sl_hits"] += 1
    elif reason == "TARGET":
        ss.validation["target_hits"] += 1

    if ss.core_pnl <= -MAX_DAILY_LOSS:
        ss.locked = True

    log_event(f"EXIT {trade['direction']} {trade['symbol']} {trade['strike']} "
              f"@ ₹{exit_premium} · PnL {fmt_pnl(pnl)} · Reason: {reason}")

def update_open_trades(symbol, current_spot):
    """
    Simulate option premium movement proportional to spot move.
    Delta approximation: 0.5 for ATM options.
    Replace with real options LTP from options chain API when available.
    """
    to_close = []
    for trade in ss.open_trades:
        if trade["symbol"] != symbol:
            continue
        delta     = 0.5
        spot_move = current_spot - trade["entry_spot"]
        direction_mult = 1 if trade["direction"] == "CALL" else -1
        prem_move = direction_mult * delta * spot_move / LOT_SIZE[symbol]
        current_p = round(trade["entry_prem"] + prem_move, 1)
        current_p = max(current_p, 0.1)
        trade["current_prem"] = current_p
        trade["pnl"] = (current_p - trade["entry_prem"]) * trade["lots"] * LOT_SIZE[symbol]

        if current_p <= trade["sl_prem"]:
            to_close.append((trade, trade["sl_prem"], "SL"))
        elif current_p >= trade["target_prem"]:
            to_close.append((trade, trade["target_prem"], "TARGET"))

    for trade, ep, reason in to_close:
        ss.open_trades.remove(trade)
        paper_exit(trade, ep, reason)
        if reason == "SL":
            ss.validation["sl_hits"] += 1

def log_event(msg):
    ts = datetime.now(IST).strftime("%H:%M:%S")
    ss.trade_log.append(f"[{ts}] {msg}")
    ss.trade_log = ss.trade_log[-100:]     # keep last 100

def fmt_pnl(v):
    return f"+₹{abs(v):,.0f}" if v >= 0 else f"-₹{abs(v):,.0f}"

# ─────────────────────────────────────────────────────────────
# MAIN FETCH + PROCESS CYCLE
# ─────────────────────────────────────────────────────────────
def run_cycle():
    """Called every refresh. Fetches data, classifies, generates signals, updates trades."""
    phase = get_phase()
    vix   = fetch_vix()

    for symbol, ticker in SYMBOLS.items():
        df = fetch_candles(ticker, period="2d", interval="1m")
        if df is None or len(df) < 21:
            continue

        spot  = spot = float(df["Close"].iloc[-1].item())
        adx   = compute_adx(df)
        slope = compute_ema_slope(df)
        vol   = compute_volume_ratio(df)
        pcr   = compute_pcr_proxy(spot, adx, vix)

        regime_id, confidence = classify_regime(vix, adx, pcr, slope, vol)

        # Track regime history for validation
        history = ss.regime_history[symbol]
        if history and history[-1]["regime"] != regime_id:
            ss.validation["regime_flips"] += 1
        history.append({
            "ts": datetime.now(IST).strftime("%H:%M:%S"),
            "regime": regime_id, "vix": vix, "adx": adx,
            "pcr": pcr, "slope": slope, "vol": vol,
        })
        ss.regime_history[symbol] = history[-500:]

        ss.market_data[symbol] = {
            "spot": spot, "vix": vix, "adx": adx,
            "pcr": pcr, "slope": slope, "vol": vol,
            "regime": regime_id, "confidence": confidence,
            "df": df,
        }

        # Update existing open trades
        update_open_trades(symbol, spot)

        # Generate new signal only if no open trade for this symbol
        already_open = any(t["symbol"] == symbol for t in ss.open_trades)
        if not already_open:
            sig = generate_signal(symbol, spot, regime_id, adx, vix, pcr, slope, vol, phase)
            ss.signals[symbol] = sig
            if sig:
                lots, actual_risk, forced = compute_size(symbol, sig["sl_points"])
                if lots > 0 and actual_risk <= MAX_TRADE_RISK:
                    paper_enter(sig, lots, actual_risk)
        else:
            ss.signals[symbol] = None

    ss.last_fetch = datetime.now(IST).strftime("%H:%M:%S")

# ─────────────────────────────────────────────────────────────
# ══════════  DASHBOARD RENDER  ══════════
# ─────────────────────────────────────────────────────────────
phase    = get_phase()
phase_m  = PHASE_META[phase]
now_ist  = datetime.now(IST).strftime("%d %b %Y  %H:%M:%S IST")

# Header
st.markdown(f"""
<div style="background:#080c12;border-bottom:1px solid #1c2333;
     padding:10px 4px;margin-bottom:14px;display:flex;
     align-items:center;justify-content:space-between;">
  <div>
    <span style="font-family:'JetBrains Mono',monospace;font-size:1.2rem;
          font-weight:700;color:#e6edf3;letter-spacing:2px;">📊 SYSTEM 1818</span>
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;
          color:#6b7785;margin-left:12px;letter-spacing:1px;">PAPER TRADE ENGINE · LIVE NSE</span>
  </div>
  <div style="display:flex;align-items:center;gap:12px;">
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#6b7785;">{now_ist}</span>
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

# Controls
ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1,1,1,2])
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
        st.markdown(f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.72rem;color:#6b7785;">Last fetch: {ss.last_fetch} · {len(ss.closed_trades)} trades closed · {len(ss.open_trades)} open</span>', unsafe_allow_html=True)

# Run cycle on first load
if not ss.market_data:
    run_cycle()

# ── ACCOUNT ROW ──────────────────────────────────────────────
st.markdown('<div class="section-lbl">Paper Account</div>', unsafe_allow_html=True)
a1,a2,a3,a4,a5 = st.columns(5)
combined = ss.core_pnl
with a1: st.metric("Starting Capital", f"₹{ACCOUNT_BASE:,.0f}")
with a2: st.metric("Current Capital",  f"₹{ss.capital:,.0f}", f"{ss.capital-ACCOUNT_BASE:+,.0f}")
with a3: st.metric("Total Paper PnL",  f"₹{ss.core_pnl:+,.0f}")
with a4: st.metric("Open Trades",      len(ss.open_trades))
with a5: st.metric("Closed Trades",    len(ss.closed_trades))

loss_pct = max(0, -ss.core_pnl) / MAX_DAILY_LOSS
bc = "#FF4D4D" if loss_pct > 0.7 else ("#FFC93B" if loss_pct > 0.4 else "#33FF99")
st.markdown(f"""
<div style="margin:6px 0 10px;">
  <div style="display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;
       font-size:0.62rem;color:#6b7785;margin-bottom:3px;">
    <span>DAILY LOSS METER</span><span>{loss_pct*100:.1f}% of ₹4,000 breaker</span>
  </div>
  <div style="background:#1c2333;border-radius:3px;height:5px;">
    <div style="width:{min(loss_pct*100,100):.1f}%;background:{bc};height:100%;border-radius:3px;transition:width 0.5s;"></div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── LIVE MARKET DATA ─────────────────────────────────────────
st.markdown('<div class="section-lbl">Live Market Matrix</div>', unsafe_allow_html=True)

if ss.market_data:
    for symbol, md in ss.market_data.items():
        rm = REGIME_META[md["regime"]]
        with st.expander(f"{'🟩' if md['regime']==2 else '🟦' if md['regime']==1 else '🟥' if md['regime']==3 else '🟨'}  {symbol}  ·  ₹{md['spot']:,.2f}  ·  Regime {md['regime']}: {rm['name']}  [{md['confidence']}]", expanded=True):
            m1,m2,m3,m4,m5,m6 = st.columns(6)
            with m1: st.metric("Spot",        f"₹{md['spot']:,.2f}")
            with m2: st.metric("India VIX",   f"{md['vix']:.2f}")
            with m3: st.metric("ADX",         f"{md['adx']:.2f}")
            with m4: st.metric("PCR (proxy)", f"{md['pcr']:.3f}")
            with m5: st.metric("EMA Slope",   f"{md['slope']:+.4f}")
            with m6: st.metric("Volume %",    f"{md['vol']:.0f}%")
            st.markdown(f"""
            <div style="background:{rm['bg']};border:1px solid {rm['color']}44;border-radius:6px;
                 padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:0.75rem;
                 color:{rm['color']};margin-top:8px;">
              <b>Regime {md['regime']} — {rm['name']}</b> · {rm['desc']}
            </div>""", unsafe_allow_html=True)
else:
    st.info("No market data yet — click ▶ Refresh Now or wait for auto-refresh.")

# ── SIGNALS ──────────────────────────────────────────────────
st.markdown('<div class="section-lbl">Current Signals</div>', unsafe_allow_html=True)
sc = st.columns(len(SYMBOLS))
for i, (symbol, sig) in enumerate(ss.signals.items()):
    with sc[i]:
        if sig:
            dc = "#33FF99" if sig["direction"] == "CALL" else "#FF4D4D"
            lots, actual_risk, _ = compute_size(symbol, sig["sl_points"])
            st.markdown(f"""
            <div class="signal-card {'signal-call' if sig['direction']=='CALL' else 'signal-put'}">
              <div style="font-size:1.1rem;font-weight:700;color:{dc};margin-bottom:8px;">
                {sig['direction']} · {symbol} {sig['strike']}
              </div>
              <div class="drow"><span class="dlbl">Regime</span><span class="dval">R{sig['regime']}</span></div>
              <div class="drow"><span class="dlbl">SL Points</span><span class="dval">{sig['sl_points']} pts</span></div>
              <div class="drow"><span class="dlbl">Lots</span><span class="dval">{lots}</span></div>
              <div class="drow"><span class="dlbl">Risk</span><span class="dval">₹{actual_risk:,.0f}</span></div>
              <div style="font-size:0.7rem;color:#8b949e;margin-top:8px;line-height:1.5;">{sig['reasoning']}</div>
              <div style="margin-top:8px;font-size:0.65rem;color:{dc};opacity:0.7;">@ {sig['ts']}</div>
            </div>""", unsafe_allow_html=True)
        else:
            already_open = any(t["symbol"] == symbol for t in ss.open_trades)
            msg = f"Trade already open for {symbol}" if already_open else f"No signal — waiting for regime confirmation"
            st.markdown(f"""
            <div class="signal-card signal-none">
              <div style="font-size:0.8rem;">⬜ {symbol}</div>
              <div style="font-size:0.72rem;margin-top:6px;">{msg}</div>
            </div>""", unsafe_allow_html=True)

# ── OPEN TRADES ───────────────────────────────────────────────
st.markdown('<div class="section-lbl">Open Paper Trades</div>', unsafe_allow_html=True)
if ss.open_trades:
    rows = []
    for t in ss.open_trades:
        pnl_color = "🟢" if t["pnl"] >= 0 else "🔴"
        rows.append({
            "Symbol":    t["symbol"],
            "Direction": t["direction"],
            "Strike":    t["strike"],
            "Regime":    f"R{t['regime']}",
            "Entry Time":t["entry_time"],
            "Entry Prem":f"₹{t['entry_prem']}",
            "CMP":       f"₹{t['current_prem']}",
            "SL":        f"₹{t['sl_prem']}",
            "Target":    f"₹{t['target_prem']}",
            "Lots":      t["lots"],
            "Paper PnL": f"{pnl_color} ₹{t['pnl']:+,.0f}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.markdown('<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.78rem;color:#6b7785;padding:10px;">No open trades right now.</div>', unsafe_allow_html=True)

# ── CLOSED TRADES + VALIDATION ───────────────────────────────
st.markdown('<div class="section-lbl">Validation Dashboard</div>', unsafe_allow_html=True)
v1,v2,v3,v4,v5 = st.columns(5)
wins  = sum(1 for t in ss.closed_trades if t["pnl"] > 0)
total = len(ss.closed_trades)
with v1: st.metric("Signals Fired",   ss.validation["signals_fired"])
with v2: st.metric("SL Hits",         ss.validation["sl_hits"])
with v3: st.metric("Target Hits",     ss.validation["target_hits"])
with v4: st.metric("Win Rate",        f"{wins/total*100:.0f}%" if total else "—")
with v5: st.metric("Regime Flips",    ss.validation["regime_flips"])

if ss.closed_trades:
    rows = []
    for t in ss.closed_trades:
        rows.append({
            "Symbol":    t["symbol"],
            "Direction": t["direction"],
            "Strike":    t["strike"],
            "Entry":     t["entry_time"],
            "Exit":      t["exit_time"],
            "Entry Prem":f"₹{t['entry_prem']}",
            "Exit Prem": f"₹{t['exit_prem']}",
            "Exit Reason":t["exit_reason"],
            "Lots":      t["lots"],
            "PnL":       f"₹{t['pnl']:+,.0f}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# PnL Curve
if len(ss.pnl_curve) >= 2:
    st.markdown('<div class="section-lbl">Paper PnL Curve</div>', unsafe_allow_html=True)
    curve_df = pd.DataFrame(ss.pnl_curve)
    st.line_chart(curve_df.set_index("ts")["pnl"], use_container_width=True)

# ── REGIME HISTORY ────────────────────────────────────────────
st.markdown('<div class="section-lbl">Regime History (Classifier Validation)</div>', unsafe_allow_html=True)
for symbol in SYMBOLS:
    hist = ss.regime_history.get(symbol, [])
    if hist:
        df_hist = pd.DataFrame(hist[-50:])
        st.caption(f"{symbol} — last {len(df_hist)} readings")
        st.dataframe(df_hist[["ts","regime","vix","adx","pcr","slope","vol"]].rename(columns={"ts":"Time","regime":"Regime","vix":"VIX","adx":"ADX","pcr":"PCR","slope":"Slope","vol":"Vol%"}),
                     use_container_width=True, hide_index=True)

# ── ACTIVITY LOG ──────────────────────────────────────────────
st.markdown('<div class="section-lbl">Activity Log</div>', unsafe_allow_html=True)
if ss.trade_log:
    log_text = "\n".join(reversed(ss.trade_log[-30:]))
    st.code(log_text, language=None)
else:
    st.markdown('<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.75rem;color:#6b7785;">No activity yet.</div>', unsafe_allow_html=True)

# ── FOOTER ────────────────────────────────────────────────────
st.markdown("""
<div style="margin-top:24px;padding:12px 0;border-top:1px solid #1c2333;
     font-family:'JetBrains Mono',monospace;font-size:0.62rem;color:#4b5563;text-align:center;line-height:2;">
  SYSTEM 1818 Paper Trade Engine · Data: yfinance (Yahoo Finance / NSE) · No real orders placed<br>
  PCR is a proxy estimate — replace with NSE options chain OI data for production use<br>
  ⚠ Paper trading results do not guarantee live performance. All trading involves risk.
</div>
""", unsafe_allow_html=True)

# ── AUTO REFRESH ──────────────────────────────────────────────
if auto and phase in ("ACTIVE", "ACTIVE_PM", "OPENING_FREEZE"):
    time.sleep(60)
    run_cycle()
    st.rerun()
