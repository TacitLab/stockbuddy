"""
舆情数据服务
"""

from sqlalchemy.orm import Session
from datetime import datetime
from database import SentimentData

class SentimentService:
    def __init__(self, db: Session):
        self.db = db
    
    def save_sentiment(self, ticker: str, sentiment: dict):
        """保存舆情分析结果"""
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        # 检查是否已存在
        existing = self.db.query(SentimentData).filter(
            SentimentData.ticker == ticker,
            SentimentData.date == date_str
        ).first()
        
        if existing:
            existing.score = sentiment.get('score', 0)
            existing.label = sentiment.get('label', '中性')
            existing.factors = sentiment.get('factors', [])
            existing.outlook = sentiment.get('outlook', '')
            existing.source = sentiment.get('source', 'llm')
        else:
            new_sentiment = SentimentData(
                ticker=ticker,
                date=date_str,
                score=sentiment.get('score', 0),
                label=sentiment.get('label', '中性'),
                factors=sentiment.get('factors', []),
                outlook=sentiment.get('outlook', ''),
                source=sentiment.get('source', 'llm')
            )
            self.db.add(new_sentiment)
        
        self.db.commit()
    
    def get_sentiment(self, ticker: str, days: int = 30):
        """获取最近N天的舆情数据"""
        sentiments = self.db.query(SentimentData).filter(
            SentimentData.ticker == ticker
        ).order_by(SentimentData.date.desc()).limit(days).all()
        
        return [{
            'date': s.date,
            'score': s.score,
            'label': s.label,
            'factors': s.factors,
            'outlook': s.outlook
        } for s in sentiments]
    
    def get_latest_sentiment(self, ticker: str):
        """获取最新舆情"""
        sentiment = self.db.query(SentimentData).filter(
            SentimentData.ticker == ticker
        ).order_by(SentimentData.date.desc()).first()
        
        if sentiment:
            return {
                'date': sentiment.date,
                'score': sentiment.score,
                'label': sentiment.label,
                'factors': sentiment.factors,
                'outlook': sentiment.outlook
            }
        return None
