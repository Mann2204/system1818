"""
╔══════════════════════════════════════════════════════════════╗
║   SYSTEM 1818 — Paper Trade Engine  v2                      ║
║   Live NSE prices via yfinance · Rule-based signals         ║
║   Includes: NIFTY/BANKNIFTY Options + Stock Futures Calls   ║
╚══════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, time as dtime, timedelta, date
import math
import time
import pytz
import json
import os

st.set_page_config(
    page_title="SYSTEM 1818 | Paper Trade Engine",
    layout="wide",
    initial_sidebar_state="collapsed",
    page_icon="📊",
)

IST            = pytz.timezone("Asia/Kolkata")
ACCOUNT_BASE   = 100_000
MAX_TRADE_RISK = 2_000
MAX_DAILY_LOSS = 4_000
SLIPPAGE       = 0.7

SYMBOLS = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
}

VIX_TICKER = "^INDIAVIX"

LOT_SIZE = {"NIFTY": 65, "BANKNIFTY": 30}

# ─────────────────────────────────────────────────────────────
# STOCK FUTURES UNIVERSE
# NSE F&O lot sizes (NSE/FAOP circular, update when revised)
# Signal: BUY (go long futures) or SELL (go short futures)
# ─────────────────────────────────────────────────────────────
FUTURES_STOCKS = {
    "RELIANCE":   {"ticker": "RELIANCE.NS", "lot": 250},
    "TCS":        {"ticker": "TCS.NS",      "lot": 150},
    "HDFCBANK":   {"ticker": "HDFCBANK.NS", "lot": 550},
    "INFY":       {"ticker": "INFY.NS",     "lot": 400},
    "ICICIBANK":  {"ticker": "ICICIBANK.NS","lot": 700},
    "SBIN":       {"ticker": "SBIN.NS",     "lot": 1500},
    "AXISBANK":   {"ticker": "AXISBANK.NS", "lot": 1200},
    "BAJFINANCE": {"ticker": "BAJFINANCE.NS","lot": 125},
    "WIPRO":      {"ticker": "WIPRO.NS",    "lot": 1500},
    "TATAMOTORS": {"ticker": "TATAMOTORS.NS","lot": 1425},
    "TATASTEEL":  {"ticker": "TATASTEEL.NS","lot": 5500},
    "KOTAKBANK":  {"ticker": "KOTAKBANK.NS","lot": 400},
    "LT":         {"ticker": "LT.NS",       "lot": 300},
    "MARUTI":     {"ticker": "MARUTI.NS",   "lot": 100},
    "SUNPHARMA":  {"ticker": "SUNPHARMA.NS","lot": 700},
    "ONGC":       {"ticker": "ONGC.NS",     "lot": 3850},
    "NTPC":       {"ticker": "NTPC.NS",     "lot": 4500},
    "ITC":        {"ticker": "ITC.NS",      "lot": 3200},
    "JSWSTEEL":   {"ticker": "JSWSTEEL.NS", "lot": 600},
    "ADANIENT":   {"ticker": "ADANIENT.NS", "lot": 250},
}

NSE_HOLIDAYS: set[date] = {
    date(2025, 1, 26), date(2025, 2, 26), date(2025, 3, 14),
    date(2025, 3, 31), date(2025, 4, 14), date(2025, 4, 18),
    date(2025, 5, 1),  date(2025, 8, 15), date(2025, 8, 27),
    date(2025, 10, 2), date(2025, 10, 24),date(2025, 11, 5),
    date(2025, 12, 25),
    date(2026, 1, 26), date(2026, 3, 20), date(2026, 4, 3),
    date(2026, 4, 14), date(2026, 5, 1),  date(2026, 8, 15),
    date(2026, 10, 2), date(2026, 10, 22),date(2026, 11, 11),
    date(2026, 11, 14),date(2026, 12, 25),
    date(2027, 1, 26), date(2027, 3, 10), date(2027, 3, 26),
    date(2027, 4, 14), date(2027, 5, 1),  date(2027, 8, 15),
    date(2027, 10, 2), date(2027, 12, 25),
}

def _is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in NSE_HOLIDAYS

def _last_tuesday_of_month(year: int, month: int) -> date:
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    days_back = (last_day.weekday() - 1) % 7
    return last_day - timedelta(days=days_back)

def _last_thursday_of_month(year: int, month: int) -> date:
    """Stock futures expire on last Thursday of the month."""
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    days_back = (last_day.weekday() - 3) % 7
    return last_day - timedelta(days=days_back)

def _nse_expiry_for_month(year: int, month: int) -> date:
    d = _last_tuesday_of_month(year, month)
    while not _is_trading_day(d):
        d -= timedelta(days=1)
    return d

def _stock_futures_expiry_for_month(year: int, month: int) -> date:
    """Stock futures: last Thursday of month, rolled back on holidays."""
    d = _last_thursday_of_month(year, month)
    while not _is_trading_day(d):
        d -= timedelta(days=1)
    return d

@st.cache_data(ttl=3600)
def get_expiry_cached(symbol: str) -> str:
    today = datetime.now(IST).date()
    now_t = datetime.now(IST).time()
    year, month = today.year, today.month
    for _ in range(3):
        exp_date = _nse_expiry_for_month(year, month)
        if exp_date > today:
            return exp_date.strftime("%d-%b-%y").upper()
        if exp_date == today and now_t < dtime(15, 30):
            return exp_date.strftime("%d-%b-%y").upper()
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return exp_date.strftime("%d-%b-%y").upper()

@st.cache_data(ttl=3600)
def get_stock_futures_expiry() -> str:
    """Nearest monthly expiry for stock futures (last Thursday)."""
    today = datetime.now(IST).date()
    now_t = datetime.now(IST).time()
    year, month = today.year, today.month
    for _ in range(3):
        exp_date = _stock_futures_expiry_for_month(year, month)
        if exp_date > today:
            return exp_date.strftime("%d-%b-%y").upper()
        if exp_date == today and now_t < dtime(15, 30):
            return exp_date.strftime("%d-%b-%y").upper()
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return exp_date.strftime("%d-%b-%y").upper()

def option_symbol_str(symbol: str, strike: int, direction: str) -> str:
    expiry   = get_expiry_cached(symbol)
    opt_type = "CE" if direction == "CALL" else "PE"
    return f"{symbol} {expiry} {strike} {opt_type}"

def futures_symbol_str(stock: str, direction: str) -> str:
    """e.g.  RELIANCE 29-JUL-26 FUT  BUY"""
    expiry = get_stock_futures_expiry()
    return f"{stock} {expiry} FUT  {direction}"

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def log_event(msg: str) -> None:
    _ss = st.session_state
    ts = datetime.now(IST).strftime("%H:%M:%S")
    if not hasattr(_ss, "trade_log"):
        _ss.trade_log = []
    _ss.trade_log.append(f"[{ts}] {msg}")
    _ss.trade_log = _ss.trade_log[-100:]

def fmt_pnl(v: float) -> str:
    return f"+₹{abs(v):,.0f}" if v >= 0 else f"-₹{abs(v):,.0f}"

SAVE_FILE = "system1818_state.json"

def _state_to_dict() -> dict:
    _s = st.session_state  # always use st.session_state directly — safe before ss alias
    return {
        "capital":               float(getattr(_s, "capital",               ACCOUNT_BASE)),
        "core_pnl":              float(getattr(_s, "core_pnl",              0.0)),
        "daily_pnl":             float(getattr(_s, "daily_pnl",             0.0)),
        "locked":                bool(getattr(_s,  "locked",                False)),
        "open_trades":           getattr(_s, "open_trades",                 []),
        "closed_trades":         getattr(_s, "closed_trades",               []),
        "trade_log":             getattr(_s, "trade_log",                   []),
        "pnl_curve":             getattr(_s, "pnl_curve",                   []),
        "validation":            getattr(_s, "validation", {
            "regime_flips": 0, "sl_hits": 0, "target_hits": 0,
            "signals_fired": 0, "correct_direction": 0,
        }),
        "futures_signals":       getattr(_s, "futures_signals",             {}),
        "futures_open_trades":   getattr(_s, "futures_open_trades",         []),
        "futures_closed_trades": getattr(_s, "futures_closed_trades",       []),
        "save_date":             datetime.now(IST).strftime("%Y-%m-%d"),
    }

def save_state() -> None:
    try:
        with open(SAVE_FILE, "w") as f:
            json.dump(_state_to_dict(), f, indent=2, default=str)
    except Exception:
        pass

def load_state() -> bool:
    if not os.path.exists(SAVE_FILE):
        return False
    try:
        with open(SAVE_FILE, "r") as f:
            data = json.load(f)
        _s = st.session_state   # use directly — ss alias not set yet when called from init_state
        today = datetime.now(IST).strftime("%Y-%m-%d")
        _s.capital              = float(data.get("capital",       ACCOUNT_BASE))
        _s.core_pnl             = float(data.get("core_pnl",      0.0))
        _s.locked               = bool(data.get("locked",         False))
        _s.open_trades          = data.get("open_trades",         [])
        _s.closed_trades        = data.get("closed_trades",       [])
        _s.trade_log            = data.get("trade_log",           [])
        _s.pnl_curve            = data.get("pnl_curve",           [])
        _s.validation           = data.get("validation", {
            "regime_flips": 0, "sl_hits": 0, "target_hits": 0,
            "signals_fired": 0, "correct_direction": 0,
        })
        # Futures state — always default to empty if missing (e.g. old save files)
        _s.futures_signals       = data.get("futures_signals",      {})
        _s.futures_open_trades   = data.get("futures_open_trades",  [])
        _s.futures_closed_trades = data.get("futures_closed_trades",[])
        # futures_market_data is never persisted — always starts empty each session
        if not hasattr(_s, "futures_market_data"):
            _s.futures_market_data = {}

        if data.get("save_date") != today:
            _s.daily_pnl = 0.0
            _s.locked    = False
            ts = datetime.now(IST).strftime("%H:%M:%S")
            _s.trade_log.append(f"[{ts}] New trading day — daily PnL reset.")
        else:
            _s.daily_pnl = float(data.get("daily_pnl", 0.0))
        return True
    except Exception:
        return False

REGIME_META = {
    1: {"name": "Range Quiet",     "color": "#3BA7FF", "bg": "#0d1e33",
        "desc": "Accumulation/Distribution — price contained, wait for breakout"},
    2: {"name": "Trend Momentum",  "color": "#33FF99", "bg": "#0d2b1e",
        "desc": "Institutional breakout — directional move confirmed, ride it"},
    3: {"name": "Range Volatile",  "color": "#FF4D4D", "bg": "#2b0d0d",
        "desc": "Retail whipsaw trap — fakeout-prone, reduce size or skip"},
    4: {"name": "Trend Quiet",     "color": "#FFC93B", "bg": "#2b220d",
        "desc": "Low-vol directional grind along 20-EMA, tight SL"},
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

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&display=swap');
.stApp { background:#060a0f; color:#c9d1d9; }
.block-container { padding:1rem 2rem 3rem 2rem; max-width:100%; }
#MainMenu, footer, header { visibility:hidden; }
div[data-testid="stMetric"] {
    background:#0d1117; border:1px solid #1c2333; border-radius:8px; padding:12px 14px;
}
div[data-testid="stMetricLabel"] {
    font-family:'JetBrains Mono',monospace; font-size:0.65rem;
    color:#6b7785; text-transform:uppercase; letter-spacing:1.5px;
}
div[data-testid="stMetricValue"] {
    font-family:'JetBrains Mono',monospace; font-size:1.3rem; color:#e6edf3;
}
.drow {
    display:flex; justify-content:space-between; padding:4px 0;
    border-bottom:0.5px solid #0d1a26;
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
.signal-card { border-radius:8px; padding:12px 14px; font-family:'JetBrains Mono',monospace; font-size:0.78rem; margin:6px 0; }
.signal-buy  { background:#0d2b1e; border:1px solid #33FF9966; }
.signal-sell { background:#2b0d0d; border:1px solid #FF4D4D66; }
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
# SESSION STATE
# ─────────────────────────────────────────────────────────────
def init_state():
    ss = st.session_state
    if "initialized" in ss:
        return
    ss.initialized           = True
    ss.capital               = float(ACCOUNT_BASE)
    ss.core_pnl              = 0.0
    ss.daily_pnl             = 0.0
    ss.locked                = False
    ss.last_fetch            = None
    ss.market_data           = {}
    ss.signals               = {}
    ss.signal_reasons        = {}
    ss.open_trades           = []
    ss.closed_trades         = []
    ss.trade_log             = []
    ss.regime_history        = {s: [] for s in SYMBOLS}
    ss.pnl_curve             = []
    ss.validation            = {
        "regime_flips": 0, "sl_hits": 0, "target_hits": 0,
        "signals_fired": 0, "correct_direction": 0,
    }
    # ── Stock Futures state ──────────────────────────────────
    ss.futures_signals       = {}   # {stock: {direction, entry, sl, target, reasoning, ts, lots}}
    ss.futures_market_data   = {}   # {stock: {price, adx, slope, vol, regime}}
    ss.futures_open_trades   = []
    ss.futures_closed_trades = []

    loaded = load_state()
    if not loaded:
        ts = datetime.now(IST).strftime("%H:%M:%S")
        ss.trade_log.append(f"[{ts}] No saved state found — starting fresh.")

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
# DATA FETCH
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

@st.cache_data(ttl=120)
def fetch_stock_candles_batch() -> dict:
    """
    Fetch 5-day 5-min candles for all futures stocks in one batch call.
    Returns {stock_name: DataFrame}.
    """
    tickers = [v["ticker"] for v in FUTURES_STOCKS.values()]
    result  = {}
    try:
        raw = yf.download(
            tickers, period="5d", interval="5m",
            progress=False, auto_adjust=True, group_by="ticker",
        )
    except Exception:
        return result

    names = list(FUTURES_STOCKS.keys())
    tkrs  = [FUTURES_STOCKS[n]["ticker"] for n in names]

    for name, ticker in zip(names, tkrs):
        try:
            if len(tickers) == 1:
                df = raw
            else:
                df = raw[ticker] if ticker in raw.columns.get_level_values(0) else None
            if df is None or df.empty or len(df) < 21:
                continue
            df = df.copy()
            df.index = df.index.tz_convert(IST)
            result[name] = df
        except Exception:
            continue
    return result

# ─────────────────────────────────────────────────────────────
# NIFTY 50 SCREENER (unchanged from original)
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

@st.cache_data(ttl=300)
def fetch_screener_data() -> pd.DataFrame:
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
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rs    = gain / (loss + 1e-9)
            rsi   = float((100 - 100 / (1 + rs)).iloc[-1])
            ema20      = close.ewm(span=20, adjust=False).mean()
            above_ema  = ltp > float(ema20.iloc[-1])
            ema_gap_pct = (ltp - float(ema20.iloc[-1])) / float(ema20.iloc[-1]) * 100
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
                "Stock":     name,
                "LTP":       round(ltp, 2),
                "Chg %":     round(chg_pct, 2),
                "RSI(14)":   round(rsi, 1),
                "Vol %":     round(vol_ratio, 0),
                "EMA Gap %": round(ema_gap_pct, 2),
                "Above EMA": "✅" if above_ema else "❌",
                "Regime":    regime_tag,
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
    try:
        close = df["Close"].squeeze()
        ema   = close.ewm(span=period, adjust=False).mean()
        val   = (ema.iloc[-1] - ema.iloc[-2]) / ema.iloc[-2]
        return float(val.item() if hasattr(val, "item") else val)
    except Exception:
        return 0.0

def compute_volume_ratio(df: pd.DataFrame, period: int = 20) -> float:
    try:
        vol = df["Volume"].squeeze()
        avg = vol.rolling(period).mean()
        ratio = float(vol.iloc[-1].item() / avg.iloc[-1].item()) * 100
        return min(ratio, 500.0)
    except Exception:
        return 100.0

def compute_rsi(df: pd.DataFrame, period: int = 14) -> float:
    try:
        close = df["Close"].squeeze().dropna()
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / (loss + 1e-9)
        rsi   = 100 - 100 / (1 + rs)
        return float(rsi.iloc[-1].item())
    except Exception:
        return 50.0

def compute_pcr_proxy(adx: float, vix: float) -> float:
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
    r4 = adx > 22 and vix < 15 and abs(slope) > 0.00015
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
    fallback = 4 if adx >= 22 else (3 if vix > 15 else 1)
    return fallback, "Heuristic"

# ─────────────────────────────────────────────────────────────
# INDEX OPTIONS SIGNAL
# ─────────────────────────────────────────────────────────────
def generate_signal(symbol, spot, regime, adx, vix, pcr, slope, vol, phase) -> dict:
    if not can_trade(phase):
        return {"signal": None, "reason": "Market phase inactive or locked."}
    step = 100 if symbol == "BANKNIFTY" else 50
    atm  = round(spot / step) * step
    direction = None; strike = None; sl_points = None; reasoning = ""

    if regime == 2 and vol > 150 and adx > 25:
        direction = "CALL" if slope > 0 else "PUT"
        strike    = atm + (step if direction == "CALL" else -step)
        sl_points = max(round(spot * 0.0035 / LOT_SIZE[symbol], 1), 15.0)
        reasoning = f"R2 Momentum ({symbol}): Vol {vol:.0f}%, ADX {adx:.1f}. Trade: {direction}"
    elif regime == 4 and abs(slope) > 0.0001:
        direction = "CALL" if slope > 0 else "PUT"
        strike    = atm
        sl_points = max(round(spot * 0.002 / LOT_SIZE[symbol], 1), 12.0)
        reasoning = f"R4 Quiet Trend ({symbol}): Slope {slope:+.5f}. Trade: {direction}"
    elif regime == 1 and abs(slope) > 0.00005:
        direction = "CALL" if slope < 0 else "PUT"
        strike    = atm + (step if direction == "CALL" else -step)
        sl_points = 8.0
        reasoning = f"R1 Range ({symbol}): Bounce at support/resistance. Trade: {direction}"
    elif regime == 3 and abs(slope) > 0.0002:
        direction = "CALL" if slope < 0 else "PUT"
        strike    = atm + (step if direction == "CALL" else -step)
        sl_points = 12.0
        reasoning = f"R3 Volatile ({symbol}): Mean reversion at extreme. Trade: {direction}"

    if direction:
        return {"signal": {"symbol": symbol, "direction": direction, "strike": strike,
                           "sl_points": sl_points, "regime": regime, "spot_entry": spot,
                           "ts": datetime.now(IST).strftime("%H:%M:%S"), "reasoning": reasoning},
                "reason": reasoning}
    return {"signal": None, "reason": f"No trade: {symbol} in R{regime} — conditions not met."}

# ─────────────────────────────────────────────────────────────
# STOCK FUTURES SIGNAL GENERATOR
# ─────────────────────────────────────────────────────────────
def generate_futures_signal(
    stock: str,
    price: float,
    adx: float,
    slope: float,
    vol: float,
    rsi: float,
    vix: float,
    phase: str,
) -> dict | None:
    """
    Returns a futures signal dict or None.

    Signal logic (5-min chart):
      BUY  — ADX > 22 AND slope > +0.00008 AND vol > 130 AND RSI 45-70
              (trending up with confirmation)
      SELL — ADX > 22 AND slope < -0.00008 AND vol > 130 AND RSI 30-55
              (trending down with confirmation)
      MOMENTUM BUY  — ADX > 28 AND vol > 200 AND RSI > 55  (strong breakout)
      MOMENTUM SELL — ADX > 28 AND vol > 200 AND RSI < 45  (strong breakdown)
      Mean-Reversion BUY  — RSI < 32 AND adx < 20 AND slope > -0.0001 (oversold bounce)
      Mean-Reversion SELL — RSI > 68 AND adx < 20 AND slope < +0.0001 (overbought reversal)

    SL = 0.5% of spot price (tight for futures)
    Target = 1.0% of spot price (1:2 R:R)
    """
    if not can_trade(phase):
        return None

    direction  = None
    reasoning  = ""
    sl_pct     = 0.005   # 0.5%
    tgt_pct    = 0.010   # 1.0%

    # Strong momentum breakout
    if adx > 28 and vol > 200:
        if rsi > 55 and slope > 0:
            direction = "BUY"
            reasoning = f"Momentum Breakout ↑: ADX {adx:.1f}, Vol {vol:.0f}%, RSI {rsi:.0f}"
        elif rsi < 45 and slope < 0:
            direction = "SELL"
            reasoning = f"Momentum Breakdown ↓: ADX {adx:.1f}, Vol {vol:.0f}%, RSI {rsi:.0f}"

    # Trend-following
    elif adx > 22 and vol > 130:
        if slope > 0.00008 and 45 <= rsi <= 70:
            direction = "BUY"
            reasoning = f"Trend Follow ↑: ADX {adx:.1f}, Slope {slope:+.5f}, RSI {rsi:.0f}"
        elif slope < -0.00008 and 30 <= rsi <= 55:
            direction = "SELL"
            reasoning = f"Trend Follow ↓: ADX {adx:.1f}, Slope {slope:+.5f}, RSI {rsi:.0f}"

    # Mean-reversion
    elif adx < 20:
        if rsi < 32 and slope > -0.0001:
            direction = "BUY"
            reasoning = f"Oversold Bounce ↑: RSI {rsi:.0f}, ADX {adx:.1f}"
        elif rsi > 68 and slope < 0.0001:
            direction = "SELL"
            reasoning = f"Overbought Reversal ↓: RSI {rsi:.0f}, ADX {adx:.1f}"

    if direction is None:
        return None

    sl_price  = round(price * (1 - sl_pct) if direction == "BUY" else price * (1 + sl_pct), 2)
    tgt_price = round(price * (1 + tgt_pct) if direction == "BUY" else price * (1 - tgt_pct), 2)
    sl_pts    = round(abs(price - sl_price), 2)
    lot       = FUTURES_STOCKS[stock]["lot"]
    # Position sizing: risk MAX_TRADE_RISK per trade
    lots      = max(1, math.floor(MAX_TRADE_RISK / (sl_pts * lot)))
    actual_risk = lots * sl_pts * lot

    # Skip if risk blows out (huge lot sizes)
    if actual_risk > MAX_TRADE_RISK * 3:
        lots = 1
        actual_risk = sl_pts * lot

    return {
        "stock":       stock,
        "direction":   direction,
        "price":       price,
        "sl_price":    sl_price,
        "tgt_price":   tgt_price,
        "sl_pts":      sl_pts,
        "lots":        lots,
        "lot_size":    lot,
        "actual_risk": actual_risk,
        "adx":         round(adx, 1),
        "rsi":         round(rsi, 1),
        "vol":         round(vol, 0),
        "slope":       round(slope, 6),
        "reasoning":   reasoning,
        "ts":          datetime.now(IST).strftime("%H:%M:%S"),
        "expiry":      get_stock_futures_expiry(),
        "contract":    futures_symbol_str(stock, direction),
    }

# ─────────────────────────────────────────────────────────────
# FUTURES PAPER TRADE EXECUTION
# ─────────────────────────────────────────────────────────────
def futures_paper_enter(sig: dict) -> None:
    trade = {
        "id":          len(ss.futures_closed_trades) + len(ss.futures_open_trades) + 1,
        "stock":       sig["stock"],
        "direction":   sig["direction"],
        "contract":    sig["contract"],
        "expiry":      sig["expiry"],
        "entry_time":  sig["ts"],
        "entry_date":  datetime.now(IST).strftime("%Y-%m-%d"),
        "entry_price": sig["price"],
        "sl_price":    sig["sl_price"],
        "tgt_price":   sig["tgt_price"],
        "sl_pts":      sig["sl_pts"],
        "lots":        sig["lots"],
        "lot_size":    sig["lot_size"],
        "actual_risk": sig["actual_risk"],
        "current_price": sig["price"],
        "pnl":         0.0,
        "status":      "OPEN",
        "reasoning":   sig["reasoning"],
        "exit_reason": None,
        "exit_time":   None,
        "exit_price":  None,
    }
    ss.futures_open_trades.append(trade)
    log_event(
        f"[FUT] ENTER {sig['direction']} {sig['stock']} @ ₹{sig['price']:,.2f} "
        f"| SL ₹{sig['sl_price']:,.2f} | Tgt ₹{sig['tgt_price']:,.2f} | {sig['lots']} lot(s)"
    )
    save_state()

def futures_paper_exit(trade: dict, exit_price: float, reason: str) -> None:
    lot = trade["lot_size"]
    mult = 1 if trade["direction"] == "BUY" else -1
    pnl  = mult * (exit_price - trade["entry_price"]) * trade["lots"] * lot

    trade.update({
        "current_price": exit_price,
        "pnl":           pnl,
        "status":        "CLOSED",
        "exit_reason":   reason,
        "exit_time":     datetime.now(IST).strftime("%H:%M:%S"),
        "exit_price":    exit_price,
    })

    ss.core_pnl  += pnl
    ss.daily_pnl += pnl
    ss.capital   += pnl
    ss.futures_closed_trades.append(trade)
    ss.pnl_curve.append({"ts": trade["exit_time"], "pnl": ss.core_pnl})

    if ss.core_pnl <= -MAX_DAILY_LOSS:
        ss.locked = True

    log_event(
        f"[FUT] EXIT {trade['direction']} {trade['stock']} @ ₹{exit_price:,.2f} "
        f"· PnL {fmt_pnl(pnl)} · Reason: {reason}"
    )
    save_state()

def update_futures_open_trades(stock: str, current_price: float) -> None:
    to_close = []
    for trade in ss.futures_open_trades:
        if trade["stock"] != stock:
            continue
        trade["current_price"] = current_price
        mult = 1 if trade["direction"] == "BUY" else -1
        trade["pnl"] = mult * (current_price - trade["entry_price"]) * trade["lots"] * trade["lot_size"]

        hit_sl  = (trade["direction"] == "BUY"  and current_price <= trade["sl_price"]) or \
                  (trade["direction"] == "SELL" and current_price >= trade["sl_price"])
        hit_tgt = (trade["direction"] == "BUY"  and current_price >= trade["tgt_price"]) or \
                  (trade["direction"] == "SELL" and current_price <= trade["tgt_price"])

        if hit_sl:
            to_close.append((trade, trade["sl_price"], "SL"))
        elif hit_tgt:
            to_close.append((trade, trade["tgt_price"], "TARGET"))

    for trade, exit_p, reason in to_close:
        ss.futures_open_trades.remove(trade)
        futures_paper_exit(trade, exit_p, reason)

# ─────────────────────────────────────────────────────────────
# POSITION SIZING (index options)
# ─────────────────────────────────────────────────────────────
def compute_size(symbol: str, sl_pts: float) -> tuple[int, float, bool]:
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
# INDEX OPTIONS PAPER TRADE EXECUTION
# ─────────────────────────────────────────────────────────────
def paper_enter(signal: dict, lots: int, actual_risk: float) -> None:
    spot       = signal["spot_entry"]
    expiry     = get_expiry_cached(signal["symbol"])
    ep         = round(spot * 0.004, 1)
    sl_premium = round(ep - signal["sl_points"], 1)
    target     = round(ep + signal["sl_points"] * 2.0, 1)
    opt_symbol = option_symbol_str(signal["symbol"], signal["strike"], signal["direction"])

    trade = {
        "id":           len(ss.closed_trades) + len(ss.open_trades) + 1,
        "symbol":       signal["symbol"],
        "direction":    signal["direction"],
        "strike":       signal["strike"],
        "expiry":       expiry,
        "opt_symbol":   opt_symbol,
        "regime":       signal["regime"],
        "entry_date":   datetime.now(IST).strftime("%Y-%m-%d"),
        "entry_time":   signal["ts"],
        "entry_spot":   signal["spot_entry"],
        "entry_prem":   ep,
        "ltp_source":   "Est. 0.4% of spot",
        "sl_prem":      sl_premium,
        "sl_points":    signal["sl_points"],
        "target_prem":  target,
        "lots":         lots,
        "actual_risk":  actual_risk,
        "current_prem": ep,
        "pnl":          0.0,
        "status":       "OPEN",
        "reasoning":    signal["reasoning"],
        "exit_reason":  None,
        "exit_time":    None,
        "exit_prem":    None,
    }
    ss.open_trades.append(trade)
    ss.validation["signals_fired"] += 1
    log_event(
        f"ENTER {opt_symbol} @ ₹{ep} [Est.] · SL ₹{sl_premium} · Target ₹{target} · {lots} lot(s)"
    )
    save_state()

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
    if reason == "SL":
        ss.validation["sl_hits"] += 1
    elif reason == "TARGET":
        ss.validation["target_hits"] += 1
    if ss.core_pnl <= -MAX_DAILY_LOSS:
        ss.locked = True
    log_event(
        f"EXIT {trade.get('opt_symbol', trade['symbol'])} "
        f"@ ₹{exit_premium} · PnL {fmt_pnl(pnl)} · Reason: {reason}"
    )
    save_state()

def update_open_trades(symbol: str, current_spot: float) -> None:
    to_close = []
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
    for trade, exit_p, reason in to_close:
        ss.open_trades.remove(trade)
        paper_exit(trade, exit_p, reason)

# ─────────────────────────────────────────────────────────────
# MAIN CYCLE
# ─────────────────────────────────────────────────────────────
def run_cycle() -> None:
    phase = get_phase()
    vix   = fetch_vix()

    # ── Index Options cycle ───────────────────────────────────
    for symbol, ticker in SYMBOLS.items():
        df = fetch_candles(ticker, period="2d", interval="1m")
        if df is None or len(df) < 21:
            continue
        spot  = float(df["Close"].iloc[-1].item())
        adx   = compute_adx(df)
        slope = compute_ema_slope(df)
        vol   = compute_volume_ratio(df)
        pcr   = compute_pcr_proxy(adx, vix)
        regime_id, confidence = classify_regime(vix, adx, pcr, slope, vol)

        history = ss.regime_history[symbol]
        if history and history[-1]["regime"] != regime_id:
            ss.validation["regime_flips"] += 1
        history.append({"ts": datetime.now(IST).strftime("%H:%M:%S"),
                        "regime": regime_id, "vix": vix, "adx": adx,
                        "pcr": pcr, "slope": slope, "vol": vol})
        ss.regime_history[symbol] = history[-500:]

        ss.market_data[symbol] = {
            "spot": spot, "vix": vix, "adx": adx, "pcr": pcr,
            "slope": slope, "vol": vol, "regime": regime_id, "confidence": confidence,
        }
        update_open_trades(symbol, spot)

        already_open = any(t["symbol"] == symbol for t in ss.open_trades)
        if not already_open:
            result = generate_signal(symbol, spot, regime_id, adx, vix, pcr, slope, vol, phase)
            sig    = result["signal"]
            reason = result["reason"]
            ss.signals[symbol]        = sig
            ss.signal_reasons[symbol] = reason
            if sig is not None:
                lots, actual_risk, forced = compute_size(symbol, sig["sl_points"])
                if lots > 0 and actual_risk <= MAX_TRADE_RISK:
                    paper_enter(sig, lots, actual_risk)
        else:
            ss.signals[symbol]        = None
            ss.signal_reasons[symbol] = f"Trade already open for {symbol}."

    # ── Stock Futures cycle ───────────────────────────────────
    batch = fetch_stock_candles_batch()
    new_futures_signals: dict = {}

    for stock, df in batch.items():
        if len(df) < 21:
            continue
        price = float(df["Close"].iloc[-1].item())
        adx   = compute_adx(df)
        slope = compute_ema_slope(df)
        vol   = compute_volume_ratio(df)
        rsi   = compute_rsi(df)

        ss.futures_market_data[stock] = {
            "price": price, "adx": adx, "slope": slope,
            "vol": vol, "rsi": rsi,
        }

        update_futures_open_trades(stock, price)

        already_open = any(t["stock"] == stock for t in ss.futures_open_trades)
        if not already_open:
            sig = generate_futures_signal(stock, price, adx, slope, vol, rsi, vix, phase)
            if sig is not None:
                new_futures_signals[stock] = sig
                futures_paper_enter(sig)

    # Merge new signals into session (keep previous cycles' signals visible)
    ss.futures_signals.update(new_futures_signals)
    # Remove signals for stocks that now have open trades
    for stock in list(ss.futures_signals.keys()):
        if any(t["stock"] == stock for t in ss.futures_open_trades):
            del ss.futures_signals[stock]

    ss.last_fetch = datetime.now(IST).strftime("%H:%M:%S")

# ═════════════════════════════════════════════════════════════
# DASHBOARD
# ═════════════════════════════════════════════════════════════
phase   = get_phase()
phase_m = PHASE_META[phase]
now_ist = datetime.now(IST).strftime("%d %b %Y  %H:%M:%S IST")

st.markdown(f"""
<div style="background:#080c12;border-bottom:1px solid #1c2333;
     padding:10px 4px;margin-bottom:14px;display:flex;
     align-items:center;justify-content:space-between;">
  <div>
    <span style="font-family:'JetBrains Mono',monospace;font-size:1.2rem;
          font-weight:700;color:#e6edf3;letter-spacing:2px;">📊 SYSTEM 1818</span>
    <span style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;
          color:#6b7785;margin-left:12px;letter-spacing:1px;">
      PAPER TRADE ENGINE · LIVE NSE · OPTIONS + STOCK FUTURES
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

ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1, 1, 1, 2])
with ctrl1:
    if st.button("▶ Refresh Now"):
        run_cycle()
        st.rerun()
with ctrl2:
    auto = st.checkbox("⚡ Auto (1-min)", value=False)
with ctrl3:
    if st.button("🔄 Reset All"):
        if os.path.exists(SAVE_FILE):
            os.remove(SAVE_FILE)
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
with ctrl4:
    if ss.last_fetch:
        idx_open = len(getattr(ss, "open_trades",         []))
        fut_open = len(getattr(ss, "futures_open_trades", []))
        st.markdown(
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.72rem;color:#6b7785;">'
            f'Last fetch: {ss.last_fetch} · Options: {idx_open} open · Futures: {fut_open} open</span>',
            unsafe_allow_html=True,
        )

if not ss.market_data:
    run_cycle()

# ── Account ───────────────────────────────────────────────────
st.markdown('<div class="section-lbl">Paper Account</div>', unsafe_allow_html=True)

_open_trades     = getattr(ss, "open_trades",         [])
_fut_open_trades = getattr(ss, "futures_open_trades", [])

opt_deployed  = sum(t["entry_prem"] * t["lots"] * LOT_SIZE[t["symbol"]] for t in _open_trades)
fut_deployed  = sum(t["entry_price"] * t["lots"] * t["lot_size"] * 0.15
                    for t in _fut_open_trades)   # ~15% margin approx
capital_deployed = opt_deployed + fut_deployed
capital_free     = ss.capital - capital_deployed
unrealised_pnl   = sum(t["pnl"] for t in _open_trades) + \
                   sum(t["pnl"] for t in _fut_open_trades)

a1, a2, a3, a4, a5, a6 = st.columns(6)
with a1: st.metric("Starting Capital",   f"₹{ACCOUNT_BASE:,.0f}")
with a2: st.metric("Current Capital",    f"₹{ss.capital:,.0f}", f"{ss.capital - ACCOUNT_BASE:+,.0f}")
with a3: st.metric("Deployed (est.)",    f"₹{capital_deployed:,.0f}")
with a4: st.metric("Free Capital",       f"₹{capital_free:,.0f}")
with a5: st.metric("Unrealised PnL",     f"₹{unrealised_pnl:+,.0f}")
with a6: st.metric("Realised PnL",       f"₹{ss.core_pnl:+,.0f}")

loss_pct  = max(0.0, -ss.core_pnl) / MAX_DAILY_LOSS
bar_color = "#FF4D4D" if loss_pct > 0.7 else ("#FFC93B" if loss_pct > 0.4 else "#33FF99")
st.markdown(f"""
<div style="margin:6px 0 10px;">
  <div style="display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;
       font-size:0.62rem;color:#6b7785;margin-bottom:3px;">
    <span>DAILY LOSS METER</span><span>{loss_pct*100:.1f}% of ₹{MAX_DAILY_LOSS:,} breaker</span>
  </div>
  <div style="background:#1c2333;border-radius:3px;height:5px;">
    <div style="width:{min(loss_pct*100,100):.1f}%;background:{bar_color};
         height:100%;border-radius:3px;"></div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Live Charts ───────────────────────────────────────────────
st.markdown('<div class="section-lbl">Live Charts — NIFTY & BANK NIFTY</div>', unsafe_allow_html=True)
TV_INTERVAL_OPTIONS = {"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30","1h":"60","1D":"D","1W":"W"}
ci1, ci2 = st.columns([4, 1])
with ci2:
    tv_sel = st.selectbox("Interval", list(TV_INTERVAL_OPTIONS.keys()), index=2, label_visibility="collapsed")
tv_iv = TV_INTERVAL_OPTIONS[tv_sel]

def tv_iframe(symbol: str, interval: str, height: int = 430) -> str:
    url = (f"https://www.tradingview.com/widgetembed/?frameElementId=tv_chart"
           f"&symbol={symbol}&interval={interval}&theme=dark&style=1&locale=en"
           f"&timezone=Asia%2FKolkata&hide_top_toolbar=0&hide_legend=0&save_image=0"
           f"&studies=RSI%40tv-basicstudies%1FMAExp%40tv-basicstudies%1FVolume%40tv-basicstudies"
           f"&utm_source=streamlit&utm_medium=widget")
    return (f'<iframe src="{url}" width="100%" height="{height}" frameborder="0" '
            f'allowtransparency="true" scrolling="no" '
            f'style="border:1px solid #1c2333;border-radius:8px;"></iframe>')

chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    st.markdown('<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.68rem;color:#3BA7FF;letter-spacing:2px;margin-bottom:6px;">NIFTY 50</div>', unsafe_allow_html=True)
    st.markdown(tv_iframe("NSE:NIFTY50", tv_iv), unsafe_allow_html=True)
with chart_col2:
    st.markdown('<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.68rem;color:#3BA7FF;letter-spacing:2px;margin-bottom:6px;">BANK NIFTY</div>', unsafe_allow_html=True)
    st.markdown(tv_iframe("NSE:BANKNIFTY", tv_iv), unsafe_allow_html=True)

# ── Live Market Matrix ────────────────────────────────────────
st.markdown('<div class="section-lbl">Live Market Matrix</div>', unsafe_allow_html=True)
if ss.market_data:
    for symbol, md in ss.market_data.items():
        rm   = REGIME_META[md["regime"]]
        icon = {"1":"🟦","2":"🟩","3":"🟥","4":"🟨"}.get(str(md["regime"]),"⬜")
        with st.expander(
            f"{icon}  {symbol}  ·  ₹{md['spot']:,.2f}  ·  "
            f"Regime {md['regime']}: {rm['name']}  [{md['confidence']}]", expanded=True):
            m1,m2,m3,m4,m5,m6 = st.columns(6)
            with m1: st.metric("Spot",       f"₹{md['spot']:,.2f}")
            with m2: st.metric("India VIX",  f"{md['vix']:.2f}")
            with m3: st.metric("ADX",        f"{md['adx']:.2f}")
            with m4: st.metric("PCR(proxy)", f"{md['pcr']:.3f}")
            with m5: st.metric("EMA Slope",  f"{md['slope']:+.5f}")
            with m6: st.metric("Volume %",   f"{md['vol']:.0f}%")
            st.markdown(f"""
            <div style="background:{rm['bg']};border:1px solid {rm['color']}44;border-radius:6px;
                 padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:0.75rem;
                 color:{rm['color']};margin-top:8px;">
              <b>Regime {md['regime']} — {rm['name']}</b> · {rm['desc']}
            </div>""", unsafe_allow_html=True)

# ── Index Signals ─────────────────────────────────────────────
st.markdown('<div class="section-lbl">Index Options Signals</div>', unsafe_allow_html=True)
sig_cols = st.columns(len(SYMBOLS))
for i, symbol in enumerate(SYMBOLS):
    sig    = ss.signals.get(symbol)
    reason = ss.signal_reasons.get(symbol, "")
    with sig_cols[i]:
        if sig is not None:
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
              <div style="font-size:0.7rem;color:#8b949e;margin-top:8px;">{sig['reasoning']}</div>
              <div style="margin-top:6px;font-size:0.65rem;color:{dc};opacity:0.7;">@ {sig['ts']}</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="signal-card signal-none">
              <div style="font-size:0.8rem;">⬜ {symbol}</div>
              <div style="font-size:0.72rem;margin-top:6px;">{reason or 'No signal.'}</div>
            </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# ████  STOCK FUTURES SIGNALS  ████
# ══════════════════════════════════════════════════════════════
st.markdown('<div class="section-lbl">Stock Futures Signals</div>', unsafe_allow_html=True)

# ── Signal summary cards ──────────────────────────────────────
active_fut_signals = {
    s: sig for s, sig in ss.futures_signals.items()
    if not any(t["stock"] == s for t in ss.futures_open_trades)
}

if active_fut_signals:
    n_cols = min(4, len(active_fut_signals))
    cols   = st.columns(n_cols)
    for idx, (stock, sig) in enumerate(active_fut_signals.items()):
        col = cols[idx % n_cols]
        dc  = "#33FF99" if sig["direction"] == "BUY" else "#FF4D4D"
        css = "signal-buy" if sig["direction"] == "BUY" else "signal-sell"
        icon = "▲" if sig["direction"] == "BUY" else "▼"
        with col:
            st.markdown(f"""
            <div class="signal-card {css}">
              <div style="font-size:1rem;font-weight:700;color:{dc};margin-bottom:8px;">
                {icon} {sig['direction']}  {stock}
              </div>
              <div class="drow"><span class="dlbl">Entry</span>
                <span class="dval">₹{sig['price']:,.2f}</span></div>
              <div class="drow"><span class="dlbl">Stop-Loss</span>
                <span class="dval" style="color:#FF4D4D;">₹{sig['sl_price']:,.2f}</span></div>
              <div class="drow"><span class="dlbl">Target</span>
                <span class="dval" style="color:#33FF99;">₹{sig['tgt_price']:,.2f}</span></div>
              <div class="drow"><span class="dlbl">Lots × Qty</span>
                <span class="dval">{sig['lots']} × {sig['lot_size']}</span></div>
              <div class="drow"><span class="dlbl">Risk ₹</span>
                <span class="dval">₹{sig['actual_risk']:,.0f}</span></div>
              <div class="drow"><span class="dlbl">ADX / RSI</span>
                <span class="dval">{sig['adx']} / {sig['rsi']}</span></div>
              <div class="drow"><span class="dlbl">Vol %</span>
                <span class="dval">{sig['vol']:.0f}%</span></div>
              <div style="font-size:0.68rem;color:#8b949e;margin-top:8px;line-height:1.5;">
                {sig['reasoning']}
              </div>
              <div style="font-size:0.62rem;color:{dc};opacity:0.7;margin-top:4px;">
                Expiry: {sig['expiry']} · @ {sig['ts']}
              </div>
            </div>""", unsafe_allow_html=True)
else:
    st.markdown(
        '<div class="signal-card signal-none" style="width:100%;">'
        '⬜ No stock futures signals currently. Conditions not met across 20 stocks or trades already open.'
        '</div>', unsafe_allow_html=True)

# ── Futures market data table ─────────────────────────────────
if ss.futures_market_data:
    with st.expander("📊 Stock Futures Market Scan (all 20 stocks)", expanded=False):
        rows = []
        for stock, md in ss.futures_market_data.items():
            # Determine signal status
            in_open = any(t["stock"] == stock for t in ss.futures_open_trades)
            in_sig  = stock in active_fut_signals
            if in_open:
                status = "🟢 OPEN"
            elif in_sig:
                d = active_fut_signals[stock]["direction"]
                status = f"{'▲' if d=='BUY' else '▼'} SIGNAL {d}"
            else:
                status = "⬜ WATCH"

            rows.append({
                "Stock":   stock,
                "Price":   f"₹{md['price']:,.2f}",
                "ADX":     round(md["adx"], 1),
                "RSI":     round(md["rsi"], 1),
                "Vol %":   f"{md['vol']:.0f}%",
                "Slope":   f"{md['slope']:+.6f}",
                "Lot":     FUTURES_STOCKS[stock]["lot"],
                "Status":  status,
            })
        df_scan = pd.DataFrame(rows)
        def _style_status(val):
            if "SIGNAL" in val:
                return "color:#33FF99;font-weight:700;" if "BUY" in val else "color:#FF4D4D;font-weight:700;"
            if "OPEN" in val:
                return "color:#FFC93B;font-weight:700;"
            return "color:#6b7785;"
        def _style_rsi(val):
            if val >= 70: return "color:#FF4D4D;font-weight:700;"
            if val <= 30: return "color:#33FF99;font-weight:700;"
            return ""
        styled = (
            df_scan.style
            .map(_style_status, subset=["Status"])
            .map(_style_rsi, subset=["RSI"])
            .set_properties(**{"font-family": "JetBrains Mono, monospace", "font-size": "0.78rem"})
        )
        st.dataframe(styled, use_container_width=True, hide_index=True, height=400)

# ── Open Futures Trades ───────────────────────────────────────
st.markdown('<div class="section-lbl">Open Stock Futures Trades</div>', unsafe_allow_html=True)
if ss.futures_open_trades:
    rows = []
    for t in ss.futures_open_trades:
        qty     = t["lots"] * t["lot_size"]
        mult    = 1 if t["direction"] == "BUY" else -1
        pnl_pct = (t["pnl"] / (t["entry_price"] * qty * 0.15) * 100) if qty else 0
        rows.append({
            "Contract":    t["contract"],
            "Expiry":      t["expiry"],
            "Direction":   t["direction"],
            "Date":        t["entry_date"],
            "Entry Time":  t["entry_time"],
            "Lots × Qty":  f"{t['lots']} × {t['lot_size']} = {qty}",
            "Entry Price": f"₹{t['entry_price']:,.2f}",
            "CMP":         f"₹{t['current_price']:,.2f}",
            "SL":          f"₹{t['sl_price']:,.2f}",
            "Target":      f"₹{t['tgt_price']:,.2f}",
            "Paper PnL":   f"{fmt_pnl(t['pnl'])} ({pnl_pct:+.1f}%)",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.markdown(
        '<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.78rem;color:#6b7785;padding:6px;">No open futures trades.</div>',
        unsafe_allow_html=True)

# ── Open Index Options Trades ─────────────────────────────────
st.markdown('<div class="section-lbl">Open Index Options Trades</div>', unsafe_allow_html=True)
if ss.open_trades:
    rows = []
    for t in ss.open_trades:
        lot         = LOT_SIZE[t["symbol"]]
        qty         = t["lots"] * lot
        invested    = t["entry_prem"] * qty
        current_val = t["current_prem"] * qty
        max_loss    = invested - (t["sl_prem"] * qty)
        pnl_pct     = (t["pnl"] / invested * 100) if invested else 0
        rows.append({
            "Contract":     t.get("opt_symbol", t["symbol"]),
            "Expiry":       t.get("expiry", "—"),
            "Entry Time":   t["entry_time"],
            "Lots × Qty":   f"{t['lots']} × {lot} = {qty}",
            "Buy Price":    f"₹{t['entry_prem']:,.1f}",
            "CMP":          f"₹{t['current_prem']:,.1f}",
            "SL Price":     f"₹{t['sl_prem']:,.1f}",
            "Target Price": f"₹{t['target_prem']:,.1f}",
            "Invested":     f"₹{invested:,.0f}",
            "Max Loss":     f"₹{max_loss:,.0f}",
            "Paper PnL":    f"{fmt_pnl(t['pnl'])} ({pnl_pct:+.1f}%)",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.markdown(
        '<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.78rem;color:#6b7785;padding:6px;">No open options trades.</div>',
        unsafe_allow_html=True)

# ── Validation ────────────────────────────────────────────────
st.markdown('<div class="section-lbl">Validation Dashboard</div>', unsafe_allow_html=True)
total     = len(ss.closed_trades) + len(ss.futures_closed_trades)
opt_wins  = sum(1 for t in ss.closed_trades if t["pnl"] > 0)
fut_wins  = sum(1 for t in ss.futures_closed_trades if t["pnl"] > 0)
all_wins  = opt_wins + fut_wins
v1,v2,v3,v4,v5,v6 = st.columns(6)
with v1: st.metric("Signals Fired",   ss.validation["signals_fired"])
with v2: st.metric("SL Hits",         ss.validation["sl_hits"])
with v3: st.metric("Target Hits",     ss.validation["target_hits"])
with v4: st.metric("Win Rate (Opt)",  f"{opt_wins/len(ss.closed_trades)*100:.0f}%" if ss.closed_trades else "—")
with v5: st.metric("Win Rate (Fut)",  f"{fut_wins/len(ss.futures_closed_trades)*100:.0f}%" if ss.futures_closed_trades else "—")
with v6: st.metric("Regime Flips",    ss.validation["regime_flips"])

# Closed futures trades table
if ss.futures_closed_trades:
    st.markdown('<div class="section-lbl">Closed Stock Futures Trades</div>', unsafe_allow_html=True)
    rows = []
    for t in ss.futures_closed_trades:
        qty = t["lots"] * t["lot_size"]
        rows.append({
            "Contract":   t["contract"],
            "Direction":  t["direction"],
            "Date":       t["entry_date"],
            "Entry":      t["entry_time"],
            "Exit":       t["exit_time"],
            "Qty":        qty,
            "Buy @":      f"₹{t['entry_price']:,.2f}",
            "Sell @":     f"₹{t['exit_price']:,.2f}",
            "Reason":     t["exit_reason"],
            "PnL":        fmt_pnl(t["pnl"]),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# Closed options trades table
if ss.closed_trades:
    st.markdown('<div class="section-lbl">Closed Index Options Trades</div>', unsafe_allow_html=True)
    rows = []
    for t in ss.closed_trades:
        lot = LOT_SIZE[t["symbol"]]
        qty = t["lots"] * lot
        rows.append({
            "Contract":  t.get("opt_symbol", t["symbol"]),
            "Entry":     t["entry_time"],
            "Exit":      t["exit_time"],
            "Qty":       qty,
            "Buy @":     f"₹{t['entry_prem']:,.1f}",
            "Sell @":    f"₹{t['exit_prem']:,.1f}",
            "Reason":    t["exit_reason"],
            "PnL":       fmt_pnl(t["pnl"]),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ── PnL Curve ─────────────────────────────────────────────────
if len(ss.pnl_curve) >= 2:
    st.markdown('<div class="section-lbl">Paper PnL Curve (Options + Futures)</div>', unsafe_allow_html=True)
    curve_df = pd.DataFrame(ss.pnl_curve)
    st.line_chart(curve_df.set_index("ts")["pnl"], use_container_width=True)

# ── Screener ──────────────────────────────────────────────────
st.markdown('<div class="section-lbl">Nifty 50 Stock Screener</div>', unsafe_allow_html=True)
scr_tab1, scr_tab2 = st.tabs(["📊 Screener Table", "📈 Market Map (Bubble)"])
with scr_tab1:
    sf1,sf2,sf3,sf4 = st.columns([1,1,1,1])
    with sf1:
        scr_regime = st.multiselect("Regime Filter",
            ["🟩 TRENDING","🟦 RANGING","🟥 EXTREME","🟨 WATCH"], default=["🟩 TRENDING"])
    with sf2:
        scr_ema = st.selectbox("EMA Position", ["All","Above EMA ✅","Below EMA ❌"])
    with sf3:
        scr_rsi_min, scr_rsi_max = st.slider("RSI Range", 0, 100, (40, 75))
    with sf4:
        scr_vol_min = st.slider("Min Volume %", 0, 300, 100)
    if st.button("🔍 Run Screener", key="run_screener"):
        with st.spinner("Fetching data…"):
            fetch_screener_data.clear()
            scr_df = fetch_screener_data()
    else:
        scr_df = fetch_screener_data()
    if scr_df.empty:
        st.warning("Screener data unavailable.")
    else:
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
        def style_chg(val):
            return f"color:{'#33FF99' if val>0 else '#FF4D4D' if val<0 else '#8b949e'};font-weight:600;"
        def style_rsi(val):
            if val >= 70: return "color:#FF4D4D;font-weight:600;"
            if val <= 30: return "color:#33FF99;font-weight:600;"
            return "color:#e6edf3;"
        styled = (filtered.style.map(style_chg, subset=["Chg %"])
                  .map(style_rsi, subset=["RSI(14)"])
                  .set_properties(**{"font-family":"JetBrains Mono, monospace","font-size":"0.8rem"}))
        st.caption(f"{len(filtered)} / {len(scr_df)} stocks match filters")
        st.dataframe(styled, use_container_width=True, hide_index=True, height=420)

with scr_tab2:
    hmap_df = fetch_screener_data()
    if not hmap_df.empty:
        tiles_html = '<div style="display:flex;flex-wrap:wrap;gap:6px;padding:4px 0;">'
        for _, row in hmap_df.iterrows():
            chg = row["Chg %"]
            if chg >= 2:    bg,fg = "#0d3320","#33FF99"
            elif chg >= 1:  bg,fg = "#0a2a1a","#29cc7a"
            elif chg >= 0:  bg,fg = "#111a14","#22aa66"
            elif chg >= -1: bg,fg = "#2a0d0d","#FF6B6B"
            elif chg >= -2: bg,fg = "#330d0d","#FF4D4D"
            else:           bg,fg = "#3d0a0a","#ff2222"
            tiles_html += f"""
            <div title="RSI:{row['RSI(14)']:.0f} | Vol:{row['Vol %']:.0f}% | LTP:₹{row['LTP']:,.0f}"
                 style="background:{bg};border:1px solid {fg}88;border-radius:6px;
                        padding:8px 10px;min-width:90px;font-family:'JetBrains Mono',monospace;">
              <div style="font-size:0.72rem;font-weight:700;color:{fg};">{row['Stock']}</div>
              <div style="font-size:0.85rem;font-weight:700;color:{fg};margin:2px 0;">{chg:+.2f}%</div>
              <div style="font-size:0.6rem;color:#6b7785;">RSI {row['RSI(14)']:.0f}</div>
            </div>"""
        tiles_html += "</div>"
        st.markdown(tiles_html, unsafe_allow_html=True)

# ── Regime History ────────────────────────────────────────────
st.markdown('<div class="section-lbl">Regime History</div>', unsafe_allow_html=True)
for symbol in SYMBOLS:
    hist = ss.regime_history.get(symbol, [])
    if hist:
        df_hist = pd.DataFrame(hist[-50:])
        st.caption(f"{symbol} — last {len(df_hist)} readings")
        st.dataframe(
            df_hist[["ts","regime","vix","adx","pcr","slope","vol"]].rename(
                columns={"ts":"Time","regime":"Regime","vix":"VIX","adx":"ADX",
                         "pcr":"PCR","slope":"Slope","vol":"Vol%"}),
            use_container_width=True, hide_index=True)

# ── Activity Log ──────────────────────────────────────────────
st.markdown('<div class="section-lbl">Activity Log</div>', unsafe_allow_html=True)
if ss.trade_log:
    st.code("\n".join(reversed(ss.trade_log[-30:])), language=None)
else:
    st.markdown('<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.75rem;color:#6b7785;">No activity yet.</div>', unsafe_allow_html=True)

st.markdown("""
<div style="margin-top:24px;padding:12px 0;border-top:1px solid #1c2333;
     font-family:'JetBrains Mono',monospace;font-size:0.62rem;
     color:#4b5563;text-align:center;line-height:2;">
  SYSTEM 1818 Paper Trade Engine · Data: yfinance (Yahoo Finance / NSE) · No real orders placed<br>
  Stock futures SL/Target are price-based (not premium). Lot sizes per NSE circulars — update when revised.<br>
  ⚠ Paper trading results do not guarantee live performance. All trading involves risk.
</div>
""", unsafe_allow_html=True)

if auto and phase in ("ACTIVE","MIDDAY_FREEZE","ACTIVE_PM","OPENING_FREEZE"):
    time.sleep(60)
    run_cycle()
    st.rerun()
