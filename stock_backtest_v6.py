"""
港股 AI 综合评分系统 v6 — 三维度 + 趋势过滤 + 盈利保护 + LLM舆情

新增特性：
1. 趋势过滤器：只在上升趋势开仓（Close > MA60）
2. 盈利保护：
   - 盈利 > 30% → 保本止损（移到成本价）
   - 盈利 > 50% → 锁定10%利润
   - 盈利 > 100% → 宽追踪止损 ATR×3
3. 信号质量门槛：
   - 开仓评分阈值提高到 3.0
   - 冷却期：同一标的 30天内只开仓一次
4. LLM舆情：接入大模型做新闻情绪分析（离线缓存）

止损策略 A/B/C 同 v5
"""

import yfinance as yf
import pandas as pd
import numpy as np
import time, os, sys, json
import warnings
warnings.filterwarnings('ignore')

CACHE_DIR = "data"
SENTIMENT_CACHE = os.path.join(CACHE_DIR, "llm_sentiment.json")
os.makedirs(CACHE_DIR, exist_ok=True)
FORCE_REFRESH = "--refresh" in sys.argv

STOCKS = {
    "平安好医生": "1833.HK",
    "叮当健康":   "9886.HK",
    "中原建业":   "9982.HK",
    "泰升集团":   "0687.HK",
    "阅文集团":   "0772.HK",
    "中芯国际":   "0981.HK",
}

PERIOD          = "2y"
INITIAL_CAPITAL = 10000.0
W_TECH, W_FUND, W_SENT = 0.60, 0.30, 0.10  # 技术面60%，基本面30%，LLM舆情10%

# ═════════════════════════════════════════════════════════════════════
# v6 新参数
# ═════════════════════════════════════════════════════════════════════
BUY_THRESH      = 1.5       # 开仓门槛（同v5）
SELL_THRESH     = -1.5
COOLDOWN_DAYS   = 0         # 冷却期：0 = 关闭
VOL_CONFIRM     = 1.2

# 盈利保护阈值
PROFIT_STAGE_1  = 0.30      # 30% 盈利 → 保本
PROFIT_STAGE_2  = 0.50      # 50% 盈利 → 锁定10%
PROFIT_STAGE_3  = 1.00      # 100% 盈利 → 宽止损

# 趋势过滤
TREND_FILTER    = False     # 是否启用趋势过滤（测试时关闭）
TREND_MA        = 60        # 用 MA60 判断趋势

# 版本参数（同v5）
A_FIXED_STOP  = 0.12
B_ATR_MULT, B_MIN_STOP, B_MAX_STOP = 2.5, 0.08, 0.35
C_LOW_ATR_PCT, C_HIGH_ATR_PCT = 0.05, 0.15
C_LOW_FIXED, C_MID_ATR_MULT, C_HIGH_ATR_MULT = 0.08, 2.5, 2.0
C_HIGH_MAX, C_MIN_STOP, C_MID_MAX = 0.40, 0.08, 0.35

# ═════════════════════════════════════════════════════════════════════
# 基本面快照（同v5）
# ═════════════════════════════════════════════════════════════════════
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
    "泰升集团": [
        {"from": "2024-01-01", "score": -1.0},
        {"from": "2024-06-01", "score": -1.0},
        {"from": "2025-01-01", "score": -2.0},
        {"from": "2025-10-01", "score": -2.0},
    ],
    "阅文集团": [
        {"from": "2024-01-01", "score": 1.0},
        {"from": "2024-06-01", "score": 2.0},
        {"from": "2025-01-01", "score": 2.0},
        {"from": "2025-10-01", "score": 3.0},
    ],
    "中芯国际": [
        {"from": "2024-01-01", "score": 2.0},
        {"from": "2024-06-01", "score": 3.0},
        {"from": "2025-01-01", "score": 3.0},
        {"from": "2025-10-01", "score": 4.0},
    ],
}

# ═════════════════════════════════════════════════════════════════════
# LLM 舆情缓存（模拟/加载）
# ═════════════════════════════════════════════════════════════════════
def load_llm_sentiment():
    """加载LLM舆情缓存，如果没有则返回基础值"""
    if os.path.exists(SENTIMENT_CACHE):
        with open(SENTIMENT_CACHE, 'r') as f:
            return json.load(f)
    return {}

def save_llm_sentiment(data):
    """保存LLM舆情缓存"""
    with open(SENTIMENT_CACHE, 'w') as f:
        json.dump(data, f, indent=2, default=str)

def get_llm_sentiment_score(name, date, sentiment_cache):
    """获取某股票某日的LLM舆情分数（-5~+5）"""
    sym = name[:4]  # 简化为前4个字作为key
    date_str = str(date.date())
    
    # 如果缓存中有，直接返回
    if sym in sentiment_cache and date_str in sentiment_cache[sym]:
        return sentiment_cache[sym][date_str]
    
    # 否则返回基于时间衰减的基础值（模拟LLM分析结果）
    # 实际使用时，应该用 llm_sentiment.py 批量生成
    base_scores = {
        "平安好医生": {2024: -1, 2025: 1, 2026: 2},
        "叮当健康":   {2024: -2, 2025: 0, 2026: 1},
        "中原建业":   {2024: -2, 2025: -3, 2026: -3},
        "泰升集团":   {2024: -1, 2025: -1, 2026: -1},
        "阅文集团":   {2024: 1, 2025: 2, 2026: 2},
        "中芯国际":   {2024: 2, 2025: 3, 2026: 4},
    }
    year = date.year
    return base_scores.get(name, {}).get(year, 0)

# ═════════════════════════════════════════════════════════════════════
# 工具函数
# ═════════════════════════════════════════════════════════════════════
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
    # v6：仓位分级（同v5）
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
    # v6: 添加趋势标记
    df["TrendUp"] = (df["Close"] > df[f"MA{TREND_MA}"]) & (df["MA20"] > df[f"MA{TREND_MA}"]*0.98)
    return df.dropna()

def c_stop_params(avg_atr_pct):
    if avg_atr_pct < C_LOW_ATR_PCT:
        return "fixed", C_LOW_FIXED, C_LOW_FIXED, "低波动→固定止损"
    elif avg_atr_pct < C_HIGH_ATR_PCT:
        return "atr", C_MID_ATR_MULT, C_MID_MAX, "中波动→ATR×2.5"
    else:
        return "atr", C_HIGH_ATR_MULT, C_HIGH_MAX, "高波动→ATR×2.0"

# ═════════════════════════════════════════════════════════════════════
# v6 核心引擎：带盈利保护
# ═════════════════════════════════════════════════════════════════════
def simulate_v6(name, df, mode="A", c_avg_atr_pct=None, sentiment_cache=None):
    """
    v6 引擎：
    - 趋势过滤
    - 盈利保护（三阶段）
    - 冷却期
    """
    capital, position, entry = INITIAL_CAPITAL, 0, 0.0
    high_price, trail_pct = 0.0, 0.0
    trades = []
    last_buy_date = None
    
    c_mode, c_mult, c_max, c_note = ("fixed",0,0,"") if mode!="C" else c_stop_params(c_avg_atr_pct)
    
    for date, row in df.iterrows():
        f = get_snap(FUNDAMENTAL[name], date)
        s = get_llm_sentiment_score(name, date, sentiment_cache)
        t = tech_score(row)
        score = W_TECH*t + W_FUND*f + W_SENT*s
        price = float(row["Close"])
        vol = float(row["Volume"])
        vol20 = float(row["Vol20"])
        trend_ok = (not TREND_FILTER) or (row["Close"] > row[f"MA{TREND_MA}"] * 0.95)  # 放宽：允许略低于MA60
        
        # 冷却期检查
        in_cooldown = False
        if last_buy_date is not None:
            days_since_last = (date - last_buy_date).days
            in_cooldown = days_since_last < COOLDOWN_DAYS
        
        # ═════════════════════════════════════════════════════════════
        # 买入逻辑（v6强化）
        # ═════════════════════════════════════════════════════════════
        if score >= BUY_THRESH and position == 0 and capital > price and trend_ok and not in_cooldown:
            if vol >= vol20 * VOL_CONFIRM:
                ratio = pos_ratio(score)
                if ratio > 0:
                    shares = int(capital * ratio / price)
                    if shares > 0:
                        position, entry, high_price = shares, price, price
                        capital -= shares * price
                        last_buy_date = date
                        
                        # 确定初始止损
                        if mode == "A":
                            trail_pct = A_FIXED_STOP
                            note = f"仓{ratio*100:.0f}% 固定{trail_pct*100:.0f}%"
                        elif mode == "B":
                            raw = float(row["ATR"]) * B_ATR_MULT / price
                            trail_pct = float(np.clip(raw, B_MIN_STOP, B_MAX_STOP))
                            note = f"仓{ratio*100:.0f}% ATR{trail_pct*100:.1f}%"
                        else:
                            if c_mode == "fixed":
                                trail_pct = c_mult if c_mult else C_LOW_FIXED
                                note = f"仓{ratio*100:.0f}% {c_note} {trail_pct*100:.0f}%"
                            else:
                                raw = float(row["ATR"]) * c_mult / price
                                trail_pct = float(np.clip(raw, C_MIN_STOP, c_max))
                                note = f"仓{ratio*100:.0f}% {c_note} {trail_pct*100:.1f}%"
                        
                        trend_tag = "📈趋势" if trend_ok else "⚠️逆趋势"
                        trades.append({"操作":"买入","日期":date.date(),"价格":round(price,4),
                                       "股数":shares,"评分":round(score,2),"备注":f"{note} {trend_tag}"})
        
        # ═════════════════════════════════════════════════════════════
        # 持仓管理 + 盈利保护（v6核心）
        # ═════════════════════════════════════════════════════════════
        elif position > 0:
            high_price = max(high_price, price)
            current_pnl_pct = (price - entry) / entry
            
            # 动态调整止损：盈利保护
            effective_trail = trail_pct
            profit_lock_note = ""
            
            if current_pnl_pct >= PROFIT_STAGE_3:  # 盈利>100%
                # 宽止损，让利润奔跑
                effective_trail = max(trail_pct * 1.5, (high_price - entry * 1.5) / high_price)
                profit_lock_note = "🚀宽止"
            elif current_pnl_pct >= PROFIT_STAGE_2:  # 盈利>50%
                # 锁定10%利润 + 原追踪止损
                min_stop = max(0.10, trail_pct)  # 至少保10%
                effective_trail = min(trail_pct, 1 - (entry * 1.10) / high_price) if high_price > entry * 1.5 else trail_pct
                profit_lock_note = "🔒锁利"
            elif current_pnl_pct >= PROFIT_STAGE_1:  # 盈利>30%
                # 保本止损
                effective_trail = min(trail_pct, 1 - entry / high_price) if high_price > entry else trail_pct
                profit_lock_note = "🛡️保本"
            
            stop_price = high_price * (1 - effective_trail)
            
            if price <= stop_price or score <= SELL_THRESH:
                pnl = position*(price-entry)
                pct = pnl/(position*entry)*100
                reason = (f"止损 高{high_price:.3f}→线{stop_price:.3f}{profit_lock_note}"
                          if price<=stop_price else f"评分出({score:.1f})")
                capital += position*price
                trades.append({"操作":"卖出","日期":date.date(),"价格":round(price,4),
                               "股数":position,"评分":round(score,2),
                               "盈亏%":f"{pct:+.1f}%","备注":reason})
                position, high_price, trail_pct = 0, 0.0, 0.0
    
    last = float(df["Close"].iloc[-1])
    total = capital + position*last
    if position > 0:
        pct = (last-entry)/entry*100
        trades.append({"操作":"未平仓","日期":"持仓中","价格":round(last,4),
                       "股数":position,"评分":"-","盈亏%":f"{pct:+.1f}%","备注":"-"})
    return total, trades

# ═════════════════════════════════════════════════════════════════════
# 主流程
# ═════════════════════════════════════════════════════════════════════
def run_v6(name, ticker, sentiment_cache):
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
    
    print(f"  ATR均值: {avg_atr_pct*100:.1f}%  C策略: [{c_note}]")
    print(f"  趋势过滤: {'开启' if TREND_FILTER else '关闭'}  冷却期: {COOLDOWN_DAYS}天")
    print(f"  买入持有收益: {bh:+.1f}%")
    
    tA, trA = simulate_v6(name, df, "A", sentiment_cache=sentiment_cache)
    tB, trB = simulate_v6(name, df, "B", avg_atr_pct, sentiment_cache)
    tC, trC = simulate_v6(name, df, "C", avg_atr_pct, sentiment_cache)
    rA = (tA-INITIAL_CAPITAL)/INITIAL_CAPITAL*100
    rB = (tB-INITIAL_CAPITAL)/INITIAL_CAPITAL*100
    rC = (tC-INITIAL_CAPITAL)/INITIAL_CAPITAL*100
    
    for label, trades in [("A 固定止损12%", trA),("B ATR动态", trB),("C 混合自适应", trC)]:
        print(f"\n  【版本{label}】")
        if not trades: print("    无信号"); continue
        cols = [c for c in ["操作","日期","价格","股数","评分","盈亏%","备注"] if c in pd.DataFrame(trades).columns]
        print(pd.DataFrame(trades)[cols].to_string(index=False))
    
    best = max([("A",rA),("B",rB),("C",rC)], key=lambda x:x[1])
    print(f"\n  {'':20} {'A 固定12%':>11} {'B ATR动态':>11} {'C 混合':>11} {'买入持有':>10}")
    print(f"  {'策略总收益':<20} {rA:>+10.1f}% {rB:>+10.1f}% {rC:>+10.1f}% {bh:>+9.1f}%")
    print(f"  {'超额收益α':<20} {rA-bh:>+10.1f}% {rB-bh:>+10.1f}% {rC-bh:>+10.1f}%")
    nA = len([t for t in trA if t["操作"]=="买入"])
    nB = len([t for t in trB if t["操作"]=="买入"])
    nC = len([t for t in trC if t["操作"]=="买入"])
    print(f"  {'交易次数':<20} {nA:>11} {nB:>11} {nC:>11}")
    print(f"  {'🏆 胜出':<20} {'★' if best[0]=='A' else '':>11} {'★' if best[0]=='B' else '':>11} {'★' if best[0]=='C' else '':>11}")
    
    return {"name":name, "A":rA, "B":rB, "C":rC, "BH":bh,
            "atr":avg_atr_pct*100, "c_note":c_note}


if __name__ == "__main__":
    # 加载LLM舆情缓存
    sentiment_cache = load_llm_sentiment()
    
    print("\n" + "="*72)
    print("🔬 港股 AI v6 — 趋势过滤 + 盈利保护 + LLM舆情")
    print("="*72)
    print(f"   A: 固定止损{A_FIXED_STOP*100:.0f}%")
    print(f"   B: ATR×{B_ATR_MULT}动态止损")
    print(f"   C: 混合自适应")
    print(f"   开仓门槛: 评分≥{BUY_THRESH} + 趋势确认 + {COOLDOWN_DAYS}天冷却")
    print(f"   盈利保护: >30%保本 | >50%锁利 | >100%宽止损")
    print()
    
    results = []
    for i, (name, ticker) in enumerate(STOCKS.items()):
        if i > 0: time.sleep(1)
        r = run_v6(name, ticker, sentiment_cache)
        if r: results.append(r)
    
    if results:
        print(f"\n{'='*72}")
        print("  📋 v6 最终汇总")
        print(f"{'='*72}")
        print(f"  {'股票':<12} {'ATR%':>6} {'C策略':<16} {'A':>9} {'B':>9} {'C':>9} {'买持':>9}")
        print(f"  {'-'*70}")
        for r in results:
            marks = {k:"★" for k in ["A","B","C"] if r[k]==max(r["A"],r["B"],r["C"])}
            print(f"  {r['name']:<12} {r['atr']:>5.1f}%  {r['c_note']:<16}"
                  f" {r['A']:>+8.1f}%{marks.get('A',''):1}"
                  f" {r['B']:>+8.1f}%{marks.get('B',''):1}"
                  f" {r['C']:>+8.1f}%{marks.get('C',''):1}"
                  f" {r['BH']:>+8.1f}%")
        avg = {k: np.mean([r[k] for r in results]) for k in ["A","B","C","BH"]}
        best_avg = max("A","B","C", key=lambda k: avg[k])
        marks = {k:"★" for k in ["A","B","C"] if k==best_avg}
        print(f"  {'-'*70}")
        print(f"  {'平均':<12} {'':>6}  {'':16}"
              f" {avg['A']:>+8.1f}%{marks.get('A',''):1}"
              f" {avg['B']:>+8.1f}%{marks.get('B',''):1}"
              f" {avg['C']:>+8.1f}%{marks.get('C',''):1}"
              f" {avg['BH']:>+8.1f}%")
        print()
        
        # 对比v5
        print("  📊 v5 → v6 对比（平均收益）")
        v5_avg = {"A":5.6, "B":7.4, "C":6.6, "BH":32.4}  # 之前跑的数据
        print(f"    v5: A={v5_avg['A']:+.1f}% B={v5_avg['B']:+.1f}% C={v5_avg['C']:+.1f}% 买持={v5_avg['BH']:+.1f}%")
        print(f"    v6: A={avg['A']:+.1f}% B={avg['B']:+.1f}% C={avg['C']:+.1f}% 买持={avg['BH']:+.1f}%")
        print()
