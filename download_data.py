"""
download_data.py — 在外网环境运行此脚本下载数据缓存
下载完成后将 data/ 目录推送到 repo，内网环境直接读缓存

用法：
  python3 download_data.py
"""

import yfinance as yf
import pandas as pd
import os, time, warnings
warnings.filterwarnings('ignore')

STOCKS = {
    "平安好医生": "1833.HK",
    "叮当健康":   "9886.HK",
    "中原建业":   "9982.HK",
}
PERIOD = "2y"
CACHE_DIR = "data"
os.makedirs(CACHE_DIR, exist_ok=True)

print("📥 Stock Buddy — 数据下载工具")
print(f"   目标目录: {CACHE_DIR}/\n")

for i, (name, ticker) in enumerate(STOCKS.items()):
    sym = ticker.replace(".HK", "")
    fp  = os.path.join(CACHE_DIR, f"{sym}.csv")

    if os.path.exists(fp):
        df = pd.read_csv(fp, index_col=0, parse_dates=True)
        print(f"  ✅ {name} ({ticker}): 已有缓存 {len(df)} 行，跳过")
        continue

    print(f"  🌐 {name} ({ticker}): 下载中...")
    try:
        df = yf.download(ticker, period=PERIOD, auto_adjust=True, progress=False)
        if df.empty:
            print(f"  ❌ {name}: 下载失败（可能仍限速，稍后重试）")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.to_csv(fp)
        print(f"  ✅ {name}: {len(df)} 行 → {fp}")
        print(f"     范围: {df.index[0].date()} ~ {df.index[-1].date()}")
        print(f"     最新收盘: {float(df['Close'].iloc[-1]):.4f}")
    except Exception as e:
        print(f"  ❌ {name}: 失败 - {e}")

    if i < len(STOCKS) - 1:
        time.sleep(5)

print("\n完成！将 data/ 目录推送到 repo 后，内网环境即可读取缓存。")
print("推送命令：")
print("  git add data/")
print("  git commit -m 'chore: add data cache'")
print("  git push")
