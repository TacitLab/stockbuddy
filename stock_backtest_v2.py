"""
港股 AI 综合评分系统 v2 - 回测框架
三维度加权评分：技术面(50%) + 基本面(30%) + 舆情(20%)
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
INITIAL_CAPITAL = 10000  # HKD

# 三维度权重
W_TECH       = 0.50
W_FUNDAMENTAL = 0.30
W_SENTIMENT   = 0.20

# ── 基本面快照（手动录入，按季度/年更新）────────────────────────────
# 格式：每条记录 {"from": "YYYY-MM-DD", "score": float, "note": str}
# 分数区间 -10 ~ +10
FUNDAMENTAL_TIMELINE = {
    "平安好医生": [
        {"from": "2024-01-01", "score": -3.0, "note": "持续亏损，估值偏高"},
        {"from": "2024-08-01", "score": -1.0, "note": "2024中报净利润转正，估值仍高"},
        {"from": "2025-01-01", "score":  0.0, "note": "盈利改善，医险协同深化"},
        {"from": "2025-08-01", "score":  1.0, "note": "营收+13.6%，经调整净利润+45.7%"},
    ],
    "叮当健康": [
        {"from": "2024-01-01", "score": -3.0, "note": "连续亏损"},
        {"from": "2024-06-01", "score": -2.0, "note": "亏损收窄中"},
        {"from": "2025-01-01", "score": -1.0, "note": "亏损继续收窄，毛利率提升"},
        {"from": "2025-09-01", "score":  1.0, "note": "2025全年调整后盈利1070万，拐点初现"},
    ],
    "中原建业": [
        {"from": "2024-01-01", "score": -3.0, "note": "地产下行，代建收入减少"},
        {"from": "2024-06-01", "score": -4.0, "note": "停牌风险，执行董事辞任"},
        {"from": "2025-01-01", "score": -4.0, "note": "盈警：净利润同比-28~32%"},
        {"from": "2025-10-01", "score": -5.0, "note": "地产持续低迷，无机构覆盖"},
    ],
}

# ── 舆情快照（手动录入）────────────────────────────────────────────
SENTIMENT_TIMELINE = {
    "平安好医生": [
        {"from": "2024-01-01", "score": -1.0, "note": "行业承压"},
        {"from": "2024-10-01", "score":  1.0, "note": "互联网医疗政策边际改善"},
        {"from": "2025-01-01", "score":  2.0, "note": "大摩买入评级，目标价19.65"},
        {"from": "2026-01-01", "score":  3.0, "note": "主力资金持续净流入，连锁药房扩展"},
    ],
    "叮当健康": [
        {"from": "2024-01-01", "score": -2.0, "note": "市场悲观，连亏"},
        {"from": "2024-08-01", "score": -1.0, "note": "关注度低"},
        {"from": "2025-04-01", "score":  1.0, "note": "互联网首诊试点，4月新规利好"},
        {"from": "2025-10-01", "score":  2.0, "note": "雪球社区关注回升，创新药布局"},
    ],
    "中原建业": [
        {"from": "2024-01-01", "score": -2.0, "note": "地产悲观情绪"},
        {"from": "2024-06-01", "score": -3.0, "note": "管理层动荡，停牌"},
        {"from": "2025-01-01", "score": -3.0, "note": "无投行覆盖，成交极低"},
        {"from": "2025-10-01", "score": -4.0, "note": "发盈警，市场信心极低"},
    ],
}

# ── 工具函数 ──────────────────────────────────────────────────────────

def get_snapshot_score(timeline, date):
    """根据日期获取对应时间段的快照分数"""
    score = timeline[0]["score"]
    for entry in timeline:
        if str(date.date()) >= entry["from"]:
            score = entry["score"]
        else:
            break
    return score

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line, macd - signal_line

def score_technical(row):
    """技术面评分 -10 ~ +10"""
    score = 0
    # RSI
    if row["RSI"] < 30:   score += 3
    elif row["RSI"] < 45: score += 1
    elif row["RSI"] > 70: score -= 3
    elif row["RSI"] > 55: score -= 1
    # MACD 金叉/死叉
    if   row["MACD_hist"] > 0 and row["MACD_hist_prev"] <= 0: score += 3
    elif row["MACD_hist"] < 0 and row["MACD_hist_prev"] >= 0: score -= 3
    elif row["MACD_hist"] > 0: score += 1
    else:                      score -= 1
    # 均线排列
    if   row["MA5"] > row["MA20"] > row["MA60"]: score += 2
    elif row["MA5"] < row["MA20"] < row["MA60"]: score -= 2
    # MA20 突破/跌破
    if   row["Close"] > row["MA20"] and row["Close_prev"] <= row["MA20_prev"]: score += 1
    elif row["Close"] < row["MA20"] and row["Close_prev"] >= row["MA20_prev"]: score -= 1
    return float(np.clip(score, -10, 10))

# ── 回测主函数 ────────────────────────────────────────────────────────

def backtest(name, ticker):
    print(f"\n{'='*65}")
    print(f"  回测: {name} ({ticker})")
    print(f"{'='*65}")

    df = yf.download(ticker, period=PERIOD, auto_adjust=True, progress=False)
    if df.empty or len(df) < 60:
        print("  ⚠️  数据不足，跳过")
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)

    close = df["Close"]
    df["RSI"] = calc_rsi(close)
    macd, sig_line, hist = calc_macd(close)
    df["MACD_hist"] = hist
    df["MACD_hist_prev"] = hist.shift(1)
    for p in [5, 20, 60]:
        df[f"MA{p}"] = close.rolling(p).mean()
    df["MA20_prev"]  = df["MA20"].shift(1)
    df["Close_prev"] = close.shift(1)
    df = df.dropna()

    # 加入三维度评分
    tech_scores  = []
    fund_scores  = []
    sent_scores  = []
    total_scores = []

    for date, row in df.iterrows():
        t = score_technical(row)
        f = get_snapshot_score(FUNDAMENTAL_TIMELINE[name], date)
        s = get_snapshot_score(SENTIMENT_TIMELINE[name], date)
        combined = W_TECH * t + W_FUNDAMENTAL * f + W_SENTIMENT * s
        tech_scores.append(t)
        fund_scores.append(f)
        sent_scores.append(s)
        total_scores.append(combined)

    df["Tech"]     = tech_scores
    df["Fund"]     = fund_scores
    df["Sent"]     = sent_scores
    df["Score"]    = total_scores

    # 买卖阈值：综合评分 >= 1.5 买入；<= -1.5 卖出
    BUY_THRESH  =  1.5
    SELL_THRESH = -1.5
    df["Signal"] = 0
    df.loc[df["Score"] >= BUY_THRESH,  "Signal"] =  1
    df.loc[df["Score"] <= SELL_THRESH, "Signal"] = -1

    # ── 模拟交易 ──
    capital    = float(INITIAL_CAPITAL)
    position   = 0
    entry_price = 0.0
    trades     = []

    for date, row in df.iterrows():
        price = float(row["Close"])
        sig   = int(row["Signal"])

        if sig == 1 and position == 0 and capital > price:
            shares = int(capital / price)
            position = shares
            entry_price = price
            capital -= shares * price
            trades.append({
                "日期": date.date(), "操作": "买入",
                "价格": round(price, 4), "股数": shares,
                "综合分": round(float(row["Score"]), 2),
                "技术": round(float(row["Tech"]), 1),
                "基本面": round(float(row["Fund"]), 1),
                "舆情": round(float(row["Sent"]), 1),
            })

        elif sig == -1 and position > 0:
            revenue = position * price
            pnl     = revenue - position * entry_price
            pnl_pct = pnl / (position * entry_price) * 100
            capital += revenue
            trades.append({
                "日期": date.date(), "操作": "卖出",
                "价格": round(price, 4), "股数": position,
                "综合分": round(float(row["Score"]), 2),
                "技术": round(float(row["Tech"]), 1),
                "基本面": round(float(row["Fund"]), 1),
                "舆情": round(float(row["Sent"]), 1),
                "盈亏HKD": round(pnl, 2),
                "盈亏%": f"{pnl_pct:+.1f}%",
            })
            position    = 0
            entry_price = 0.0

    last_price = float(df["Close"].iloc[-1])
    if position > 0:
        unrealized = position * (last_price - entry_price)
        capital_total = capital + position * last_price
        trades.append({
            "日期": "持仓中", "操作": "未平仓",
            "价格": round(last_price, 4), "股数": position,
            "未实现盈亏HKD": round(unrealized, 2),
        })
    else:
        capital_total = capital

    strategy_return  = (capital_total - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    buy_hold_return  = (last_price / float(df["Close"].iloc[0]) - 1) * 100

    # ── 输出 ──
    print(f"\n  📊 交易记录:")
    tdf = pd.DataFrame(trades)
    if not tdf.empty:
        print(tdf.to_string(index=False))
    else:
        print("  无交易信号")

    # 评分分布统计
    print(f"\n  📉 评分分布（综合）:")
    bins = [-10, -3, -1.5, 0, 1.5, 3, 10]
    labels = ["强卖[-10,-3]","卖[-3,-1.5]","中性[-1.5,0]","中性[0,1.5]","买[1.5,3]","强买[3,10]"]
    score_ser = df["Score"]
    for label, cnt in zip(labels, np.histogram(score_ser, bins=bins)[0]):
        bar = "█" * int(cnt / max(1, len(df)) * 40)
        print(f"  {label:>18}: {bar} ({cnt}天)")

    print(f"\n  📈 回测结果汇总:")
    print(f"  初始资金:       HKD {INITIAL_CAPITAL:>10,.0f}")
    print(f"  最终资金:       HKD {capital_total:>10,.2f}")
    print(f"  策略总收益:     {strategy_return:>+10.1f}%")
    print(f"  买入持有收益:   {buy_hold_return:>+10.1f}%  （同期）")
    print(f"  超额收益(α):   {strategy_return - buy_hold_return:>+10.1f}%")
    print(f"  触发交易次数:   {len([t for t in trades if t.get('操作') in ['买入','卖出']]):>10}")

    return {
        "name": name,
        "strategy": strategy_return,
        "buy_hold": buy_hold_return,
        "alpha": strategy_return - buy_hold_return,
        "trades": len([t for t in trades if t.get("操作") in ["买入", "卖出"]]),
    }


# ── 主入口 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n🔬 港股 AI 综合评分系统 v2 — 历史回测")
    print(f"   权重: 技术面 {W_TECH*100:.0f}% | 基本面 {W_FUNDAMENTAL*100:.0f}% | 舆情 {W_SENTIMENT*100:.0f}%")
    print(f"   买入阈值: ≥1.5 | 卖出阈值: ≤-1.5 | 数据周期: {PERIOD}\n")

    results = []
    for i, (name, ticker) in enumerate(STOCKS.items()):
        if i > 0:
            time.sleep(3)  # 避免 yfinance 限速
        r = backtest(name, ticker)
        if r:
            results.append(r)

    if results:
        print(f"\n{'='*65}")
        print("  📋 三股票综合汇总")
        print(f"{'='*65}")
        print(f"  {'股票':<12} {'策略收益':>10} {'买持收益':>10} {'超额收益α':>10} {'交易次数':>8}")
        print(f"  {'-'*54}")
        for r in results:
            flag = "✅" if r["alpha"] > 0 else "❌"
            print(f"  {r['name']:<12} {r['strategy']:>+9.1f}% {r['buy_hold']:>+9.1f}% {r['alpha']:>+9.1f}% {r['trades']:>6} {flag}")
        print()
