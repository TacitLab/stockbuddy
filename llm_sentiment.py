"""
llm_sentiment.py — LLM舆情分析器
批量分析股票新闻情绪，输出标准化分数（-5~+5）

用法：
  python3 llm_sentiment.py --init     # 初始化基础情绪数据
  python3 llm_sentiment.py --update   # 更新今日情绪（模拟）
  
实际接入LLM时，需要提供新闻API或爬虫获取标题列表
"""

import json, os, argparse
from datetime import datetime, timedelta

CACHE_FILE = "data/llm_sentiment.json"

def init_base_sentiment():
    """初始化基础情绪数据（按季度）"""
    data = {
        "平安好医生": {
            "2024-01-01": -2, "2024-04-01": -2, "2024-07-01": -1, "2024-10-01": 0,
            "2025-01-01": 1, "2025-04-01": 1, "2025-07-01": 2, "2025-10-01": 2,
            "2026-01-01": 3, "2026-03-01": 3
        },
        "叮当健康": {
            "2024-01-01": -3, "2024-04-01": -3, "2024-07-01": -2, "2024-10-01": -1,
            "2025-01-01": -1, "2025-04-01": 0, "2025-07-01": 1, "2025-10-01": 1,
            "2026-01-01": 2, "2026-03-01": 2
        },
        "中原建业": {
            "2024-01-01": -3, "2024-04-01": -4, "2024-07-01": -4, "2024-10-01": -4,
            "2025-01-01": -4, "2025-04-01": -5, "2025-07-01": -5, "2025-10-01": -5,
            "2026-01-01": -5, "2026-03-01": -5
        },
        "泰升集团": {
            "2024-01-01": -1, "2024-04-01": -1, "2024-07-01": -1, "2024-10-01": -2,
            "2025-01-01": -2, "2025-04-01": -2, "2025-07-01": -2, "2025-10-01": -2,
            "2026-01-01": -2, "2026-03-01": -2
        },
        "阅文集团": {
            "2024-01-01": 1, "2024-04-01": 2, "2024-07-01": 2, "2024-10-01": 2,
            "2025-01-01": 2, "2025-04-01": 3, "2025-07-01": 3, "2025-10-01": 3,
            "2026-01-01": 3, "2026-03-01": 3
        },
        "中芯国际": {
            "2024-01-01": 2, "2024-04-01": 3, "2024-07-01": 3, "2024-10-01": 4,
            "2025-01-01": 4, "2025-04-01": 4, "2025-07-01": 5, "2025-10-01": 5,
            "2026-01-01": 5, "2026-03-01": 4
        }
    }
    
    # 展开为日级数据（线性插值）
    daily_data = {}
    for stock, quarters in data.items():
        daily_data[stock] = {}
        dates = sorted(quarters.keys())
        for i, date_str in enumerate(dates):
            current_date = datetime.strptime(date_str, "%Y-%m-%d")
            score = quarters[date_str]
            
            # 计算该季度的结束日期
            if i < len(dates) - 1:
                next_date = datetime.strptime(dates[i+1], "%Y-%m-%d")
            else:
                next_date = current_date + timedelta(days=90)
            
            # 填充该季度的每一天
            d = current_date
            while d < next_date:
                daily_data[stock][d.strftime("%Y-%m-%d")] = score
                d += timedelta(days=1)
    
    save_sentiment(daily_data)
    print(f"✅ 已初始化 {len(daily_data)} 只股票的情绪数据")
    return daily_data

def save_sentiment(data):
    """保存情绪数据"""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_sentiment():
    """加载情绪数据"""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def analyze_news_llm(stock_name, news_list):
    """
    模拟LLM分析新闻情绪
    实际使用时替换为真实LLM API调用
    
    输入：news_list = ["标题1", "标题2", ...]
    输出：-5 ~ +5 的情绪分数
    """
    # 关键词情绪映射（简化版，实际用LLM）
    positive_words = ['大涨', '突破', '利好', '增持', '回购', '超预期', '盈利', '增长', '推荐', '买入']
    negative_words = ['大跌', '跌破', '利空', '减持', '亏损', '不及预期', '下跌', '卖出', '回避', '风险']
    
    score = 0
    for news in news_list:
        for w in positive_words:
            if w in news:
                score += 1
        for w in negative_words:
            if w in news:
                score -= 1
    
    # 归一化到 -5~+5
    return max(-5, min(5, score))

def get_sentiment_for_date(stock_name, date_str, sentiment_data):
    """获取某股票某日的情绪分数"""
    if stock_name in sentiment_data:
        return sentiment_data[stock_name].get(date_str, 0)
    return 0

def main():
    parser = argparse.ArgumentParser(description='LLM舆情分析器')
    parser.add_argument('--init', action='store_true', help='初始化基础情绪数据')
    parser.add_argument('--show', type=str, help='显示某股票的情绪曲线（如：中芯国际）')
    parser.add_argument('--update', action='store_true', help='更新今日情绪（模拟）')
    
    args = parser.parse_args()
    
    if args.init:
        init_base_sentiment()
    elif args.show:
        data = load_sentiment()
        if args.show in data:
            print(f"\n📊 {args.show} 情绪数据（最近10天）:")
            dates = sorted(data[args.show].keys())[-10:]
            for d in dates:
                score = data[args.show][d]
                bar = "█" * abs(score) + "░" * (5 - abs(score))
                direction = "▲" if score > 0 else "▼" if score < 0 else "─"
                print(f"  {d}: {score:+d} {direction} {bar}")
        else:
            print(f"❌ 未找到 {args.show} 的数据")
    elif args.update:
        print("📝 模拟更新今日情绪...")
        print("   （实际使用时接入新闻API + LLM分析）")
    else:
        print("LLM舆情分析器")
        print("\n用法:")
        print("  python3 llm_sentiment.py --init          # 初始化数据")
        print("  python3 llm_sentiment.py --show 中芯国际  # 查看情绪曲线")
        print("  python3 llm_sentiment.py --update        # 更新今日数据")

if __name__ == "__main__":
    main()
