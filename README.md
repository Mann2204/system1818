# SYSTEM 1818 — Paper Trade Engine

Live NSE paper trading validation. Real prices, zero real orders.

## Deploy in 5 minutes (free, no local Python)

### Step 1 — Create a GitHub account
Go to github.com → Sign up (free)

### Step 2 — Create a new repository
1. Click the **+** icon → New repository
2. Name it: `system1818`
3. Set to **Public**
4. Click **Create repository**

### Step 3 — Upload files
Click **Add file → Upload files** and upload both:
- `system1818_papertrade.py`
- `requirements.txt`

Commit with message: `Initial deploy`

### Step 4 — Deploy on Streamlit Cloud
1. Go to **share.streamlit.io** → Sign in with GitHub
2. Click **New app**
3. Select your repo: `system1818`
4. Main file path: `system1818_papertrade.py`
5. Click **Deploy**

Streamlit Cloud will install dependencies and launch your app.
You'll get a free public URL like:
`https://yourname-system1818-papertrade-xxxxx.streamlit.app`

**Done.** The app runs in your browser. No Python installation needed.

---

## What the paper engine validates over 1 month

| What | How |
|------|-----|
| **Regime classifier accuracy** | Regime History table — watch for flips and stability |
| **2% sizing engine** | Every trade card shows lots, risk, and SL pts |
| **Entry/exit logic & SL hits** | Validation Dashboard — SL Hits vs Target Hits ratio |
| **PnL curve & drawdown** | Live PnL curve chart updates after each closed trade |
| **Signal quality** | Activity Log — every entry/exit logged with reason |

## What is real vs simulated

| Data | Status |
|------|--------|
| NIFTY spot price | ✅ Real (yfinance → NSE) |
| BANKNIFTY spot price | ✅ Real (yfinance → NSE) |
| India VIX | ✅ Real (yfinance → NSE) |
| ADX, EMA Slope, Volume | ✅ Computed from real OHLCV |
| PCR | ⚠️ Proxy estimate (formula-based) |
| Options premium (LTP) | ⚠️ Delta approximation (0.5 × spot move) |
| Order execution | ❌ Paper only — no real orders |

## After 1 month — going live checklist

- [ ] Win rate > 45% across 20+ signals
- [ ] Avg RR ≥ 1.5:1 (target hits vs SL hits)
- [ ] Max drawdown stayed under ₹4,000 daily limit
- [ ] Regime classifier stable (< 3 flips per session on average)
- [ ] Replace PCR proxy with NSE options chain OI feed
- [ ] Replace options premium estimate with Angel One LTP
- [ ] Add Claude API call for strategy reasoning
- [ ] Move secrets to `.streamlit/secrets.toml`

---

*Paper trading results do not guarantee live performance. All trading involves risk.*
