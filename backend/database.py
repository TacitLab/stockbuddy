"""
数据库模型 - SQLAlchemy
"""

from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'stocks.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# ═════════════════════════════════════════════════════════════════════
# 数据表模型
# ═════════════════════════════════════════════════════════════════════

class Position(Base):
    """持仓表"""
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    stock_name = Column(String(50), nullable=False)
    ticker = Column(String(20), nullable=False, index=True)
    shares = Column(Integer, nullable=False)
    cost_price = Column(Float, nullable=False)
    current_price = Column(Float, default=0)
    market_value = Column(Float, default=0)
    pnl = Column(Float, default=0)  # 盈亏金额
    pnl_percent = Column(Float, default=0)  # 盈亏百分比
    
    # 策略参数
    strategy = Column(String(10), default="C")  # A/B/C
    stop_loss = Column(Float, default=0.08)  # 止损比例
    
    # 元数据
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    notes = Column(Text, nullable=True)

class StockData(Base):
    """股票数据缓存表"""
    __tablename__ = "stock_data"
    
    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    date = Column(String(10), nullable=False)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(Float)
    ma5 = Column(Float)
    ma20 = Column(Float)
    ma60 = Column(Float)
    rsi = Column(Float)
    atr = Column(Float)
    
    updated_at = Column(DateTime, default=datetime.now)

class SentimentData(Base):
    """舆情数据表"""
    __tablename__ = "sentiment_data"
    
    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    date = Column(String(10), nullable=False)
    score = Column(Integer)  # -5 ~ +5
    label = Column(String(20))  # 极度悲观/悲观/中性/乐观/极度乐观
    factors = Column(JSON)  # 影响因素列表
    outlook = Column(String(50))
    source = Column(String(20), default="llm")  # llm / manual / system
    
    created_at = Column(DateTime, default=datetime.now)

class AnalysisResult(Base):
    """分析结果表"""
    __tablename__ = "analysis_results"
    
    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    date = Column(String(10), nullable=False)
    
    # 信号
    action = Column(String(20))  # BUY / SELL / HOLD
    score = Column(Float)  # 综合评分
    confidence = Column(String(10))  # HIGH / MEDIUM / LOW
    
    # 详情
    tech_score = Column(Float)
    fund_score = Column(Float)
    sent_score = Column(Float)
    
    # 止损建议
    suggested_stop = Column(Float)
    position_ratio = Column(Float)
    
    # 完整数据（JSON）
    full_data = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.now)

class TradeLog(Base):
    """交易日志表"""
    __tablename__ = "trade_logs"
    
    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False)
    action = Column(String(10), nullable=False)  # BUY / SELL
    shares = Column(Integer)
    price = Column(Float)
    reason = Column(Text)
    pnl = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)

# ═════════════════════════════════════════════════════════════════════
# 初始化数据库
# ═════════════════════════════════════════════════════════════════════

def init_db():
    Base.metadata.create_all(bind=engine)
    print(f"✅ 数据库初始化完成: {DB_PATH}")

if __name__ == "__main__":
    init_db()
