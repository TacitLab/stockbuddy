"""
港股 AI 综合评分系统 v5 — 三版本 A/B/C 对比
A: 固定止损 12%（全仓）
B: ATR 动态止损（仓位分级）
C: 混合策略 — 按股票波动率自动选择 A 或 B
  - ATR/价格 < 5% → 低波动，用固定止损 8%
  - ATR/价格 5~15% → 中波动，用 ATR×2.5 动态
  - ATR/价格 > 15% → 高波动，用 ATR×2.0 + 宽上限 40%
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
PERIOD          = "2y"
INITIAL_CAPITAL = 10000.0
W_TECH, W_FUND, W_SENT = 0.50, 0.30, 0.20
BUY_THRESH, SELL_THRESH = 1.5, -1.5
VOL_CONFIRM = 1.2

# ── 版本参数 ──────────────────────────────────────────────────────────
A_FIXED_STOP  = 0.12   # A: 固定 12%

B_ATR_MULT    = 2.5    # B: ATR × 2.5
B_MIN_STOP    = 0.08
B_MAX_STOP    = 0.35

# C: 混合 —— 阈值
C_LOW_ATR_PCT  = 0.05   # ATR% < 5%  → 低波动
C_HIGH_ATR_PCT = 0.15   # ATR% > 15% → 高波动
C_LOW_FIXED    = 0.08   # 低波动用固定 8%
C_MID_ATR_MULT = 2.5    # 中波动 ATR×2.5
C_HIGH_ATR_MULT= 2.0    # 高波动 ATR×2.0（更宽）
C_HIGH_MAX     = 0.40   # 高波动上限 40%
C_MIN_STOP     = 0.08
C_MID_MAX      = 0.35

# ── 快照数据 ──────────────────────────────────────────────────────────
FUNDAMENTAL = {
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
SENTIMENT = {
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

# ── 工具函数 ──────────────────────────────────────────────────────────
def get_snap(tl, date):
    v = tl[0]["score"]
    for e in tl:
        if str(date.date()) >= e["from"]: v = e["score"]
        else: break
    return v

def calc_rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=p-1, min_periods=p).mean()
    l = (-d.clip(upper=0)).ewm(com=p-1, min_periods=p).mean()
    return 100 - 100/(1+g/l)

def calc_macd(s):
    m = s.ewm(span=12,adjust=False).mean() - s.ewm(span=26,adjust=False).mean()
    return m - m.ewm(span=9,adjust=False).mean()

def calc_atr(df, p=14):
    hi,lo,cl = df["High"],df["Low"],df["Close"]
    tr = pd.concat([(hi-lo),(hi-cl.shift(1)).abs(),(lo-cl.shift(1)).abs()],axis=1).max(axis=1)
    return tr.ewm(com=p-1,min_periods=p).mean()

def tech_score(row):
    s = 0
    if   row.RSI<30: s+=3
    elif row.RSI<45: s+=1
    elif row.RSI>70: s-=3
    elif row.RSI>55: s-=1
    if   row.MH>0 and row.MH_p<=0: s+=3
    elif row.MH<0 and row.MH_p>=0: s-=3
    elif row.MH>0: s+=1
    else: s-=1
    if   row.MA5>row.MA20>row.MA60: s+=2
    elif row.MA5<row.MA20<row.MA60: s-=2
    if   row.Close>row.MA20 and row.Cp<=row.MA20p: s+=1
    elif row.Close<row.MA20 and row.Cp>=row.MA20p: s-=1
    return float(np.clip(s,-10,10))

def pos_ratio(score):
    if score>=5: return 1.0
    elif score>=3: return 0.6
    return 0.3

def load(ticker):
    sym = ticker.replace(".HK","")
    fp  = os.path.join(CACHE_DIR, f"{sym}.csv")
    if os.path.exists(fp) and not FORCE_REFRESH:
        df = pd.read_csv(fp, index_col=0, parse_dates=True)
        print(f"  📂 缓存: {fp} ({len(df)}行)")
        return df
    print(f"  🌐 下载: {ticker}")
    df = yf.download(ticker, period=PERIOD, auto_adjust=True, progress=False)
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
    df.to_csv(fp)
    return df

def prep(ticker):
    df = load(ticker)
    if df is None or len(df)<60: return None
    c = df["Close"]
    df["RSI"]  = calc_rsi(c)
    h = calc_macd(c)
    df["MH"]   = h; df["MH_p"] = h.shift(1)
    for p in [5,20,60]: df[f"MA{p}"] = c.rolling(p).mean()
    df["MA20p"]= df["MA20"].shift(1); df["Cp"] = c.shift(1)
    df["Vol20"]= df["Volume"].rolling(20).mean()
    df["ATR"]  = calc_atr(df)
    return df.dropna()

# ── 混合策略 C 的止损参数选择 ─────────────────────────────────────────
def c_stop_params(avg_atr_pct):
    """根据股票历史ATR波动率自动决定止损方式"""
    if avg_atr_pct < C_LOW_ATR_PCT:
        return "fixed", C_LOW_FIXED, C_LOW_FIXED, "低波动→固定止损"
    elif avg_atr_pct < C_HIGH_ATR_PCT:
        return "atr",   C_MID_ATR_MULT, C_MID_MAX, "中波动→ATR×2.5"
    else:
        return "atr",   C_HIGH_ATR_MULT, C_HIGH_MAX, "高波动→ATR×2.0"

# ── 通用模拟引擎 ──────────────────────────────────────────────────────
def simulate(name, df, mode="A", c_avg_atr_pct=None):
    """
    mode: 'A'=固定止损12%, 'B'=ATR动态, 'C'=混合自适应
    """
    capital, position, entry = INITIAL_CAPITAL, 0, 0.0
    high_price, trail_pct = 0.0, 0.0
    trades = []

    # C 版预先确定止损类型（全局一致，模拟真实部署）
    c_mode, c_mult, c_max, c_note = ("fixed",0,0,"") if mode!="C" else c_stop_params(c_avg_atr_pct)

    for date, row in df.iterrows():
        f     = get_snap(FUNDAMENTAL[name], date)
        s     = get_snap(SENTIMENT[name], date)
        t     = tech_score(row)
        score = W_TECH*t + W_FUND*f + W_SENT*s
        price = float(row["Close"])
        vol   = float(row["Volume"])
        vol20 = float(row["Vol20"])

        # 买入
        if score >= BUY_THRESH and position == 0 and capital > price:
            if vol >= vol20 * VOL_CONFIRM:
                ratio  = pos_ratio(score)
                shares = int(capital * ratio / price)
                if shares > 0:
                    position, entry, high_price = shares, price, price
                    capital -= shares * price

                    # 确定止损幅度
                    if mode == "A":
                        trail_pct = A_FIXED_STOP
                        note = f"仓{ratio*100:.0f}% 固定止损{trail_pct*100:.0f}%"
                    elif mode == "B":
                        raw = float(row["ATR"]) * B_ATR_MULT / price
                        trail_pct = float(np.clip(raw, B_MIN_STOP, B_MAX_STOP))
                        note = f"仓{ratio*100:.0f}% ATR止损{trail_pct*100:.1f}%"
                    else:  # C
                        if c_mode == "fixed":
                            trail_pct = c_mult if c_mult else C_LOW_FIXED
                            note = f"仓{ratio*100:.0f}% {c_note} {trail_pct*100:.0f}%"
                        else:
                            raw = float(row["ATR"]) * c_mult / price
                            trail_pct = float(np.clip(raw, C_MIN_STOP, c_max))
                            note = f"仓{ratio*100:.0f}% {c_note} {trail_pct*100:.1f}%"

                    trades.append({"操作":"买入","日期":date.date(),"价格":round(price,4),
                                   "股数":shares,"评分":round(score,2),"备注":note})

        elif position > 0:
            high_price = max(high_price, price)
            stop_price = high_price * (1 - trail_pct)
            if price <= stop_price or score <= SELL_THRESH:
                pnl = position*(price-entry); pct = pnl/(position*entry)*100
                reason = (f"止损 高{high_price:.3f}→线{stop_price:.3f}"
                          if price<=stop_price else f"评分出({score:.1f})")
                capital += position*price
                trades.append({"操作":"卖出","日期":date.date(),"价格":round(price,4),
                               "股数":position,"评分":round(score,2),
                               "盈亏%":f"{pct:+.1f}%","备注":reason})
                position, high_price, trail_pct = 0, 0.0, 0.0

    last  = float(df["Close"].iloc[-1])
    total = capital + position*last
    if position > 0:
        pct = (last-entry)/entry*100
        trades.append({"操作":"未平仓","日期":"持仓中","价格":round(last,4),
                       "股数":position,"评分":"-","盈亏%":f"{pct:+.1f}%","备注":"-"})
    return total, trades

# ── 主流程 ────────────────────────────────────────────────────────────
def run_abc(name, ticker):
    print(f"\n{'='*72}")
    print(f"  {name} ({ticker})")
    print(f"{'='*72}")
    df = prep(ticker)
    if df is None:
        print("  ⚠️  数据不足，跳过")
        return None

    avg_atr_pct = float(df["ATR"].mean() / df["Close"].mean())
    bh = (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1)*100
    c_mode, c_mult, c_max, c_note = c_stop_params(avg_atr_pct)
    est_stop = (C_LOW_FIXED if c_mode=="fixed"
                else float(np.clip(df["ATR"].mean()*c_mult/df["Close"].mean(), C_MIN_STOP, c_max)))
    print(f"  ATR均值: {avg_atr_pct*100:.1f}%  C策略选择: [{c_note}]  估算止损: {est_stop*100:.1f}%")
    print(f"  买入持有收益: {bh:+.1f}%")

    tA, trA = simulate(name, df, "A")
    tB, trB = simulate(name, df, "B")
    tC, trC = simulate(name, df, "C", avg_atr_pct)
    rA = (tA-INITIAL_CAPITAL)/INITIAL_CAPITAL*100
    rB = (tB-INITIAL_CAPITAL)/INITIAL_CAPITAL*100
    rC = (tC-INITIAL_CAPITAL)/INITIAL_CAPITAL*100

    for label, trades in [("A 固定止损12%", trA),("B ATR动态", trB),("C 混合自适应", trC)]:
        print(f"\n  【版本{label}】")
        if not trades: print("    无信号"); continue
        cols = [c for c in ["操作","日期","价格","股数","评分","盈亏%","备注"]
                if c in pd.DataFrame(trades).columns]
        print(pd.DataFrame(trades)[cols].to_string(index=False))

    best = max([("A",rA),("B",rB),("C",rC)], key=lambda x:x[1])
    print(f"\n  {'':20} {'A 固定12%':>11} {'B ATR动态':>11} {'C 混合':>11} {'买入持有':>10}")
    print(f"  {'策略总收益':<20} {rA:>+10.1f}% {rB:>+10.1f}% {rC:>+10.1f}% {bh:>+9.1f}%")
    print(f"  {'超额收益α':<20} {rA-bh:>+10.1f}% {rB-bh:>+10.1f}% {rC-bh:>+10.1f}%")
    nA = len([t for t in trA if t["操作"] in ("买入","卖出")])
    nB = len([t for t in trB if t["操作"] in ("买入","卖出")])
    nC = len([t for t in trC if t["操作"] in ("买入","卖出")])
    print(f"  {'交易次数':<20} {nA:>11} {nB:>11} {nC:>11}")
    print(f"  {'🏆 本轮胜出':<20} {'★' if best[0]=='A' else '':>11} {'★' if best[0]=='B' else '':>11} {'★' if best[0]=='C' else '':>11}")

    return {"name":name, "A":rA, "B":rB, "C":rC, "BH":bh,
            "atr":avg_atr_pct*100, "c_note":c_note}


if __name__ == "__main__":
    print("\n🔬 港股 AI v5 — 三版本 A/B/C 对比回测")
    print(f"   A: 固定止损{A_FIXED_STOP*100:.0f}%（全局）")
    print(f"   B: ATR×{B_ATR_MULT}动态止损（{B_MIN_STOP*100:.0f}%~{B_MAX_STOP*100:.0f}%）")
    print(f"   C: 混合自适应 — ATR<5%→固定8% | 5~15%→ATR×2.5 | >15%→ATR×2.0")
    print(f"   仓位分级: 评分1.5-3→30% | 3-5→60% | >5→100%\n")

    results = []
    for i, (name, ticker) in enumerate(STOCKS.items()):
        if i > 0: time.sleep(3)
        r = run_abc(name, ticker)
        if r: results.append(r)

    if results:
        print(f"\n{'='*72}")
        print("  📋 最终三版本汇总")
        print(f"{'='*72}")
        print(f"  {'股票':<12} {'ATR%':>6} {'C策略':<18} {'A':>9} {'B':>9} {'C':>9} {'买持':>9}")
        print(f"  {'-'*70}")
        for r in results:
            marks = {k:"★" for k in ["A","B","C"] if r[k]==max(r["A"],r["B"],r["C"])}
            print(f"  {r['name']:<12} {r['atr']:>5.1f}%  {r['c_note']:<18}"
                  f" {r['A']:>+8.1f}%{marks.get('A',''):1}"
                  f" {r['B']:>+8.1f}%{marks.get('B',''):1}"
                  f" {r['C']:>+8.1f}%{marks.get('C',''):1}"
                  f" {r['BH']:>+8.1f}%")
        avg = {k: np.mean([r[k] for r in results]) for k in ["A","B","C","BH"]}
        best_avg = max("A","B","C", key=lambda k: avg[k])
        marks = {k:"★" for k in ["A","B","C"] if k==best_avg}
        print(f"  {'平均':<12} {'':>6}  {'':18}"
              f" {avg['A']:>+8.1f}%{marks.get('A',''):1}"
              f" {avg['B']:>+8.1f}%{marks.get('B',''):1}"
              f" {avg['C']:>+8.1f}%{marks.get('C',''):1}"
              f" {avg['BH']:>+8.1f}%")
        print()
