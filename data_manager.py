"""
data_manager.py — 港股数据管理器
支持 yfinance（优先）+ 东方财富备用（免费）
带指数退避重试，429限速自动切换源

用法：
  python3 data_manager.py --download-all    # 下载/更新所有股票
  python3 data_manager.py --check           # 检查数据完整性
  python3 data_manager.py --force-refresh   # 强制重新下载
"""

import pandas as pd
import requests
import yfinance as yf
import os, time, json, argparse, warnings
from datetime import datetime, timedelta
from typing import Optional, Dict, List
warnings.filterwarnings('ignore')

CACHE_DIR = "data"
CACHE_META = os.path.join(CACHE_DIR, "meta.json")

STOCKS = {
    "平安好医生": {"ticker": "1833.HK", "em_code": "116.01833"},
    "叮当健康":   {"ticker": "9886.HK", "em_code": "116.09886"},
    "中原建业":   {"ticker": "9982.HK", "em_code": "116.09982"},
    "泰升集团":   {"ticker": "0687.HK", "em_code": "116.00687"},
    "阅文集团":   {"ticker": "0772.HK", "em_code": "116.00772"},
    "中芯国际":   {"ticker": "0981.HK", "em_code": "116.00981"},
}

# 东方财富 API 配置
EM_API_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 重试配置
MAX_RETRIES = 5
BASE_DELAY = 10  # 基础延迟秒数

class DataManager:
    def __init__(self, cache_dir: str = CACHE_DIR):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.meta = self._load_meta()
    
    def _load_meta(self) -> Dict:
        """加载缓存元数据"""
        if os.path.exists(CACHE_META):
            with open(CACHE_META, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_meta(self):
        """保存缓存元数据"""
        with open(CACHE_META, 'w') as f:
            json.dump(self.meta, f, indent=2, default=str)
    
    def _get_cache_path(self, sym: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{sym}.csv")
    
    def _exponential_backoff(self, attempt: int) -> float:
        """指数退避延迟"""
        delay = min(BASE_DELAY * (2 ** attempt), 300)  # 最大5分钟
        jitter = delay * 0.1 * (hash(str(time.time())) % 10 / 10)
        return delay + jitter
    
    def download_yfinance(self, ticker: str, period: str = "2y", 
                          max_retries: int = MAX_RETRIES) -> Optional[pd.DataFrame]:
        """从 yfinance 下载数据，带重试"""
        for attempt in range(max_retries):
            try:
                print(f"    🌐 yfinance: 尝试 {attempt+1}/{max_retries}...")
                df = yf.download(
                    ticker, 
                    period=period, 
                    auto_adjust=True, 
                    progress=False,
                    timeout=30
                )
                if df.empty:
                    print(f"    ⚠️ yfinance: 返回空数据")
                    return None
                
                # 处理多级列名
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                
                print(f"    ✅ yfinance: 成功获取 {len(df)} 行")
                return df
                
            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = any(x in err_str for x in ['too many', '429', 'rate limit', 'limit'])
                
                if is_rate_limit and attempt < max_retries - 1:
                    delay = self._exponential_backoff(attempt)
                    print(f"    ⏳ yfinance: 限速，等待 {delay:.1f}s 后重试...")
                    time.sleep(delay)
                else:
                    print(f"    ❌ yfinance: 失败 - {e}")
                    return None
        return None
    
    def download_eastmoney(self, em_code: str, days: int = 500) -> Optional[pd.DataFrame]:
        """从东方财富下载数据（备用源）"""
        try:
            print(f"    🌐 东方财富: 请求数据...")
            
            # 构造请求参数
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y%m%d')
            
            params = {
                "secid": em_code,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101",  # 日K
                "fqt": "0",    # 不复权
                "beg": start_date,
                "end": end_date,
                "_": int(time.time() * 1000)
            }
            
            resp = requests.get(EM_API_URL, params=params, headers=EM_HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            if 'data' not in data or not data['data'] or 'klines' not in data['data']:
                print(f"    ⚠️ 东方财富: 无数据返回")
                return None
            
            klines = data['data']['klines']
            if not klines:
                print(f"    ⚠️ 东方财富: K线为空")
                return None
            
            # 解析数据
            records = []
            for line in klines:
                parts = line.split(',')
                if len(parts) >= 6:
                    records.append({
                        'Date': parts[0],
                        'Open': float(parts[1]),
                        'Close': float(parts[2]),
                        'Low': float(parts[4]),
                        'High': float(parts[3]),
                        'Volume': float(parts[5])
                    })
            
            df = pd.DataFrame(records)
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            df = df.sort_index()
            
            # 只取最近 N 天
            if len(df) > days:
                df = df.iloc[-days:]
            
            # 列名标准化（和 yfinance 一致）
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
            
            print(f"    ✅ 东方财富: 成功获取 {len(df)} 行")
            return df
            
        except Exception as e:
            print(f"    ❌ 东方财富: 失败 - {e}")
            return None
    
    def download_stock(self, name: str, info: Dict, 
                       force_refresh: bool = False) -> bool:
        """下载单只股票数据，自动切换源"""
        sym = info['ticker'].replace('.HK', '')
        cache_path = self._get_cache_path(sym)
        
        # 检查缓存
        if not force_refresh and os.path.exists(cache_path):
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            print(f"  ✅ {name}: 已有缓存 {len(df)} 行，跳过")
            return True
        
        print(f"\n  📥 {name} ({info['ticker']})")
        
        # 尝试 yfinance
        df = self.download_yfinance(info['ticker'])
        source = "yfinance"
        
        # yfinance 失败，切换东方财富
        if df is None:
            print(f"    🔄 切换到备用源...")
            time.sleep(2)  # 短暂延迟避免并发
            df = self.download_eastmoney(info['em_code'])
            source = "eastmoney"
        
        if df is None or df.empty:
            print(f"  ❌ {name}: 所有数据源均失败")
            return False
        
        # 保存缓存
        df.to_csv(cache_path)
        
        # 更新元数据
        self.meta[sym] = {
            'name': name,
            'ticker': info['ticker'],
            'source': source,
            'downloaded_at': datetime.now().isoformat(),
            'rows': len(df),
            'date_range': {
                'start': df.index[0].strftime('%Y-%m-%d'),
                'end': df.index[-1].strftime('%Y-%m-%d')
            }
        }
        self._save_meta()
        
        print(f"  ✅ {name}: 已保存 {len(df)} 行 ({source})")
        print(f"     范围: {df.index[0].date()} ~ {df.index[-1].date()}")
        
        return True
    
    def download_all(self, force_refresh: bool = False) -> Dict[str, bool]:
        """下载所有股票数据"""
        print("="*60)
        print("📊 Stock Buddy — 数据下载管理器")
        print(f"   缓存目录: {self.cache_dir}")
        print(f"   强制刷新: {'是' if force_refresh else '否'}")
        print("="*60)
        
        results = {}
        for i, (name, info) in enumerate(STOCKS.items()):
            success = self.download_stock(name, info, force_refresh)
            results[name] = success
            
            # 下载间隔，避免触发限速
            if i < len(STOCKS) - 1:
                delay = 3 if success else 5
                time.sleep(delay)
        
        # 打印汇总
        print("\n" + "="*60)
        print("📋 下载汇总")
        print("="*60)
        success_count = sum(1 for v in results.values() if v)
        for name, ok in results.items():
            status = "✅ 成功" if ok else "❌ 失败"
            print(f"  {name}: {status}")
        print(f"\n  总计: {success_count}/{len(results)} 成功")
        
        return results
    
    def check_data(self) -> bool:
        """检查数据完整性"""
        print("="*60)
        print("🔍 数据完整性检查")
        print("="*60)
        
        all_ok = True
        for name, info in STOCKS.items():
            sym = info['ticker'].replace('.HK', '')
            cache_path = self._get_cache_path(sym)
            
            if not os.path.exists(cache_path):
                print(f"  ❌ {name}: 无缓存文件")
                all_ok = False
                continue
            
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            
            if len(df) < 60:
                print(f"  ⚠️ {name}: 数据不足 ({len(df)} 行，建议 >=60)")
                all_ok = False
            else:
                print(f"  ✅ {name}: {len(df)} 行，最新 {df.index[-1].date()}")
        
        return all_ok
    
    def get_cache_info(self) -> pd.DataFrame:
        """获取缓存信息表"""
        if not self.meta:
            return pd.DataFrame()
        
        rows = []
        for sym, info in self.meta.items():
            rows.append({
                '股票': info.get('name', sym),
                '代码': info.get('ticker', sym),
                '数据源': info.get('source', '-'),
                '下载时间': info.get('downloaded_at', '-')[:19],
                '数据条数': info.get('rows', 0),
                '日期范围': f"{info.get('date_range', {}).get('start', '-')} ~ {info.get('date_range', {}).get('end', '-')}"
            })
        
        return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description='Stock Buddy 数据管理器')
    parser.add_argument('--download-all', action='store_true', help='下载/更新所有股票数据')
    parser.add_argument('--check', action='store_true', help='检查数据完整性')
    parser.add_argument('--force-refresh', action='store_true', help='强制重新下载')
    parser.add_argument('--info', action='store_true', help='显示缓存信息')
    
    args = parser.parse_args()
    
    dm = DataManager()
    
    if args.download_all:
        dm.download_all(force_refresh=args.force_refresh)
    elif args.check:
        ok = dm.check_data()
        exit(0 if ok else 1)
    elif args.info:
        info = dm.get_cache_info()
        if info.empty:
            print("暂无缓存数据")
        else:
            print(info.to_string(index=False))
    else:
        # 默认行为：检查 + 提示
        print("Stock Buddy 数据管理器")
        print("\n常用命令:")
        print("  python3 data_manager.py --download-all      # 下载所有数据")
        print("  python3 data_manager.py --check             # 检查数据完整性")
        print("  python3 data_manager.py --force-refresh     # 强制重新下载")
        print("  python3 data_manager.py --info              # 查看缓存信息")


if __name__ == "__main__":
    main()
