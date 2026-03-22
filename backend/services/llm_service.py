"""
LLM服务
负责：调用Agent进行舆情分析
"""

import json
import asyncio
from datetime import datetime
from typing import Dict

class LLMService:
    """LLM舆情分析服务"""
    
    def __init__(self):
        # 模拟新闻数据源
        self.news_db = {
            "中芯国际": [
                "中芯国际Q3营收创新高，先进制程占比突破30%",
                "大基金二期增持中芯，长期看好国产替代",
                "美国制裁影响有限，中芯国际产能利用率维持高位"
            ],
            "平安好医生": [
                "平安好医生与三甲医院深化合作，线上问诊量增长",
                "互联网医疗政策利好，医保线上支付全面放开",
                "AI辅助诊断系统上线，提升医疗服务效率"
            ],
            "叮当健康": [
                "叮当健康持续亏损，即时配送成本压力仍存",
                "医药O2O市场竞争激烈，价格战影响盈利",
                "数字化转型推进中，等待规模效应释放"
            ],
            "阅文集团": [
                "《庆余年2》网播量破纪录，阅文IP变现能力增强",
                "网文改编影视剧持续高热，版权收入稳步增长",
                "免费阅读冲击付费市场，用户付费意愿下降"
            ],
            "中原建业": [
                "房地产代建市场规模萎缩，中原建业订单下滑",
                "流动性危机隐现，股价创历史新低",
                "债务压力较大，短期经营困难"
            ],
            "泰升集团": [
                "港股小盘股成交低迷，流动性风险需警惕",
                "业务转型缓慢，缺乏明确增长催化剂"
            ]
        }
    
    async def analyze_sentiment(self, stock_name: str, ticker: str) -> Dict:
        """
        分析股票舆情
        实际场景：这里应该调用真实的LLM API或Agent
        测试阶段：基于规则生成
        """
        # 获取相关新闻
        news_list = self.news_db.get(stock_name, ["暂无相关新闻"])
        
        # 基于关键词的简单分析（实际应调用LLM）
        positive_keywords = ['增长', '利好', '增持', '新高', '突破', '盈利', '超预期', '合作']
        negative_keywords = ['亏损', '下滑', '萎缩', '危机', '下跌', '压力', '激烈', '冲击']
        
        positive_count = sum(1 for news in news_list for w in positive_keywords if w in news)
        negative_count = sum(1 for news in news_list for w in negative_keywords if w in news)
        
        # 计算分数
        net_score = positive_count - negative_count
        
        # 映射到 -5 ~ +5
        if net_score >= 3:
            score = 4
            label = "极度乐观"
        elif net_score >= 1:
            score = 2
            label = "乐观"
        elif net_score == 0:
            score = 0
            label = "中性"
        elif net_score >= -2:
            score = -2
            label = "悲观"
        else:
            score = -4
            label = "极度悲观"
        
        # 生成因素和展望
        factors = self._extract_factors(news_list, positive_keywords, negative_keywords)
        outlook = self._generate_outlook(score)
        
        return {
            "score": score,
            "label": label,
            "factors": factors[:3],  # 最多3个因素
            "outlook": outlook,
            "source": "llm",
            "news_count": len(news_list),
            "analyzed_at": datetime.now().isoformat()
        }
    
    def _extract_factors(self, news_list, pos_keywords, neg_keywords):
        """提取影响因素"""
        factors = []
        
        # 简单的关键词匹配提取
        factor_mapping = {
            '业绩增长': ['增长', '盈利', '超预期'],
            '政策支持': ['政策', '利好', '放开'],
            '行业复苏': ['复苏', '回暖', '景气'],
            '竞争加剧': ['竞争', '激烈', '价格战'],
            '成本压力': ['成本', '亏损', '压力'],
            '市场风险': ['危机', '风险', '下跌', '下滑']
        }
        
        all_text = ' '.join(news_list)
        
        for factor, keywords in factor_mapping.items():
            if any(kw in all_text for kw in keywords):
                factors.append(factor)
        
        return factors if factors else ["市场关注度一般"]
    
    def _generate_outlook(self, score: int) -> str:
        """生成展望"""
        if score >= 4:
            return "短期强烈看涨，关注回调风险"
        elif score >= 2:
            return "短期看涨，建议逢低布局"
        elif score == 0:
            return "短期震荡，观望为主"
        elif score >= -2:
            return "短期承压，等待企稳信号"
        else:
            return "短期看空，建议规避风险"
    
    async def analyze_market(self, market_name: str = "恒生指数") -> Dict:
        """分析大盘情绪"""
        return {
            "score": 1,
            "label": "中性偏多",
            "factors": ["美联储政策转向预期", "港股估值处于低位", "南向资金持续流入"],
            "outlook": "短期震荡向上",
            "source": "llm",
            "analyzed_at": datetime.now().isoformat()
        }
