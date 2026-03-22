"""
股票数据服务
负责：数据获取、缓存、持仓管理
"""

import yfinance as yf
import pandas as pd
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json
import sys
import os

# 添加父目录到路径
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from database import Position, StockData, AnalysisResult, TradeLog
from models import PositionCreate

class StockService:
    def __init__(self, db: Session):
        self.db = db
        self.cache_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'cache')
        os.makedirs(self.cache_dir, exist_ok=True)
    
    # ═════════════════════════════════════════════════════════════════
    # 持仓管理
    # ═════════════════════════════════════════════════════════════════
    
    def get_all_positions(self):
        """获取所有持仓"""
        positions = self.db.query(Position).all()
        # 更新实时价格
        for pos in positions:
            try:
                quote = self.get_realtime_quote(pos.ticker)
                pos.current_price = quote['price']
                pos.market_value = pos.shares * pos.current_price
                pos.pnl = pos.market_value - (pos.shares * pos.cost_price)
                pos.pnl_percent = (pos.pnl / (pos.shares * pos.cost_price)) * 100
            except:
                pass
        self.db.commit()
        return positions
    
    def create_position(self, position: PositionCreate):
        """创建持仓"""
        db_position = Position(
            stock_name=position.stock_name,
            ticker=position.ticker,
            shares=position.shares,
            cost_price=position.cost_price,
            strategy=position.strategy,
            notes=position.notes
        )
        self.db.add(db_position)
        self.db.commit()
        self.db.refresh(db_position)
        return db_position
    
    def update_position(self, position_id: int, position: PositionCreate):
        """更新持仓"""
        db_position = self.db.query(Position).filter(Position.id == position_id).first()
        if not db_position:
            raise ValueError("持仓不存在")
        
        db_position.stock_name = position.stock_name
        db_position.ticker = position.ticker
        db_position.shares = position.shares
        db_position.cost_price = position.cost_price
        db_position.strategy = position.strategy
        db_position.notes = position.notes
        
        self.db.commit()
        self.db.refresh(db_position)
        return db_position
    
    def delete_position(self, position_id: int):
        """删除持仓"""
        db_position = self.db.query(Position).filter(Position.id == position_id).first()
        if not db_position:
            raise ValueError("持仓不存在")
        self.db.delete(db_position)
        self.db.commit()
    
    # ═════════════════════════════════════════════════════════════════
    # 数据获取
    # ═════════════════════════════════════════════════════════════════
    
    def update_stock_data(self, ticker: str, period: str = "2y"):
        """更新股票数据"""
        # 从yfinance获取
        df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if df.empty:
            raise ValueError(f"无法获取{ticker}的数据")
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        
        # 计算技术指标
        df['MA5'] = df['Close'].rolling(5).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        
        # RSI
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14).mean()
        df['RSI'] = 100 - (100 / (1 + gain / loss))
        
        # ATR
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift(1)).abs()
        low_close = (df['Low'] - df['Close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()
        
        df = df.dropna()
        
        # 保存到数据库
        for date, row in df.iterrows():
            date_str = date.strftime('%Y-%m-%d')
            
            # 检查是否已存在
            existing = self.db.query(StockData).filter(
                StockData.ticker == ticker,
                StockData.date == date_str
            ).first()
            
            if existing:
                existing.open_price = float(row['Open'])
                existing.high_price = float(row['High'])
                existing.low_price = float(row['Low'])
                existing.close_price = float(row['Close'])
                existing.volume = float(row['Volume'])
                existing.ma5 = float(row['MA5'])
                existing.ma20 = float(row['MA20'])
                existing.ma60 = float(row['MA60'])
                existing.rsi = float(row['RSI'])
                existing.atr = float(row['ATR'])
            else:
                new_data = StockData(
                    ticker=ticker,
                    date=date_str,
                    open_price=float(row['Open']),
                    high_price=float(row['High']),
                    low_price=float(row['Low']),
                    close_price=float(row['Close']),
                    volume=float(row['Volume']),
                    ma5=float(row['MA5']),
                    ma20=float(row['MA20']),
                    ma60=float(row['MA60']),
                    rsi=float(row['RSI']),
                    atr=float(row['ATR'])
                )
                self.db.add(new_data)
        
        self.db.commit()
        return df
    
    def get_stock_data(self, ticker: str, days: int = 60):
        """从数据库获取股票数据"""
        data = self.db.query(StockData).filter(
            StockData.ticker == ticker
        ).order_by(StockData.date.desc()).limit(days).all()
        
        if not data:
            return None
        
        df = pd.DataFrame([{
            'date': d.date,
            'open': d.open_price,
            'high': d.high_price,
            'low': d.low_price,
            'close': d.close_price,
            'volume': d.volume,
            'ma5': d.ma5,
            'ma20': d.ma20,
            'ma60': d.ma60,
            'rsi': d.rsi,
            'atr': d.atr
        } for d in data])
        
        return df.iloc[::-1]  # 正序
    
    def get_realtime_quote(self, ticker: str):
        """获取实时行情"""
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # 尝试获取实时价格
        try:
            hist = stock.history(period="1d")
            if not hist.empty:
                current_price = float(hist['Close'].iloc[-1])
                prev_close = float(hist['Close'].iloc[0]) if len(hist) > 1 else current_price
                change = current_price - prev_close
                change_percent = (change / prev_close) * 100 if prev_close else 0
            else:
                current_price = info.get('currentPrice', 0)
                prev_close = info.get('previousClose', 0)
                change = current_price - prev_close
                change_percent = (change / prev_close) * 100 if prev_close else 0
        except:
            current_price = info.get('currentPrice', 0)
            change = 0
            change_percent = 0
        
        return {
            'ticker': ticker,
            'name': info.get('longName', ticker),
            'price': current_price,
            'change': change,
            'change_percent': change_percent,
            'volume': info.get('volume', 0),
            'updated_at': datetime.now().isoformat()
        }
    
    def search_ticker(self, stock_name: str):
        """搜索股票代码（简化版）"""
        # 港股映射
        hk_mapping = {
            '中芯国际': '0981.HK',
            '平安好医生': '1833.HK',
            '叮当健康': '9886.HK',
            '中原建业': '9982.HK',
            '阅文集团': '0772.HK',
            '泰升集团': '0687.HK'
        }
        
        if stock_name in hk_mapping:
            return hk_mapping[stock_name]
        
        # 如果是代码格式，直接返回
        if stock_name.endswith('.HK'):
            return stock_name
        
        raise ValueError(f"无法识别股票: {stock_name}")
    
    # ═════════════════════════════════════════════════════════════════
    # 分析结果
    # ═════════════════════════════════════════════════════════════════
    
    def save_analysis_result(self, ticker: str, result: dict):
        """保存分析结果"""
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        analysis = AnalysisResult(
            ticker=ticker,
            date=date_str,
            action=result.get('signal', {}).get('action', 'HOLD'),
            score=result.get('signal', {}).get('score', 0),
            confidence=result.get('signal', {}).get('confidence', 'LOW'),
            full_data=result
        )
        self.db.add(analysis)
        self.db.commit()
    
    def get_latest_analysis(self, ticker: str):
        """获取最新分析"""
        result = self.db.query(AnalysisResult).filter(
            AnalysisResult.ticker == ticker
        ).order_by(AnalysisResult.created_at.desc()).first()
        
        if result:
            return result.full_data
        return None
