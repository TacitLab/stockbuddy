"""
港股 AI 综合评分系统 v3 - A/B 回测对比
A: 原版（固定阈值 + 全仓）
B: 优化版（移动止损 + 仓位分级 + 成交量确认）
"""

import yfinance as yf
import pandas as pd
import numpy as np
import time
import warnings
warnings.filterwarnings('ignore')

# ── 参数 ──────────────────────────────────────────────────────────────
STOCKS = {
    "平安好医生": "1833.HK",
    "叮当健康":   "9886.HK",
    "中原建业":   "9982.HK",
}
PERIOD = "2y"
INITIAL_CAPITAL = 10000.0  # HKD

W_TECH        = 0.50
W_FUNDAMENTAL = 0.30
W_SENTIMENT   = 0.20

# 版本 A：固定阈值
A_BUY_THRESH  =  1.5
A_SELL_THRESH = -1.5

# 版本 B：优化参数
B_BUY_THRESH       =  1.5   # 买入阈值不变
B_SELL_THRESH      = -1.5   # 评分卖出阈值
B_TRAILING_STOP    =  0.12  # 移动止损：从最高点回撤12%触发卖出
B_VOL_CONFIRM      =  1.2   # 成交量确认：买入日成交量需 > 20日均量 × 1.2
# 仓位分级（按综合评分）
def position_ratio(score):
    if score >= 5:   return 1.0   # 满仓
    elif score >= 3: return 0.6   # 六成仓
    else:            return 0.3   # 三成仓

# ── 快照数据 ──────────────────────────────────────────────────────────
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

# ── 工具函数 ──────────────────────────────────────────────────────────
def get_snapshot(timeline, date):
    score = timeline[0]["score"]
    for e in timeline:
        if str(date.date()) >= e["from"]:
            score = e["score"]
        else:
            break
    return score

def calc_rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=p-1, min_periods=p).mean()
    l = (-d.clip(upper=0)).ewm(com=p-1, min_periods=p).mean()
    return 100 - 100 / (1 + g / l)

def calc_macd(s, fast=12, slow=26, sig=9):
    ef = s.ewm(span=fast, adjust=False).mean()
    es = s.ewm(span=slow, adjust=False).mean()
    m  = ef - es
    sl = m.ewm(span=sig, adjust=False).mean()
    return m, sl, m - sl

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

def prepare_df(ticker):
    df = yf.download(ticker, period=PERIOD, auto_adjust=True, progress=False)
    if df.empty or len(df) < 60:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    c = df["Close"]
    df["RSI"]      = calc_rsi(c)
    _, _, h        = calc_macd(c)
    df["MACD_h"]   = h
    df["MACD_h_p"] = h.shift(1)
    for p in [5, 20, 60]:
        df[f"MA{p}"] = c.rolling(p).mean()
    df["MA20_p"]   = df["MA20"].shift(1)
    df["Close_p"]  = c.shift(1)
    df["Vol20"]    = df["Volume"].rolling(20).mean()  # 20日均量
    return df.dropna()

# ── 版本 A：原版回测 ─────────────────────────────────────────────────
def run_A(name, df):
    capital, position, entry_price = INITIAL_CAPITAL, 0, 0.0
    trades = []
    for date, row in df.iterrows():
        f = get_snapshot(FUNDAMENTAL_TIMELINE[name], date)
        s = get_snapshot(SENTIMENT_TIMELINE[name], date)
        t = score_tech(row)
        score = W_TECH * t + W_FUNDAMENTAL * f + W_SENTIMENT * s
        price = float(row["Close"])

        if score >= A_BUY_THRESH and position == 0 and capital > price:
            shares = int(capital / price)
            position, entry_price = shares, price
            capital -= shares * price
            trades.append(("买入", date.date(), price, shares, round(score,2), None))

        elif score <= A_SELL_THRESH and position > 0:
            pnl = position * (price - entry_price)
            capital += position * price
            trades.append(("卖出", date.date(), price, position, round(score,2),
                           f"{pnl/abs(position*entry_price)*100:+.1f}%"))
            position = 0

    last = float(df["Close"].iloc[-1])
    total = capital + position * last
    if position > 0:
        pnl = position * (last - entry_price)
        trades.append(("未平仓", "持仓中", last, position, "-",
                       f"{pnl/abs(position*entry_price)*100:+.1f}%"))
    return total, trades

# ── 版本 B：优化版回测 ───────────────────────────────────────────────
def run_B(name, df):
    capital, position, entry_price = INITIAL_CAPITAL, 0, 0.0
    highest_price = 0.0  # 持仓期间最高价（移动止损用）
    trades = []

    for date, row in df.iterrows():
        f = get_snapshot(FUNDAMENTAL_TIMELINE[name], date)
        s = get_snapshot(SENTIMENT_TIMELINE[name], date)
        t = score_tech(row)
        score = W_TECH * t + W_FUNDAMENTAL * f + W_SENTIMENT * s
        price = float(row["Close"])
        vol   = float(row["Volume"])
        vol20 = float(row["Vol20"])

        # ── 买入逻辑（加成交量确认）──
        if score >= B_BUY_THRESH and position == 0 and capital > price:
            vol_ok = vol >= vol20 * B_VOL_CONFIRM  # 成交量放大确认
            if vol_ok:
                ratio  = position_ratio(score)       # 仓位分级
                invest = capital * ratio
                shares = int(invest / price)
                if shares > 0:
                    position, entry_price = shares, price
                    highest_price = price
                    capital -= shares * price
                    trades.append(("买入", date.date(), price, shares,
                                   round(score,2), f"仓位{ratio*100:.0f}%", f"量比{vol/vol20:.1f}x"))

        # ── 持仓管理 ──
        elif position > 0:
            highest_price = max(highest_price, price)
            trailing_triggered = price <= highest_price * (1 - B_TRAILING_STOP)
            score_triggered    = score <= B_SELL_THRESH

            if trailing_triggered or score_triggered:
                reason = f"移动止损({price:.3f}≤{highest_price*(1-B_TRAILING_STOP):.3f})" \
                         if trailing_triggered else f"评分卖出({score:.1f})"
                pnl = position * (price - entry_price)
                capital += position * price
                trades.append(("卖出", date.date(), price, position,
                               round(score,2), reason,
                               f"{pnl/abs(position*entry_price)*100:+.1f}%"))
                position, highest_price = 0, 0.0

    last = float(df["Close"].iloc[-1])
    total = capital + position * last
    if position > 0:
        pnl = position * (last - entry_price)
        trades.append(("未平仓", "持仓中", last, position, "-", "-",
                       f"{pnl/abs(position*entry_price)*100:+.1f}%"))
    return total, trades

# ── 主流程 ────────────────────────────────────────────────────────────
def run_ab_test(name, ticker):
    print(f"\n{'='*68}")
    print(f"  {name} ({ticker})")
    print(f"{'='*68}")
    df = prepare_df(ticker)
    if df is None:
        print("  ⚠️  数据不足，跳过")
        return None

    first_price = float(df["Close"].iloc[0])
    last_price  = float(df["Close"].iloc[-1])
    bh_return   = (last_price / first_price - 1) * 100

    total_A, trades_A = run_A(name, df)
    total_B, trades_B = run_B(name, df)

    ret_A = (total_A - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    ret_B = (total_B - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    print(f"\n  【版本A 原版】交易记录:")
    for t in trades_A:
        print(f"    {str(t[1]):<12} {t[0]:<4} 价:{t[2]:.4f} 股:{t[3]:>6} 分:{t[4]}  {t[5] or ''}")

    print(f"\n  【版本B 优化版】交易记录:")
    for t in trades_B:
        extra = "  ".join(str(x) for x in t[5:] if x)
        print(f"    {str(t[1]):<12} {t[0]:<4} 价:{t[2]:.4f} 股:{t[3]:>6} 分:{t[4]}  {extra}")

    print(f"\n  {'':20} {'版本A(原版)':>12} {'版本B(优化)':>12} {'买入持有':>10}")
    print(f"  {'策略总收益':<20} {ret_A:>+11.1f}% {ret_B:>+11.1f}% {bh_return:>+9.1f}%")
    print(f"  {'超额收益α':<20} {ret_A-bh_return:>+11.1f}% {ret_B-bh_return:>+11.1f}%")
    print(f"  {'交易次数':<20} {len([t for t in trades_A if t[0] in ('买入','卖出')]):>12} "
          f"{len([t for t in trades_B if t[0] in ('买入','卖出')]):>12}")
    print(f"  {'B vs A 提升':<20} {'':>12} {ret_B-ret_A:>+11.1f}%")

    return {"name": name, "A": ret_A, "B": ret_B, "BH": bh_return,
            "A_trades": len([t for t in trades_A if t[0] in ('买入','卖出')]),
            "B_trades": len([t for t in trades_B if t[0] in ('买入','卖出')])}


if __name__ == "__main__":
    print("\n🔬 港股 AI 评分系统 A/B 回测对比")
    print("   A: 固定阈值 + 全仓出入")
    print("   B: 移动止损12% + 仓位分级(30/60/100%) + 成交量确认(1.2x)")
    print(f"   数据周期: {PERIOD} | 初始资金: HKD {INITIAL_CAPITAL:,.0f}/股\n")

    results = []
    for i, (name, ticker) in enumerate(STOCKS.items()):
        if i > 0: time.sleep(5)
        r = run_ab_test(name, ticker)
        if r: results.append(r)

    if results:
        print(f"\n{'='*68}")
        print("  📋 A/B 汇总对比")
        print(f"{'='*68}")
        print(f"  {'股票':<12} {'A收益':>9} {'B收益':>9} {'买持':>9} {'B-A':>8} {'A笔数':>6} {'B笔数':>6}")
        print(f"  {'-'*64}")
        for r in results:
            winner = "B✅" if r["B"] > r["A"] else "A✅"
            print(f"  {r['name']:<12} {r['A']:>+8.1f}% {r['B']:>+8.1f}% {r['BH']:>+8.1f}% "
                  f"{r['B']-r['A']:>+7.1f}% {r['A_trades']:>6} {r['B_trades']:>6}  {winner}")

        avg_a  = np.mean([r["A"]  for r in results])
        avg_b  = np.mean([r["B"]  for r in results])
        avg_bh = np.mean([r["BH"] for r in results])
        print(f"  {'平均':<12} {avg_a:>+8.1f}% {avg_b:>+8.1f}% {avg_bh:>+8.1f}% {avg_b-avg_a:>+7.1f}%")
        print()
