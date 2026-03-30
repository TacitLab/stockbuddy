#!/usr/bin/env python3
"""
港股分析脚本 - 使用腾讯财经数据源进行技术面+基本面分析

用法:
    python3 analyze_stock.py <股票代码> [--period <周期>] [--output <输出文件>]

示例:
    python3 analyze_stock.py 0700.HK
    python3 analyze_stock.py 0700.HK --period 6mo --output report.json
    python3 analyze_stock.py 9988.HK --period 1y
"""

import sys
import json
import argparse
import time
import hashlib
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

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
#  缓存与重试机制
# ─────────────────────────────────────────────

DATA_DIR = Path.home() / ".stockbuddy"
CACHE_DIR = DATA_DIR / "cache"
CACHE_TTL_SECONDS = 600  # 缓存有效期 10 分钟
LEGACY_CACHE_DIR = Path.home() / ".stock_buddy_cache"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2


def _cache_key(code: str, period: str) -> str:
    """生成缓存文件名"""
    key = f"{code}_{period}"
    return hashlib.md5(key.encode()).hexdigest() + ".json"


def _read_cache(code: str, period: str) -> dict | None:
    """读取缓存"""
    cache_file = CACHE_DIR / _cache_key(code, period)
    if not cache_file.exists():
        legacy_cache_file = LEGACY_CACHE_DIR / _cache_key(code, period)
        if legacy_cache_file.exists():
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(
                    legacy_cache_file.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            except OSError:
                cache_file = legacy_cache_file

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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / _cache_key(code, period)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except OSError:
        pass


# ─────────────────────────────────────────────
#  腾讯财经数据获取
# ─────────────────────────────────────────────

def normalize_hk_code(code: str) -> tuple[str, str]:
    """标准化港股代码，返回 (原始数字代码, 带.HK后缀代码)"""
    code = code.strip().upper().replace(".HK", "")
    digits = code.lstrip("0")
    if digits.isdigit():
        numeric_code = code.zfill(4)
        return numeric_code, numeric_code + ".HK"
    return code, code + ".HK"


def fetch_tencent_quote(code: str) -> dict:
    """获取腾讯财经实时行情"""
    numeric_code, full_code = normalize_hk_code(code)
    url = f"http://qt.gtimg.cn/q=hk{numeric_code}"
    
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=10) as response:
                data = response.read().decode("gb2312", errors="ignore")
                return _parse_tencent_quote(data, numeric_code)
        except urllib.error.URLError as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BASE_DELAY * (attempt + 1))
            else:
                raise Exception(f"获取实时行情失败: {e}")
    return {}


def _parse_tencent_quote(data: str, code: str) -> dict:
    """解析腾讯财经实时行情响应"""
    var_name = f"v_hk{code}"
    for line in data.strip().split(";"):
        line = line.strip()
        if not line or var_name not in line:
            continue
        # 提取引号内的内容
        parts = line.split('"')
        if len(parts) < 2:
            continue
        values = parts[1].split("~")
        if len(values) < 35:  # 至少需要35个字段
            continue
        
        def safe_float(idx: int, default: float = 0.0) -> float:
            try:
                return float(values[idx]) if values[idx] else default
            except (ValueError, IndexError):
                return default
        
        def safe_str(idx: int, default: str = "") -> str:
            return values[idx] if idx < len(values) else default
        
        # 字段映射 (根据腾讯财经API实际数据)
        # 0:市场 1:名称 2:代码 3:现价 4:昨收 5:今开 6:成交量
        # 30:时间戳 31:涨跌额 32:涨跌幅 33:最高 34:最低
        # 39:市盈率 47:市净率 37:总市值 48:52周高 49:52周低
        return {
            "name": values[1],
            "code": values[2],
            "price": safe_float(3),
            "prev_close": safe_float(4),
            "open": safe_float(5),
            "volume": safe_float(6),
            "high": safe_float(33),
            "low": safe_float(34),
            "change_amount": safe_float(31),
            "change_pct": safe_float(32),
            "timestamp": safe_str(30),
            "pe": safe_float(39) if len(values) > 39 else None,
            "pb": safe_float(47) if len(values) > 47 else None,
            "market_cap": safe_str(37),
            "52w_high": safe_float(48) if len(values) > 48 else None,
            "52w_low": safe_float(49) if len(values) > 49 else None,
        }
    return {}


def fetch_tencent_kline(code: str, days: int = 120) -> pd.DataFrame:
    """获取腾讯财经K线数据"""
    numeric_code, full_code = normalize_hk_code(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk{numeric_code},day,,,{days},qfq"
    
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                return _parse_tencent_kline(data, numeric_code)
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BASE_DELAY * (attempt + 1))
            else:
                raise Exception(f"获取K线数据失败: {e}")
    return pd.DataFrame()


def _parse_tencent_kline(data: dict, code: str) -> pd.DataFrame:
    """解析腾讯财经K线数据"""
    key = f"hk{code}"
    if data.get("code") != 0 or not data.get("data") or key not in data["data"]:
        return pd.DataFrame()
    
    day_data = data["data"][key].get("day", [])
    if not day_data:
        return pd.DataFrame()
    
    # 格式: [日期, 开盘价, 收盘价, 最低价, 最高价, 成交量]
    records = []
    for item in day_data:
        if len(item) >= 6:
            records.append({
                "Date": item[0],
                "Open": float(item[1]),
                "Close": float(item[2]),
                "Low": float(item[3]),
                "High": float(item[4]),
                "Volume": float(item[5]),
            })
    
    df = pd.DataFrame(records)
    if not df.empty:
        df["Date"] = pd.to_datetime(df["Date"])
        df.set_index("Date", inplace=True)
    return df


def period_to_days(period: str) -> int:
    """将周期字符串转换为天数"""
    mapping = {
        "1mo": 30,
        "3mo": 90,
        "6mo": 180,
        "1y": 250,
        "2y": 500,
        "5y": 1250,
    }
    return mapping.get(period, 180)


# ─────────────────────────────────────────────
#  技术指标计算 (保持不变)
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
    if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
        return "金叉-买入信号"
    if dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2]:
        return "死叉-卖出信号"
    if dif.iloc[-1] > 0 and dea.iloc[-1] > 0:
        if macd_hist.iloc[-1] > macd_hist.iloc[-2]:
            return "多头增强"
        return "多头区域"
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
#  基本面分析 (基于腾讯数据)
# ─────────────────────────────────────────────

def get_fundamentals(quote: dict) -> dict:
    """基于实时行情数据的基本面分析"""
    result = {}
    
    # 估值指标 (腾讯提供的)
    pe = quote.get("pe")
    pb = quote.get("pb")
    result["PE"] = round(pe, 2) if pe else None
    result["PB"] = round(pb, 2) if pb else None
    result["PS"] = None  # 腾讯不提供
    
    # 市值
    result["market_cap"] = quote.get("market_cap", "")
    
    # 52周价格区间
    result["52w_high"] = quote.get("52w_high")
    result["52w_low"] = quote.get("52w_low")
    
    # 公司信息
    result["company_name"] = quote.get("name", "未知")
    result["sector"] = "港股"
    result["industry"] = "港股"
    result["currency"] = "HKD"
    
    # 基本面信号
    result["fundamental_signal"] = _fundamental_signal(result)
    
    return result


def _fundamental_signal(data: dict) -> str:
    """基本面信号判断 (简化版)"""
    score = 0
    reasons = []

    pe = data.get("PE")
    if pe is not None and pe > 0:
        if pe < 15:
            score += 2
            reasons.append(f"PE低估值({pe})")
        elif pe < 25:
            score += 1
            reasons.append(f"PE合理({pe})")
        elif pe > 40:
            score -= 1
            reasons.append(f"PE偏高({pe})")

    pb = data.get("PB")
    if pb is not None:
        if pb < 1:
            score += 1
            reasons.append(f"PB破净({pb})")
        elif pb > 5:
            score -= 1
            reasons.append(f"PB偏高({pb})")

    if score >= 3:
        signal = "基本面优秀"
    elif score >= 1:
        signal = "基本面良好"
    elif score >= 0:
        signal = "基本面一般"
    else:
        signal = "基本面较差"

    return f"{signal} ({'; '.join(reasons[:3])})" if reasons else signal


# ─────────────────────────────────────────────
#  综合评分与建议
# ─────────────────────────────────────────────

def generate_recommendation(technical: dict, fundamental: dict, current_price: float) -> dict:
    """综合技术面和基本面给出操作建议"""
    score = 0
    signals = []

    # 技术面评分
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

    # 基本面评分
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

    # 映射到操作建议
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

def analyze_stock(code: str, period: str = "6mo", use_cache: bool = True) -> dict:
    """对单只港股进行完整分析"""
    numeric_code, full_code = normalize_hk_code(code)
    
    if use_cache:
        cached = _read_cache(full_code, period)
        if cached:
            print(f"📦 使用缓存数据 ({full_code})，缓存有效期 {CACHE_TTL_SECONDS}s", file=sys.stderr)
            return cached

    result = {"code": full_code, "analysis_time": datetime.now().isoformat(), "error": None}

    try:
        # 1. 获取实时行情
        quote = fetch_tencent_quote(numeric_code)
        if not quote or not quote.get("price"):
            result["error"] = f"无法获取 {full_code} 的实时行情"
            return result
        
        current_price = quote["price"]
        result["current_price"] = current_price
        result["price_date"] = quote.get("timestamp", "")
        result["price_change"] = quote.get("change_amount")
        result["price_change_pct"] = quote.get("change_pct")

        # 2. 获取K线数据
        days = period_to_days(period)
        hist = fetch_tencent_kline(numeric_code, days)
        
        if hist.empty or len(hist) < 30:
            result["error"] = f"无法获取 {full_code} 的历史K线数据 (仅获得 {len(hist)} 条)"
            return result
        
        result["data_points"] = len(hist)

        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        volume = hist["Volume"]

        # 3. 技术分析
        technical = {}
        technical["ma_trend"] = calc_ma_trend(close)
        technical["macd"] = calc_macd(close)
        technical["rsi"] = calc_rsi(close)
        technical["kdj"] = calc_kdj(high, low, close)
        technical["bollinger"] = calc_bollinger(close)
        technical["volume"] = calc_volume_analysis(volume, close)
        result["technical"] = technical

        # 4. 基本面分析
        fundamental = get_fundamentals(quote)
        result["fundamental"] = fundamental

        # 5. 综合建议
        result["recommendation"] = generate_recommendation(technical, fundamental, current_price)

        # 6. 写入缓存
        if result.get("error") is None:
            _write_cache(full_code, period, result)

    except Exception as e:
        result["error"] = f"分析过程出错: {str(e)}"

    return result


def main():
    parser = argparse.ArgumentParser(description="港股分析工具 (腾讯财经数据源)")
    parser.add_argument("code", help="港股代码 (如 0700.HK, 00700, 腾讯)")
    parser.add_argument("--period", default="6mo", help="数据周期 (1mo/3mo/6mo/1y/2y/5y)")
    parser.add_argument("--output", help="输出JSON文件路径")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存，强制重新请求数据")
    parser.add_argument("--clear-cache", action="store_true", help="清除所有缓存后退出")
    args = parser.parse_args()

    if args.clear_cache:
        import shutil
        cleared = False
        for path in (CACHE_DIR, LEGACY_CACHE_DIR):
            if path.exists():
                shutil.rmtree(path)
                cleared = True
        if cleared:
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
