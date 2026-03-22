"""
llm_sentiment_agent.py — 通过Agent生成舆情数据

用法：
  python3 llm_sentiment_agent.py --generate 中芯国际 2024-06-01 2024-06-30
  
这会产生一个请求，你可以复制给Agent来获取情绪分析
"""

import argparse
import json
from datetime import datetime, timedelta

def generate_prompt(stock_name, date_range):
    """生成给Agent的舆情分析请求"""
    
    # 模拟新闻标题（实际应从新闻API获取）
    mock_news = {
        "中芯国际": [
            "中芯国际Q2营收超预期，先进制程占比提升",
            "半导体行业复苏迹象明显，中芯产能利用率回升",
            "大基金增持中芯国际，看好长期发展",
            "美国制裁影响有限，中芯国产替代加速"
        ],
        "平安好医生": [
            "平安好医生亏损收窄，互联网医疗政策利好",
            "医保支付接入线上问诊，行业迎来拐点",
            "阿里健康京东健康竞争加剧，市场份额受挤压"
        ],
        "叮当健康": [
            "叮当健康持续亏损，即时配送成本居高不下",
            "医药电商价格战激烈，盈利前景不明"
        ],
        "中原建业": [
            "房地产销售持续下滑，代建业务需求萎缩",
            "中原建业股价创历史新低，流动性危机隐现"
        ],
        "阅文集团": [
            "《庆余年2》热播带动阅文IP变现增长",
            "网文改编影视剧大获成功，版权收入提升",
            "短视频冲击长文字阅读，用户增长放缓"
        ],
        "泰升集团": [
            "港股小盘股流动性枯竭，泰升集团成交低迷",
            "地产业务不温不火，缺乏催化剂"
        ]
    }
    
    news = mock_news.get(stock_name, ["暂无相关新闻"])
    
    prompt = f"""请分析【{stock_name}】在 {date_range} 期间的市场情绪。

新闻标题：
{chr(10).join(['- ' + n for n in news])}

请给出：
1. 整体情绪倾向（极度悲观/悲观/中性/乐观/极度乐观）
2. 情绪分数（-5到+5的整数，0为中性）
3. 主要影响因素（政策/业绩/行业/竞争等）
4. 未来1个月预期

返回JSON格式：
{{
    "sentiment_score": 0,
    "sentiment_label": "中性",
    "factors": ["因素1", "因素2"],
    "outlook": "短期震荡"
}}
"""
    return prompt

def main():
    parser = argparse.ArgumentParser(description='通过Agent生成舆情数据')
    parser.add_argument('--generate', nargs=3, metavar=('STOCK', 'START', 'END'),
                        help='生成舆情分析请求，如：--generate 中芯国际 2024-06-01 2024-06-30')
    parser.add_argument('--example', action='store_true', help='显示示例输出')
    
    args = parser.parse_args()
    
    if args.generate:
        stock, start, end = args.generate
        prompt = generate_prompt(stock, f"{start} ~ {end}")
        print("=" * 60)
        print("📋 请将以下内容发送给Agent（我）：")
        print("=" * 60)
        print()
        print(prompt)
        print()
        print("=" * 60)
        print("📥 收到回复后，将JSON结果保存到 data/llm_sentiment.json")
        
    elif args.example:
        example = {
            "中芯国际": {
                "2024-06-15": {
                    "sentiment_score": 3,
                    "sentiment_label": "乐观",
                    "factors": ["业绩超预期", "行业复苏"],
                    "outlook": "短期看涨",
                    "source": "agent_analysis"
                }
            }
        }
        print("示例输出格式（保存到 data/llm_sentiment.json）：")
        print(json.dumps(example, indent=2, ensure_ascii=False))
    else:
        print("LLM舆情Agent接口")
        print("\n用法：")
        print("  python3 llm_sentiment_agent.py --generate 中芯国际 2024-06-01 2024-06-30")
        print("  python3 llm_sentiment_agent.py --example")
        print("\n提示：")
        print("  1. 先用 --generate 产生请求内容")
        print("  2. 将内容发给Agent（我）获取分析")
        print("  3. 把返回的JSON保存到 data/llm_sentiment.json")
        print("  4. 运行 stock_backtest_v7.py 时会自动读取")

if __name__ == "__main__":
    main()
