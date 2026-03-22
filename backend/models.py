"""
Pydantic模型 - 请求/响应数据验证
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# ═════════════════════════════════════════════════════════════════════
# 持仓相关
# ═════════════════════════════════════════════════════════════════════

class PositionCreate(BaseModel):
    stock_name: str
    ticker: str
    shares: int
    cost_price: float
    strategy: str = "C"  # A/B/C
    notes: Optional[str] = None

class PositionResponse(BaseModel):
    id: int
    stock_name: str
    ticker: str
    shares: int
    cost_price: float
    current_price: float
    market_value: float
    pnl: float
    pnl_percent: float
    strategy: str
    created_at: datetime
    notes: Optional[str]
    
    class Config:
        from_attributes = True

# ═════════════════════════════════════════════════════════════════════
# 分析相关
# ═════════════════════════════════════════════════════════════════════

class StockAnalysisRequest(BaseModel):
    stock_name: str
    ticker: Optional[str] = None

class SentimentData(BaseModel):
    score: int  # -5 ~ +5
    label: str
    factors: List[str]
    outlook: str
    source: str = "llm"

class TechnicalData(BaseModel):
    current_price: float
    ma5: float
    ma20: float
    ma60: float
    rsi: float
    atr: float
    atr_percent: float
    trend: str  # UP / DOWN / SIDEWAYS

class SignalData(BaseModel):
    action: str  # BUY / SELL / HOLD
    score: float
    confidence: str  # HIGH / MEDIUM / LOW
    stop_loss: float
    position_ratio: float  # 建议仓位比例
    reasons: List[str]

class AnalysisResult(BaseModel):
    stock_name: str
    ticker: str
    signal: SignalData
    sentiment: SentimentData
    technical: TechnicalData
    timestamp: str

# ═════════════════════════════════════════════════════════════════════
# 行情相关
# ═════════════════════════════════════════════════════════════════════

class QuoteData(BaseModel):
    ticker: str
    name: str
    price: float
    change: float
    change_percent: float
    volume: float
    updated_at: str

# ═════════════════════════════════════════════════════════════════════
# 任务相关
# ═════════════════════════════════════════════════════════════════════

class TaskStatus(BaseModel):
    task_id: str
    status: str  # pending / running / completed / failed
    progress: int  # 0-100
    message: str
    created_at: str
    completed_at: Optional[str]
