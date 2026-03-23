#!/usr/bin/env python3
"""
港股分析脚本 - 获取港股数据并进行技术面+基本面分析，给出操作建议。

用法:
    python3 analyze_stock.py <股票代码> [--period <周期>] [--output <输出文件>]

示例:
    python3 analyze_stock.py 0700.HK
    python3 analyze_stock.py 0700.HK --period 6mo --output report.json
    python3 analyze_stock.py 9988.HK --period 1y

股票代码格式: 数字.HK (如 0700.HK 腾讯控股, 9988.HK 阿里巴巴)
周期选项: 1mo, 3mo, 6mo, 1y, 2y, 5y (默认 6mo)
"""

import sys
import json
import argparse
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance 未安装。请运行: pip3 install yfinance", file=sys.stderr)
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    print("ERROR: numpy 未安装。请运行: pip3 install numpy", file=sys.stderr)
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas 未安装。请运行: pip3 install pandas", file=sys.stderr)
    sys.exit(1)


# ─────────────────────────────────────────────
#  缓存与重试机制（解决 Yahoo Finance 限频问题）
# ─────────────────────────────────────────────

CACHE_DIR = Path.home() / ".stock_buddy_cache"
CACHE_TTL_SECONDS = 600  # 缓存有效期 10 分钟（同一股票短时间内不重复请求）
MAX_RETRIES = 4          # 最大重试次数
RETRY_BASE_DELAY = 5     # 重试基础延迟（秒），指数退避: 5s, 10s, 20s, 40s


def _cache_key(code: str, period: str) -> str:
    """生成缓存文件名"""
    key = f"{code}_{period}"
    return hashlib.md5(key.encode()).hexdigest() + ".json"


def _read_cache(code: str, period: str) -> dict | None:
    """读取缓存，若未过期则返回缓存数据"""
    cache_file = CACHE_DIR / _cache_key(code, period)
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cached = json.load(f)
        cached_time = datetime.fromisoformat(cached.get("analysis_time", ""))
        if (datetime.now() - cached_time).total_seconds() < CACHE_TTL_SECONDS:
            cached["_from_cache"] = True
            return cached
    except (json.JSONDecodeError, ValueError, KeyError):
        pass
    return None


def _write_cache(code: str, period: str, data: dict):
    """写入缓存"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / _cache_key(code, period)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except OSError:
        pass  # 缓存写入失败不影响主流程


def _retry_request(func, *args, max_retries=MAX_RETRIES, **kwargs):
    """
    带指数退避的重试包装器。
    捕获 Yahoo Finance 限频错误并自动重试。
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()
            # 仅对限频/网络类错误重试
            is_rate_limit = any(kw in error_msg for kw in [
                "rate limit", "too many requests", "429", "throttl",
                "connection", "timeout", "timed out",
            ])
            if not is_rate_limit:
                raise  # 非限频错误直接抛出
            if attempt < max_retries - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)  # 3s, 6s, 12s
                print(f"⏳ 请求被限频，{delay}秒后第{attempt+2}次重试...", file=sys.stderr)
                time.sleep(delay)
    raise last_error


# ─────────────────────────────────────────────
#  技术指标计算
# ─────────────────────────────────────────────

def calc_ma(close: pd.Series, windows: list[int] = None) -> dict:
    """计算多周期移动平均线"""
    if windows is None:
        windows = [5, 10, 20, 60, 120, 250]
    result = {}
    for w in windows:
        if len(close) >= w:
            ma = close.rolling(window=w).mean()
            result[f"MA{w}"] = round(ma.iloc[-1], 3)
    return result


def calc_ema(close: pd.Series, span: int) -> pd.Series:
    """计算指数移动平均线"""
    return close.ewm(span=span, adjust=False).mean()


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """计算MACD指标"""
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = 2 * (dif - dea)

    return {
        "DIF": round(dif.iloc[-1], 4),
        "DEA": round(dea.iloc[-1], 4),
        "MACD": round(macd_hist.iloc[-1], 4),
        "signal": _macd_signal(dif, dea, macd_hist),
    }


def _macd_signal(dif: pd.Series, dea: pd.Series, macd_hist: pd.Series) -> str:
    """MACD信号判断"""
    if len(dif) < 3:
        return "中性"
    # 金叉：DIF上穿DEA
    if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
        return "金叉-买入信号"
    # 死叉：DIF下穿DEA
    if dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2]:
        return "死叉-卖出信号"
    # 零轴上方
    if dif.iloc[-1] > 0 and dea.iloc[-1] > 0:
        if macd_hist.iloc[-1] > macd_hist.iloc[-2]:
            return "多头增强"
        return "多头区域"
    # 零轴下方
    if dif.iloc[-1] < 0 and dea.iloc[-1] < 0:
        if macd_hist.iloc[-1] < macd_hist.iloc[-2]:
            return "空头增强"
        return "空头区域"
    return "中性"


def calc_rsi(close: pd.Series, periods: list[int] = None) -> dict:
    """计算RSI指标"""
    if periods is None:
        periods = [6, 12, 24]
    result = {}
    delta = close.diff()
    for p in periods:
        if len(close) < p + 1:
            continue
        gain = delta.clip(lower=0).rolling(window=p).mean()
        loss = (-delta.clip(upper=0)).rolling(window=p).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        val = round(rsi.iloc[-1], 2)
        result[f"RSI{p}"] = val
    # 综合信号
    rsi_main = result.get("RSI12", result.get("RSI6", 50))
    if rsi_main > 80:
        result["signal"] = "严重超买-卖出信号"
    elif rsi_main > 70:
        result["signal"] = "超买-注意风险"
    elif rsi_main < 20:
        result["signal"] = "严重超卖-买入信号"
    elif rsi_main < 30:
        result["signal"] = "超卖-关注买入"
    else:
        result["signal"] = "中性"
    return result


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9) -> dict:
    """计算KDJ指标"""
    if len(close) < n:
        return {"K": 50, "D": 50, "J": 50, "signal": "数据不足"}
    lowest_low = low.rolling(window=n).min()
    highest_high = high.rolling(window=n).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan) * 100

    k = pd.Series(index=close.index, dtype=float)
    d = pd.Series(index=close.index, dtype=float)
    k.iloc[n - 1] = 50
    d.iloc[n - 1] = 50
    for i in range(n, len(close)):
        k.iloc[i] = 2 / 3 * k.iloc[i - 1] + 1 / 3 * rsv.iloc[i]
        d.iloc[i] = 2 / 3 * d.iloc[i - 1] + 1 / 3 * k.iloc[i]
    j = 3 * k - 2 * d

    k_val = round(k.iloc[-1], 2)
    d_val = round(d.iloc[-1], 2)
    j_val = round(j.iloc[-1], 2)

    signal = "中性"
    if k_val > d_val and k.iloc[-2] <= d.iloc[-2]:
        signal = "金叉-买入信号"
    elif k_val < d_val and k.iloc[-2] >= d.iloc[-2]:
        signal = "死叉-卖出信号"
    elif j_val > 100:
        signal = "超买区域"
    elif j_val < 0:
        signal = "超卖区域"

    return {"K": k_val, "D": d_val, "J": j_val, "signal": signal}


def calc_bollinger(close: pd.Series, window: int = 20, num_std: float = 2) -> dict:
    """计算布林带"""
    if len(close) < window:
        return {"signal": "数据不足"}
    ma = close.rolling(window=window).mean()
    std = close.rolling(window=window).std()
    upper = ma + num_std * std
    lower = ma - num_std * std

    current = close.iloc[-1]
    upper_val = round(upper.iloc[-1], 3)
    lower_val = round(lower.iloc[-1], 3)
    mid_val = round(ma.iloc[-1], 3)
    bandwidth = round((upper_val - lower_val) / mid_val * 100, 2)

    signal = "中性"
    if current > upper_val:
        signal = "突破上轨-超买"
    elif current < lower_val:
        signal = "突破下轨-超卖"
    elif current > mid_val:
        signal = "中轨上方-偏强"
    else:
        signal = "中轨下方-偏弱"

    return {
        "upper": upper_val,
        "middle": mid_val,
        "lower": lower_val,
        "bandwidth_pct": bandwidth,
        "signal": signal,
    }


def calc_volume_analysis(volume: pd.Series, close: pd.Series) -> dict:
    """成交量分析"""
    if len(volume) < 20:
        return {"signal": "数据不足"}
    avg_5 = volume.rolling(5).mean().iloc[-1]
    avg_20 = volume.rolling(20).mean().iloc[-1]
    current = volume.iloc[-1]
    vol_ratio = round(current / avg_5, 2) if avg_5 > 0 else 0
    price_change = close.iloc[-1] - close.iloc[-2]

    signal = "中性"
    if vol_ratio > 2 and price_change > 0:
        signal = "放量上涨-强势"
    elif vol_ratio > 2 and price_change < 0:
        signal = "放量下跌-弱势"
    elif vol_ratio < 0.5 and price_change > 0:
        signal = "缩量上涨-动力不足"
    elif vol_ratio < 0.5 and price_change < 0:
        signal = "缩量下跌-抛压减轻"

    return {
        "current_volume": int(current),
        "avg_5d_volume": int(avg_5),
        "avg_20d_volume": int(avg_20),
        "volume_ratio": vol_ratio,
        "signal": signal,
    }


def calc_ma_trend(close: pd.Series) -> dict:
    """均线趋势分析"""
    mas = calc_ma(close, [5, 10, 20, 60])
    current = close.iloc[-1]

    above_count = sum(1 for v in mas.values() if current > v)
    total = len(mas)

    if above_count == total and total > 0:
        signal = "多头排列-强势"
    elif above_count == 0:
        signal = "空头排列-弱势"
    elif above_count >= total * 0.7:
        signal = "偏多"
    elif above_count <= total * 0.3:
        signal = "偏空"
    else:
        signal = "震荡"

    return {**mas, "trend_signal": signal, "price_above_ma_count": f"{above_count}/{total}"}


# ─────────────────────────────────────────────
#  基本面分析
# ─────────────────────────────────────────────

def get_fundamentals(ticker: yf.Ticker) -> dict:
    """获取基本面数据"""
    info = ticker.info
    result = {}

    # 估值指标
    pe = info.get("trailingPE") or info.get("forwardPE")
    pb = info.get("priceToBook")
    ps = info.get("priceToSalesTrailing12Months")
    result["PE"] = round(pe, 2) if pe else None
    result["PB"] = round(pb, 2) if pb else None
    result["PS"] = round(ps, 2) if ps else None

    # 股息 (yfinance 有时返回异常值，限制在合理范围)
    div_yield = info.get("dividendYield")
    if div_yield is not None and 0 < div_yield < 1:
        result["dividend_yield_pct"] = round(div_yield * 100, 2)
    elif div_yield is not None and div_yield >= 1:
        # 可能已经是百分比形式
        result["dividend_yield_pct"] = round(div_yield, 2) if div_yield < 30 else None
    else:
        result["dividend_yield_pct"] = None

    # 市值
    market_cap = info.get("marketCap")
    if market_cap:
        if market_cap >= 1e12:
            result["market_cap"] = f"{market_cap/1e12:.2f} 万亿"
        elif market_cap >= 1e8:
            result["market_cap"] = f"{market_cap/1e8:.2f} 亿"
        else:
            result["market_cap"] = f"{market_cap:,.0f}"
    else:
        result["market_cap"] = None

    # 盈利能力
    result["profit_margin_pct"] = round(info.get("profitMargins", 0) * 100, 2) if info.get("profitMargins") else None
    result["roe_pct"] = round(info.get("returnOnEquity", 0) * 100, 2) if info.get("returnOnEquity") else None
    result["roa_pct"] = round(info.get("returnOnAssets", 0) * 100, 2) if info.get("returnOnAssets") else None

    # 增长指标
    result["revenue_growth_pct"] = round(info.get("revenueGrowth", 0) * 100, 2) if info.get("revenueGrowth") else None
    result["earnings_growth_pct"] = round(info.get("earningsGrowth", 0) * 100, 2) if info.get("earningsGrowth") else None

    # 负债
    result["debt_to_equity"] = round(info.get("debtToEquity", 0), 2) if info.get("debtToEquity") else None

    # 52周价格区间
    result["52w_high"] = info.get("fiftyTwoWeekHigh")
    result["52w_low"] = info.get("fiftyTwoWeekLow")
    result["50d_avg"] = info.get("fiftyDayAverage")
    result["200d_avg"] = info.get("twoHundredDayAverage")

    # 公司信息
    result["company_name"] = info.get("longName") or info.get("shortName", "未知")
    result["sector"] = info.get("sector", "未知")
    result["industry"] = info.get("industry", "未知")
    result["currency"] = info.get("currency", "HKD")

    # 基本面评分
    result["fundamental_signal"] = _fundamental_signal(result)

    return result


def _fundamental_signal(data: dict) -> str:
    """基本面信号判断"""
    score = 0
    reasons = []

    # PE 评估
    pe = data.get("PE")
    if pe is not None:
        if pe < 0:
            score -= 1
            reasons.append("PE为负(亏损)")
        elif pe < 15:
            score += 2
            reasons.append("PE低估值")
        elif pe < 25:
            score += 1
            reasons.append("PE合理")
        elif pe > 40:
            score -= 1
            reasons.append("PE高估")

    # PB 评估
    pb = data.get("PB")
    if pb is not None:
        if pb < 1:
            score += 1
            reasons.append("PB破净")
        elif pb > 5:
            score -= 1

    # 股息率
    div = data.get("dividend_yield_pct")
    if div is not None and div > 3:
        score += 1
        reasons.append(f"高股息{div}%")

    # ROE
    roe = data.get("roe_pct")
    if roe is not None:
        if roe > 15:
            score += 1
            reasons.append("ROE优秀")
        elif roe < 5:
            score -= 1

    # 增长
    rev_growth = data.get("revenue_growth_pct")
    if rev_growth is not None and rev_growth > 10:
        score += 1
        reasons.append("收入增长良好")

    earnings_growth = data.get("earnings_growth_pct")
    if earnings_growth is not None and earnings_growth > 15:
        score += 1
        reasons.append("利润增长强劲")

    # 负债
    de = data.get("debt_to_equity")
    if de is not None and de > 200:
        score -= 1
        reasons.append("负债率偏高")

    if score >= 3:
        signal = "基本面优秀"
    elif score >= 1:
        signal = "基本面良好"
    elif score >= 0:
        signal = "基本面一般"
    else:
        signal = "基本面较差"

    return f"{signal} ({'; '.join(reasons[:4])})" if reasons else signal


# ─────────────────────────────────────────────
#  综合评分与建议
# ─────────────────────────────────────────────

def generate_recommendation(technical: dict, fundamental: dict, current_price: float) -> dict:
    """综合技术面和基本面给出操作建议"""
    score = 0  # 范围大约 -10 到 +10
    signals = []

    # ── 技术面评分 ──
    macd_sig = technical.get("macd", {}).get("signal", "")
    if "买入" in macd_sig or "金叉" in macd_sig:
        score += 2
        signals.append(f"MACD: {macd_sig}")
    elif "卖出" in macd_sig or "死叉" in macd_sig:
        score -= 2
        signals.append(f"MACD: {macd_sig}")
    elif "多头" in macd_sig:
        score += 1
        signals.append(f"MACD: {macd_sig}")
    elif "空头" in macd_sig:
        score -= 1
        signals.append(f"MACD: {macd_sig}")

    rsi_sig = technical.get("rsi", {}).get("signal", "")
    if "超卖" in rsi_sig:
        score += 2
        signals.append(f"RSI: {rsi_sig}")
    elif "超买" in rsi_sig:
        score -= 2
        signals.append(f"RSI: {rsi_sig}")

    kdj_sig = technical.get("kdj", {}).get("signal", "")
    if "买入" in kdj_sig or "金叉" in kdj_sig:
        score += 1
        signals.append(f"KDJ: {kdj_sig}")
    elif "卖出" in kdj_sig or "死叉" in kdj_sig:
        score -= 1
        signals.append(f"KDJ: {kdj_sig}")

    boll_sig = technical.get("bollinger", {}).get("signal", "")
    if "超卖" in boll_sig or "下轨" in boll_sig:
        score += 1
        signals.append(f"布林带: {boll_sig}")
    elif "超买" in boll_sig or "上轨" in boll_sig:
        score -= 1
        signals.append(f"布林带: {boll_sig}")

    ma_sig = technical.get("ma_trend", {}).get("trend_signal", "")
    if "多头" in ma_sig or "强势" in ma_sig:
        score += 2
        signals.append(f"均线: {ma_sig}")
    elif "空头" in ma_sig or "弱势" in ma_sig:
        score -= 2
        signals.append(f"均线: {ma_sig}")
    elif "偏多" in ma_sig:
        score += 1
    elif "偏空" in ma_sig:
        score -= 1

    vol_sig = technical.get("volume", {}).get("signal", "")
    if "放量上涨" in vol_sig:
        score += 1
        signals.append(f"成交量: {vol_sig}")
    elif "放量下跌" in vol_sig:
        score -= 1
        signals.append(f"成交量: {vol_sig}")

    # ── 基本面评分 ──
    fund_sig = fundamental.get("fundamental_signal", "")
    if "优秀" in fund_sig:
        score += 2
        signals.append(f"基本面: {fund_sig}")
    elif "良好" in fund_sig:
        score += 1
        signals.append(f"基本面: {fund_sig}")
    elif "较差" in fund_sig:
        score -= 2
        signals.append(f"基本面: {fund_sig}")

    # 52周位置
    high_52w = fundamental.get("52w_high")
    low_52w = fundamental.get("52w_low")
    if high_52w and low_52w and high_52w != low_52w:
        position = (current_price - low_52w) / (high_52w - low_52w)
        if position < 0.2:
            score += 1
            signals.append(f"52周位置: {position:.0%} (接近低点)")
        elif position > 0.9:
            score -= 1
            signals.append(f"52周位置: {position:.0%} (接近高点)")
        else:
            signals.append(f"52周位置: {position:.0%}")

    # ── 映射到操作建议 ──
    if score >= 5:
        action = "强烈买入"
        action_en = "STRONG_BUY"
        color = "🟢🟢"
    elif score >= 2:
        action = "买入"
        action_en = "BUY"
        color = "🟢"
    elif score >= -1:
        action = "持有/观望"
        action_en = "HOLD"
        color = "🟡"
    elif score >= -4:
        action = "卖出"
        action_en = "SELL"
        color = "🔴"
    else:
        action = "强烈卖出"
        action_en = "STRONG_SELL"
        color = "🔴🔴"

    return {
        "action": action,
        "action_en": action_en,
        "score": score,
        "icon": color,
        "key_signals": signals,
        "summary": f"{color} {action} (综合评分: {score})",
    }


# ─────────────────────────────────────────────
#  主流程
# ─────────────────────────────────────────────

def normalize_hk_code(code: str) -> str:
    """标准化港股代码"""
    code = code.strip().upper()
    if not code.endswith(".HK"):
        # 尝试补全
        digits = code.lstrip("0")
        if digits.isdigit():
            code = code.zfill(4) + ".HK"
    return code


def analyze_stock(code: str, period: str = "6mo", use_cache: bool = True) -> dict:
    """对单只港股进行完整分析（内置缓存 + 自动重试）"""
    code = normalize_hk_code(code)

    # 1. 尝试读取缓存
    if use_cache:
        cached = _read_cache(code, period)
        if cached:
            print(f"📦 使用缓存数据 ({code})，缓存有效期 {CACHE_TTL_SECONDS}s", file=sys.stderr)
            return cached

    result = {"code": code, "analysis_time": datetime.now().isoformat(), "error": None}

    try:
        ticker = yf.Ticker(code)

        # 2. 带重试的数据获取（限频时可能返回空数据或抛异常）
        hist = None
        for attempt in range(MAX_RETRIES):
            try:
                hist = ticker.history(period=period)
                if hist is not None and not hist.empty:
                    break  # 成功获取数据
                # 空数据可能是限频导致，重试
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    print(f"⏳ 数据为空（可能限频），{delay}秒后第{attempt+2}次重试...", file=sys.stderr)
                    time.sleep(delay)
                    ticker = yf.Ticker(code)  # 重新创建 ticker 对象
            except Exception as e:
                error_msg = str(e).lower()
                is_retriable = any(kw in error_msg for kw in [
                    "rate limit", "too many requests", "429", "throttl",
                    "connection", "timeout", "timed out",
                ])
                if not is_retriable or attempt >= MAX_RETRIES - 1:
                    raise
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"⏳ 请求被限频，{delay}秒后第{attempt+2}次重试...", file=sys.stderr)
                time.sleep(delay)
                ticker = yf.Ticker(code)

        if hist is None or hist.empty:
            result["error"] = f"无法获取 {code} 的历史数据，请检查股票代码是否正确"
            return result

        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        volume = hist["Volume"]
        current_price = round(close.iloc[-1], 3)

        result["current_price"] = current_price
        result["price_date"] = str(hist.index[-1].date())
        result["data_points"] = len(hist)

        # 价格变动
        if len(close) > 1:
            prev_close = close.iloc[-2]
            change = current_price - prev_close
            change_pct = change / prev_close * 100
            result["price_change"] = round(change, 3)
            result["price_change_pct"] = round(change_pct, 2)

        # 技术分析
        technical = {}
        technical["ma_trend"] = calc_ma_trend(close)
        technical["macd"] = calc_macd(close)
        technical["rsi"] = calc_rsi(close)
        technical["kdj"] = calc_kdj(high, low, close)
        technical["bollinger"] = calc_bollinger(close)
        technical["volume"] = calc_volume_analysis(volume, close)
        result["technical"] = technical

        # 3. 带重试的基本面数据获取
        try:
            fundamental = _retry_request(get_fundamentals, ticker)
            result["fundamental"] = fundamental
        except Exception as e:
            result["fundamental"] = {"error": str(e), "fundamental_signal": "数据获取失败"}
            fundamental = result["fundamental"]

        # 综合建议
        result["recommendation"] = generate_recommendation(technical, fundamental, current_price)

        # 4. 写入缓存（仅成功分析时）
        if result.get("error") is None:
            _write_cache(code, period, result)

    except Exception as e:
        result["error"] = f"分析过程出错: {str(e)}"

    return result


def main():
    parser = argparse.ArgumentParser(description="港股分析工具")
    parser.add_argument("code", help="港股代码 (如 0700.HK)")
    parser.add_argument("--period", default="6mo", help="数据周期 (1mo/3mo/6mo/1y/2y/5y)")
    parser.add_argument("--output", help="输出JSON文件路径")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存，强制重新请求数据")
    parser.add_argument("--clear-cache", action="store_true", help="清除所有缓存后退出")
    args = parser.parse_args()

    # 清除缓存
    if args.clear_cache:
        import shutil
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
            print("✅ 缓存已清除")
        else:
            print("ℹ️ 无缓存可清除")
        return

    result = analyze_stock(args.code, args.period, use_cache=not args.no_cache)

    output = json.dumps(result, ensure_ascii=False, indent=2, default=str)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"分析结果已保存至 {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
