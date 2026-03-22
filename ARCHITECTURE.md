# Stock Buddy 交易系统

## 架构

```
stock-buddy/
├── backend/           # FastAPI后端
│   ├── main.py        # 主入口
│   ├── database.py    # 数据库模型
│   ├── models.py      # Pydantic模型
│   ├── services/
│   │   ├── stock_service.py    # 股票数据服务
│   │   ├── sentiment_service.py # 舆情分析服务
│   │   ├── strategy_service.py  # 策略服务
│   │   └── llm_service.py       # LLM服务
│   └── tasks.py       # 定时任务
├── frontend/          # 前端
│   ├── index.html     # 主页面
│   ├── app.js         # 前端逻辑
│   └── style.css      # 样式
└── data/              # 数据存储
    ├── stocks.db      # SQLite数据库
    └── cache/         # 股票数据缓存
```

## 功能模块

1. **持仓管理** - CRUD持仓股票，记录成本、数量
2. **自动舆情** - 每日定时分析持仓股票舆情
3. **策略信号** - 实时计算买入/卖出信号
4. **手动分析** - 输入新股票代码，即时分析
5. **LLM集成** - 自动/手动触发舆情分析

## 运行

```bash
# 安装依赖
pip install fastapi uvicorn sqlalchemy apscheduler pandas yfinance

# 启动后端
cd backend && uvicorn main:app --reload --port 8000

# 前端直接打开 frontend/index.html
```
