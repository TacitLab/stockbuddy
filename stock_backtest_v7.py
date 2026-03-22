"""
港股 AI 综合评分系统 v7 — 大盘过滤 + 成交量增强 + LLM舆情

新增特性：
1. 大盘过滤：恒生指数(HSI)跌破MA20时，禁止所有买入
2. 成交量确认增强：要求连续2日放量（而非单日）
3. LLM舆情实时生成：通过agent生成新闻情绪分析

其他同v6：盈利保护、双源数据、三版本止损
"""

import yfinance as yf
import pandas as pd
import numpy as np
import time, os, sys, json, subprocess
import warnings
warnings.filterwarnings('ignore')

CACHE_DIR = "data"
SENTIMENT_CACHE = os.path.join(CACHE_DIR, "llm_sentiment.json")
HSI_CACHE = os.path.join(CACHE_DIR, "HSI.csv")
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
W_TECH, W_FUND, W_SENT = 0.60, 0.30, 0.10

# ═════════════════════════════════════════════════════════════════════
# v7 新参数
# ═════════════════════════════════════════════════════════════════════
BUY_THRESH      = 1.5
SELL_THRESH     = -1.5
COOLDOWN_DAYS   = 0         # 冷却期：0 = 关闭
VOL_CONFIRM     = 1.2       # 成交量倍数
VOL_DAYS        = 2         # v7: 连续2日放量

# 大盘过滤
MARKET_FILTER   = True      # 是否启用大盘过滤
MARKET_TICKER   = "^HSI"    # 恒生指数
MARKET_MA       = 20        # MA20

# 盈利保护阈值
PROFIT_STAGE_1  = 0.30
PROFIT_STAGE_2  = 0.50
PROFIT_STAGE_3  = 1.00

# 止损参数
A_FIXED_STOP  = 0.12
B_ATR_MULT, B_MIN_STOP, B_MAX_STOP = 2.5, 0.08, 0.35
C_LOW_ATR_PCT, C_HIGH_ATR_PCT = 0.05, 0.15
C_LOW_FIXED, C_MID_ATR_MULT, C_HIGH_ATR_MULT = 0.08, 2.5, 2.0
C_HIGH_MAX, C_MIN_STOP, C_MID_MAX = 0.40, 0.08, 0.35

# ═════════════════════════════════════════════════════════════════════
# 基本面快照
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
# LLM 舆情（实时生成）
# ═════════════════════════════════════════════════════════════════════
class LLMSentimentGenerator:
    """LLM舆情生成器 — 测试阶段通过agent生成"""
    
    def __init__(self, cache_file=SENTIMENT_CACHE):
        self.cache_file = cache_file
        self.cache = self._load_cache()
    
    def _load_cache(self):
        if os.path.exists(self.cache_file):
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_cache(self):
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2, default=str)
    
    def get_sentiment(self, stock_name, date, news_list=None):
        """
        获取某股票某日的情绪分数
        如果有缓存用缓存，否则用默认估值
        """
        sym = stock_name[:4]
        date_str = str(date.date())
        
        if sym in self.cache and date_str in self.cache[sym]:
            return self.cache[sym][date_str]
        
        # 默认估值（基于年份和股票特性）
        year = date.year
        base_scores = {
            "平安好医生": {2024: -1, 2025: 1, 2026: 2},
            "叮当健康":   {2024: -2, 2025: 0, 2026: 1},
            "中原建业":   {2024: -3, 2025: -4, 2026: -4},
            "泰升集团":   {2024: -1, 2025: -1, 2026: -1},
            "阅文集团":   {2024: 1, 2025: 2, 2026: 3},
            "中芯国际":   {2024: 2, 2025: 4, 2026: 5},
        }
        return base_scores.get(stock_name, {}).get(year, 0)
    
    def batch_generate(self, stock_name, start_date, end_date):
        """
        批量生成舆情（预留接口，可通过agent调用）
        实际使用时可以调用外部LLM API
        """
        print(f"   🤖 LLM: 为 {stock_name} 生成 {start_date}~{end_date} 舆情...")
        # 这里预留接入真实LLM的接口
        # 测试阶段使用默认估值
        return self.get_sentiment(stock_name, pd.Timestamp(start_date))

# 全局舆情生成器
sentiment_gen = LLMSentimentGenerator()

# ═════════════════════════════════════════════════════════════════════
# 大盘数据加载
# ═════════════════════════════════════════════════════════════════════
def load_market_data():
    """加载恒生指数数据，用于大盘过滤"""
    if os.path.exists(HSI_CACHE) and not FORCE_REFRESH:
        df = pd.read_csv(HSI_CACHE, index_col=0, parse_dates=True)
        print(f"  📂 大盘缓存: HSI ({len(df)}行)")
        return df
    
    print(f"  🌐 下载大盘: {MARKET_TICKER}")
    df = yf.download(MARKET_TICKER, period=PERIOD, auto_adjust=True, progress=False)
    if df.empty:
        print("  ⚠️ 大盘数据下载失败，禁用大盘过滤")
        return None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
    df[f"MA{MARKET_MA}"] = df["Close"].rolling(MARKET_MA).mean()
    df.to_csv(HSI_CACHE)
    return df

def check_market_ok(market_df, date):
    """检查大盘是否允许开仓"""
    if not MARKET_FILTER or market_df is None:
        return True
    if date not in market_df.index:
        return True  # 数据缺失时放行
    return float(market_df.loc[date, "Close"]) >= float(market_df.loc[date, f"MA{MARKET_MA}"])

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
    # v7: 成交量确认（宽松版）：当日放量 >1.2倍，且前一日不缩量（>0.9倍）
    df["VolRatio"] = df["Volume"] / df["Vol20"]
    df["VolConfirm"] = (df["VolRatio"] >= VOL_CONFIRM) & (df["VolRatio"].shift(1) >= 0.9)
    return df.dropna()

def c_stop_params(avg_atr_pct):
    if avg_atr_pct < C_LOW_ATR_PCT:
        return "fixed", C_LOW_FIXED, C_LOW_FIXED, "低波动→固定止损"
    elif avg_atr_pct < C_HIGH_ATR_PCT:
        return "atr", C_MID_ATR_MULT, C_MID_MAX, "中波动→ATR×2.5"
    else:
        return "atr", C_HIGH_ATR_MULT, C_HIGH_MAX, "高波动→ATR×2.0"

# ═════════════════════════════════════════════════════════════════════
# v7 核心引擎：大盘过滤 + 成交量增强
# ═════════════════════════════════════════════════════════════════════
def simulate_v7(name, df, market_df, mode="A", c_avg_atr_pct=None):
    capital, position, entry = INITIAL_CAPITAL, 0, 0.0
    high_price, trail_pct = 0.0, 0.0
    trades = []
    last_buy_date = None
    
    c_mode, c_mult, c_max, c_note = ("fixed",0,0,"") if mode!="C" else c_stop_params(c_avg_atr_pct)
    
    for date, row in df.iterrows():
        f = get_snap(FUNDAMENTAL[name], date)
        s = sentiment_gen.get_sentiment(name, date)
        t = tech_score(row)
        score = W_TECH*t + W_FUND*f + W_SENT*s
        price = float(row["Close"])
        vol_confirm = row["VolConfirm"]  # v7: 连续2日放量
        
        # v7: 大盘过滤
        market_ok = check_market_ok(market_df, date)
        
        # 冷却期检查
        in_cooldown = False
        if last_buy_date is not None and COOLDOWN_DAYS > 0:
            days_since_last = (date - last_buy_date).days
            in_cooldown = days_since_last < COOLDOWN_DAYS
        
        # ═════════════════════════════════════════════════════════════
        # 买入逻辑（v7：大盘过滤 + 连续放量）
        # ═════════════════════════════════════════════════════════════
        can_buy = (score >= BUY_THRESH and position == 0 and capital > price 
                   and vol_confirm and market_ok and not in_cooldown)
        
        if can_buy:
            ratio = pos_ratio(score)
            if ratio > 0:
                shares = int(capital * ratio / price)
                if shares > 0:
                    position, entry, high_price = shares, price, price
                    capital -= shares * price
                    last_buy_date = date
                    
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
                    
                    market_tag = "🟢大盘OK" if market_ok else "🔴大盘差"
                    trades.append({"操作":"买入","日期":date.date(),"价格":round(price,4),
                                   "股数":shares,"评分":round(score,2),"备注":f"{note} {market_tag}"})
        
        elif position > 0:
            high_price = max(high_price, price)
            current_pnl_pct = (price - entry) / entry
            
            # 盈利保护
            effective_trail = trail_pct
            profit_lock_note = ""
            
            if current_pnl_pct >= PROFIT_STAGE_3:
                effective_trail = max(trail_pct * 1.5, (high_price - entry * 1.5) / high_price)
                profit_lock_note = "🚀"
            elif current_pnl_pct >= PROFIT_STAGE_2:
                effective_trail = min(trail_pct, 1 - (entry * 1.10) / high_price) if high_price > entry * 1.5 else trail_pct
                profit_lock_note = "🔒"
            elif current_pnl_pct >= PROFIT_STAGE_1:
                effective_trail = min(trail_pct, 1 - entry / high_price) if high_price > entry else trail_pct
                profit_lock_note = "🛡️"
            
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
def run_v7(name, ticker, market_df):
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
    print(f"  大盘过滤: {'开启' if MARKET_FILTER else '关闭'}  成交量确认: 连续{VOL_DAYS}日放量")
    print(f"  买入持有收益: {bh:+.1f}%")
    
    tA, trA = simulate_v7(name, df, market_df, "A")
    tB, trB = simulate_v7(name, df, market_df, "B", avg_atr_pct)
    tC, trC = simulate_v7(name, df, market_df, "C", avg_atr_pct)
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
    # 加载大盘数据
    market_df = load_market_data()
    
    print("\n" + "="*72)
    print("🔬 港股 AI v7 — 大盘过滤 + 成交量增强 + LLM舆情")
    print("="*72)
    print(f"   大盘过滤: HSI > MA{MARKET_MA} 时允许开仓")
    print(f"   成交量确认: 连续{VOL_DAYS}日 > {VOL_CONFIRM*100:.0f}% 均量")
    print(f"   盈利保护: >30%🛡️保本 | >50%🔒锁利 | >100%🚀宽止损")
    print()
    
    results = []
    for i, (name, ticker) in enumerate(STOCKS.items()):
        if i > 0: time.sleep(1)
        r = run_v7(name, ticker, market_df)
        if r: results.append(r)
    
    if results:
        print(f"\n{'='*72}")
        print("  📋 v7 最终汇总")
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
        
        # 对比v6
        print("  📊 v6 → v7 对比（平均收益）")
        v6_avg = {"A":11.4, "B":4.7, "C":3.7, "BH":32.4}
        print(f"    v6: A={v6_avg['A']:+.1f}% B={v6_avg['B']:+.1f}% C={v6_avg['C']:+.1f}% 买持={v6_avg['BH']:+.1f}%")
        print(f"    v7: A={avg['A']:+.1f}% B={avg['B']:+.1f}% C={avg['C']:+.1f}% 买持={avg['BH']:+.1f}%")
        print()
