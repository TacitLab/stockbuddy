"""
港股 AI v4 A/B 回测 — 支持本地CSV缓存，绕过yfinance限速
用法：
  1. 正常运行：python3 stock_backtest_v4_ab.py
  2. 强制重新下载：python3 stock_backtest_v4_ab.py --refresh
"""

import yfinance as yf
import pandas as pd
import numpy as np
import time, os, sys
import warnings
warnings.filterwarnings('ignore')

CACHE_DIR = "data"
os.makedirs(CACHE_DIR, exist_ok=True)
FORCE_REFRESH = "--refresh" in sys.argv

STOCKS = {
    "平安好医生": "1833.HK",
    "叮当健康":   "9886.HK",
    "中原建业":   "9982.HK",
}
PERIOD = "2y"
INITIAL_CAPITAL = 10000.0
W_TECH, W_FUNDAMENTAL, W_SENTIMENT = 0.50, 0.30, 0.20
BUY_THRESH, SELL_THRESH = 1.5, -1.5

# A: 固定止损
A_TRAILING_STOP = 0.12
A_VOL_CONFIRM   = 1.2

# B: ATR动态止损
B_ATR_MULT    = 2.5
B_ATR_PERIOD  = 14
B_VOL_CONFIRM = 1.2
B_MIN_STOP    = 0.08
B_MAX_STOP    = 0.35

def position_ratio(score):
    if score >= 5:   return 1.0
    elif score >= 3: return 0.6
    return 0.3

FUNDAMENTAL_TIMELINE = {
    "平安好医生": [
        {"from": "2024-01-01", "score": -3.0},
        {"from": "2024-08-01", "score": -1.0},
        {"from": "2025-01-01", "score":  0.0},
        {"from": "2025-08-01", "score":  1.0},
    ],
    "叮当健康": [
        {"from": "2024-01-01", "score": -3.0},
        {"from": "2024-06-01", "score": -2.0},
        {"from": "2025-01-01", "score": -1.0},
        {"from": "2025-09-01", "score":  1.0},
    ],
    "中原建业": [
        {"from": "2024-01-01", "score": -3.0},
        {"from": "2024-06-01", "score": -4.0},
        {"from": "2025-01-01", "score": -4.0},
        {"from": "2025-10-01", "score": -5.0},
    ],
}
SENTIMENT_TIMELINE = {
    "平安好医生": [
        {"from": "2024-01-01", "score": -1.0},
        {"from": "2024-10-01", "score":  1.0},
        {"from": "2025-01-01", "score":  2.0},
        {"from": "2026-01-01", "score":  3.0},
    ],
    "叮当健康": [
        {"from": "2024-01-01", "score": -2.0},
        {"from": "2024-08-01", "score": -1.0},
        {"from": "2025-04-01", "score":  1.0},
        {"from": "2025-10-01", "score":  2.0},
    ],
    "中原建业": [
        {"from": "2024-01-01", "score": -2.0},
        {"from": "2024-06-01", "score": -3.0},
        {"from": "2025-01-01", "score": -3.0},
        {"from": "2025-10-01", "score": -4.0},
    ],
}

def get_snapshot(tl, date):
    score = tl[0]["score"]
    for e in tl:
        if str(date.date()) >= e["from"]: score = e["score"]
        else: break
    return score

def calc_rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=p-1, min_periods=p).mean()
    l = (-d.clip(upper=0)).ewm(com=p-1, min_periods=p).mean()
    return 100 - 100 / (1 + g / l)

def calc_macd(s, fast=12, slow=26, sig=9):
    m = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    return m - m.ewm(span=sig, adjust=False).mean()

def calc_atr(df, period=14):
    hi, lo, cl = df["High"], df["Low"], df["Close"]
    tr = pd.concat([(hi-lo), (hi-cl.shift(1)).abs(), (lo-cl.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(com=period-1, min_periods=period).mean()

def score_tech(row):
    s = 0
    if   row.RSI < 30:  s += 3
    elif row.RSI < 45:  s += 1
    elif row.RSI > 70:  s -= 3
    elif row.RSI > 55:  s -= 1
    if   row.MACD_h > 0 and row.MACD_h_p <= 0: s += 3
    elif row.MACD_h < 0 and row.MACD_h_p >= 0: s -= 3
    elif row.MACD_h > 0: s += 1
    else:                s -= 1
    if   row.MA5 > row.MA20 > row.MA60: s += 2
    elif row.MA5 < row.MA20 < row.MA60: s -= 2
    if   row.Close > row.MA20 and row.Close_p <= row.MA20_p: s += 1
    elif row.Close < row.MA20 and row.Close_p >= row.MA20_p: s -= 1
    return float(np.clip(s, -10, 10))

def load_data(ticker):
    """优先读CSV缓存，否则从yfinance下载并缓存"""
    sym = ticker.replace(".HK", "")
    fp  = os.path.join(CACHE_DIR, f"{sym}.csv")
    if os.path.exists(fp) and not FORCE_REFRESH:
        df = pd.read_csv(fp, index_col=0, parse_dates=True)
        print(f"  📂 读取缓存: {fp} ({len(df)} 行)")
        return df
    print(f"  🌐 下载数据: {ticker}")
    df = yf.download(ticker, period=PERIOD, auto_adjust=True, progress=False)
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
    df.to_csv(fp)
    print(f"  💾 已缓存: {fp}")
    return df

def prepare_df(ticker):
    df = load_data(ticker)
    if df is None or len(df) < 60: return None
    c = df["Close"]
    df["RSI"]      = calc_rsi(c)
    h              = calc_macd(c)
    df["MACD_h"]   = h
    df["MACD_h_p"] = h.shift(1)
    for p in [5, 20, 60]: df[f"MA{p}"] = c.rolling(p).mean()
    df["MA20_p"]   = df["MA20"].shift(1)
    df["Close_p"]  = c.shift(1)
    df["Vol20"]    = df["Volume"].rolling(20).mean()
    df["ATR"]      = calc_atr(df, B_ATR_PERIOD)
    return df.dropna()

def simulate(name, df, use_atr=False):
    capital, position, entry_price = INITIAL_CAPITAL, 0, 0.0
    highest_price, trailing_pct   = 0.0, 0.0
    trades = []
    vc = A_VOL_CONFIRM if not use_atr else B_VOL_CONFIRM

    for date, row in df.iterrows():
        f     = get_snapshot(FUNDAMENTAL_TIMELINE[name], date)
        s     = get_snapshot(SENTIMENT_TIMELINE[name], date)
        t     = score_tech(row)
        score = W_TECH*t + W_FUNDAMENTAL*f + W_SENTIMENT*s
        price = float(row["Close"])
        vol   = float(row["Volume"])
        vol20 = float(row["Vol20"])

        if score >= BUY_THRESH and position == 0 and capital > price:
            if vol >= vol20 * vc:
                ratio  = position_ratio(score)
                shares = int(capital * ratio / price)
                if shares > 0:
                    position, entry_price, highest_price = shares, price, price
                    capital -= shares * price
                    if use_atr:
                        raw = float(row["ATR"]) * B_ATR_MULT / price
                        trailing_pct = float(np.clip(raw, B_MIN_STOP, B_MAX_STOP))
                        note = f"仓{ratio*100:.0f}% 量比{vol/vol20:.1f}x ATR止损{trailing_pct*100:.1f}%"
                    else:
                        trailing_pct = A_TRAILING_STOP
                        note = f"仓{ratio*100:.0f}% 量比{vol/vol20:.1f}x 固定止损{trailing_pct*100:.0f}%"
                    trades.append({"操作":"买入","日期":date.date(),"价格":round(price,4),
                                   "股数":shares,"评分":round(score,2),"备注":note})

        elif position > 0:
            highest_price = max(highest_price, price)
            stop_price    = highest_price * (1 - trailing_pct)
            if price <= stop_price or score <= SELL_THRESH:
                pnl = position * (price - entry_price)
                pct = pnl / (position * entry_price) * 100
                reason = (f"移动止损 高点{highest_price:.3f}→止损{stop_price:.3f}"
                          if price <= stop_price else f"评分卖出({score:.1f})")
                capital += position * price
                trades.append({"操作":"卖出","日期":date.date(),"价格":round(price,4),
                               "股数":position,"评分":round(score,2),
                               "盈亏%":f"{pct:+.1f}%","备注":reason})
                position, highest_price, trailing_pct = 0, 0.0, 0.0

    last  = float(df["Close"].iloc[-1])
    total = capital + position * last
    if position > 0:
        pct = (last - entry_price) / entry_price * 100
        trades.append({"操作":"未平仓","日期":"持仓中","价格":round(last,4),
                       "股数":position,"评分":"-","盈亏%":f"{pct:+.1f}%","备注":"-"})
    return total, trades

def run_ab(name, ticker):
    print(f"\n{'='*70}")
    print(f"  {name} ({ticker})")
    print(f"{'='*70}")
    df = prepare_df(ticker)
    if df is None:
        print("  ⚠️  数据不足，跳过")
        return None

    avg_atr_pct = df["ATR"].mean() / df["Close"].mean() * 100
    est_stop    = np.clip(df["ATR"].mean()*B_ATR_MULT/df["Close"].mean(), B_MIN_STOP, B_MAX_STOP)*100
    bh = (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1) * 100
    print(f"  ATR均值波动: {avg_atr_pct:.1f}%  → B动态止损估算: {est_stop:.1f}%  买持: {bh:+.1f}%")

    total_A, tA = simulate(name, df, use_atr=False)
    total_B, tB = simulate(name, df, use_atr=True)
    retA = (total_A - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    retB = (total_B - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    for label, trades in [("版本A 固定止损12%", tA), ("版本B ATR动态止损", tB)]:
        print(f"\n  【{label}】")
        if not trades: print("    无信号"); continue
        cols = [c for c in ["操作","日期","价格","股数","评分","盈亏%","备注"] if c in pd.DataFrame(trades).columns]
        print(pd.DataFrame(trades)[cols].to_string(index=False))

    nA = len([t for t in tA if t["操作"] in ("买入","卖出")])
    nB = len([t for t in tB if t["操作"] in ("买入","卖出")])
    print(f"\n  {'':22} {'A 固定12%':>12} {'B ATR动态':>12} {'买入持有':>10}")
    print(f"  {'策略总收益':<22} {retA:>+11.1f}% {retB:>+11.1f}% {bh:>+9.1f}%")
    print(f"  {'超额收益α':<22} {retA-bh:>+11.1f}% {retB-bh:>+11.1f}%")
    print(f"  {'交易次数':<22} {nA:>12} {nB:>12}")
    w = "B ✅" if retB > retA else ("A ✅" if retA > retB else "平手")
    print(f"  {'胜出':<22} {'':>23}  → {w}  (B-A: {retB-retA:+.1f}%)")
    return {"name":name,"A":retA,"B":retB,"BH":bh,"nA":nA,"nB":nB,"atr":avg_atr_pct}

if __name__ == "__main__":
    print("\n🔬 港股 AI v4 A/B 回测 — ATR动态止损 vs 固定止损")
    print(f"   A: 固定止损{A_TRAILING_STOP*100:.0f}% | B: ATR×{B_ATR_MULT}动态({B_MIN_STOP*100:.0f}%~{B_MAX_STOP*100:.0f}%)")
    print(f"   仓位分级 评分1.5-3→30% | 3-5→60% | >5→100%\n")

    results = []
    for i, (name, ticker) in enumerate(STOCKS.items()):
        if i > 0: time.sleep(3)
        r = run_ab(name, ticker)
        if r: results.append(r)

    if results:
        print(f"\n{'='*70}")
        print("  📋 A/B 最终汇总")
        print(f"{'='*70}")
        print(f"  {'股票':<12} {'ATR%':>6} {'A收益':>9} {'B收益':>9} {'买持':>9} {'B-A':>8} {'胜者':>5}")
        print(f"  {'-'*64}")
        for r in results:
            w = "B✅" if r["B"]>r["A"] else ("A✅" if r["A"]>r["B"] else "平")
            print(f"  {r['name']:<12} {r['atr']:>5.1f}% {r['A']:>+8.1f}% {r['B']:>+8.1f}% "
                  f"{r['BH']:>+8.1f}% {r['B']-r['A']:>+7.1f}% {w:>5}")
        avg_a  = np.mean([r["A"]  for r in results])
        avg_b  = np.mean([r["B"]  for r in results])
        avg_bh = np.mean([r["BH"] for r in results])
        print(f"  {'平均':<12} {'':>6} {avg_a:>+8.1f}% {avg_b:>+8.1f}% {avg_bh:>+8.1f}% {avg_b-avg_a:>+7.1f}%")
