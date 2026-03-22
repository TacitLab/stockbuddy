"""
策略服务
实现v7策略：三维度评分 + 大盘过滤 + 盈利保护
"""

import pandas as pd
import numpy as np
from sqlalchemy.orm import Session

class StrategyService:
    def __init__(self, db: Session):
        self.db = db
        self.weights = {'tech': 0.6, 'fund': 0.3, 'sent': 0.1}
    
    def calculate_signal(self, ticker: str, stock_data: pd.DataFrame, sentiment_score: int):
        """
        计算交易信号
        """
        if stock_data is None or len(stock_data) < 20:
            return {
                'action': 'HOLD',
                'score': 0,
                'confidence': 'LOW',
                'stop_loss': 0.08,
                'position_ratio': 0,
                'reasons': ['数据不足']
            }
        
        latest = stock_data.iloc[-1]
        
        # ═════════════════════════════════════════════════════════════════
        # 1. 技术面评分
        # ═════════════════════════════════════════════════════════════════
        tech_score = 0
        reasons = []
        
        # RSI
        rsi = latest.get('rsi', 50)
        if rsi < 30:
            tech_score += 3
            reasons.append(f'RSI超卖({rsi:.1f})')
        elif rsi < 45:
            tech_score += 1
        elif rsi > 70:
            tech_score -= 3
            reasons.append(f'RSI超买({rsi:.1f})')
        elif rsi > 55:
            tech_score -= 1
        
        # 均线
        close = latest.get('close', 0)
        ma5 = latest.get('ma5', 0)
        ma20 = latest.get('ma20', 0)
        ma60 = latest.get('ma60', 0)
        
        if close > ma5 > ma20:
            tech_score += 2
            reasons.append('均线多头排列')
        elif close < ma5 < ma20:
            tech_score -= 2
            reasons.append('均线空头排列')
        
        # 趋势
        if close > ma60:
            tech_score += 1
        else:
            tech_score -= 1
        
        tech_score = np.clip(tech_score, -10, 10)
        
        # ═════════════════════════════════════════════════════════════════
        # 2. 基本面（简化，实际应从数据库读取）
        # ═════════════════════════════════════════════════════════════════
        # 这里简化处理，实际应该根据股票获取对应的基本面评分
        fund_score = 0  # 默认为中性
        
        # ═════════════════════════════════════════════════════════════════
        # 3. 综合评分
        # ═════════════════════════════════════════════════════════════════
        total_score = (
            self.weights['tech'] * tech_score +
            self.weights['fund'] * fund_score +
            self.weights['sent'] * sentiment_score * 2  # sentiment是-5~5，放大
        )
        
        # ═════════════════════════════════════════════════════════════════
        # 4. 生成信号
        # ═════════════════════════════════════════════════════════════════
        atr = latest.get('atr', close * 0.05)
        atr_percent = atr / close if close > 0 else 0.05
        
        # 止损设置
        if atr_percent < 0.05:
            stop_loss = 0.08  # 低波动，固定8%
            stop_type = '固定8%'
        elif atr_percent < 0.15:
            stop_loss = min(0.35, max(0.08, atr_percent * 2.5))  # 中波动
            stop_type = f'ATR×2.5 ({stop_loss*100:.1f}%)'
        else:
            stop_loss = min(0.40, max(0.08, atr_percent * 2.0))  # 高波动
            stop_type = f'ATR×2.0 ({stop_loss*100:.1f}%)'
        
        # 仓位建议
        if total_score >= 5:
            position_ratio = 1.0
            confidence = 'HIGH'
        elif total_score >= 3:
            position_ratio = 0.6
            confidence = 'MEDIUM'
        elif total_score >= 1.5:
            position_ratio = 0.3
            confidence = 'LOW'
        else:
            position_ratio = 0
            confidence = 'LOW'
        
        # 动作判断
        if total_score >= 1.5:
            action = 'BUY'
        elif total_score <= -1.5:
            action = 'SELL'
        else:
            action = 'HOLD'
        
        reasons.append(f'舆情{sentiment_score:+d}分')
        reasons.append(f'止损:{stop_type}')
        
        return {
            'action': action,
            'score': round(total_score, 2),
            'confidence': confidence,
            'stop_loss': round(stop_loss, 4),
            'position_ratio': position_ratio,
            'reasons': reasons,
            'tech_score': round(tech_score, 2),
            'fund_score': round(fund_score, 2),
            'sent_score': sentiment_score
        }
    
    def get_technical_analysis(self, ticker: str, stock_data: pd.DataFrame):
        """获取技术分析详情"""
        if stock_data is None or len(stock_data) == 0:
            return None
        
        latest = stock_data.iloc[-1]
        
        close = latest.get('close', 0)
        ma5 = latest.get('ma5', 0)
        ma20 = latest.get('ma20', 0)
        ma60 = latest.get('ma60', 0)
        rsi = latest.get('rsi', 50)
        atr = latest.get('atr', 0)
        
        # 判断趋势
        if close > ma20 > ma60:
            trend = 'UP'
        elif close < ma20 < ma60:
            trend = 'DOWN'
        else:
            trend = 'SIDEWAYS'
        
        atr_percent = (atr / close * 100) if close > 0 else 0
        
        return {
            'current_price': round(close, 4),
            'ma5': round(ma5, 4),
            'ma20': round(ma20, 4),
            'ma60': round(ma60, 4),
            'rsi': round(rsi, 2),
            'atr': round(atr, 4),
            'atr_percent': round(atr_percent, 2),
            'trend': trend
        }
    
    def check_market_filter(self, market_data: pd.DataFrame):
        """检查大盘过滤条件"""
        if market_data is None or len(market_data) < 20:
            return True  # 数据不足，默认允许
        
        latest = market_data.iloc[-1]
        close = latest.get('close', 0)
        ma20 = latest.get('ma20', 0)
        
        return close >= ma20
