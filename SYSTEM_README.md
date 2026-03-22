# Stock Buddy 港股AI交易系统

一套完整的港股交易分析系统，支持持仓管理、自动舆情分析、实时交易信号。

## 功能特性

- 📊 **持仓管理** - 记录持仓股票，自动计算盈亏
- 🤖 **AI舆情分析** - 每日自动分析持仓股票舆情（支持Agent调用）
- 📈 **策略信号** - v7策略：三维度评分 + 大盘过滤 + 盈利保护
- 🔍 **手动分析** - 输入任意股票代码，即时生成分析报告
- ⏰ **定时任务** - 每日9:00自动运行分析
- 🌐 **Web界面** - 现代化UI，支持移动端

## 技术栈

- **后端**: FastAPI + SQLite + APScheduler
- **前端**: 原生HTML/CSS/JS
- **数据源**: yfinance（自动切东方财富备用）
- **LLM**: 预留Agent接口（测试阶段用规则引擎）

## 快速启动

```bash
cd stock-buddy
./start.sh
```

访问:
- 前端: http://localhost:8000/app
- API文档: http://localhost:8000/docs

## 目录结构

```
stock-buddy/
├── backend/              # FastAPI后端
│   ├── main.py          # 主入口
│   ├── database.py      # 数据库模型
│   ├── models.py        # Pydantic模型
│   ├── services/        # 业务服务
│   │   ├── stock_service.py
│   │   ├── sentiment_service.py
│   │   ├── strategy_service.py
│   │   └── llm_service.py
│   └── requirements.txt
├── frontend/            # 前端界面
│   ├── index.html
│   ├── style.css
│   └── app.js
├── data/                # 数据存储
│   ├── stocks.db       # SQLite数据库
│   └── cache/          # 股票数据缓存
├── start.sh            # 启动脚本
└── README.md
```

## 使用指南

### 1. 添加持仓

进入"持仓管理"页面，点击"添加持仓"，输入:
- 股票名称（如：中芯国际）
- 股票代码（如：0981.HK）
- 持仓数量
- 成本价
- 选择策略（A/B/C）

### 2. 查看分析

在"总览"页面查看:
- 实时市值和盈亏
- 买入/卖出信号
- 持仓列表

### 3. 手动分析新股票

进入"股票分析"页面:
1. 输入股票名称或代码
2. 点击"分析"
3. 查看综合评分、技术信号、舆情分析

### 4. 每日自动分析

系统每天9:00自动:
1. 更新持仓股票数据
2. 生成舆情分析
3. 计算交易信号
4. 保存分析结果

也可手动点击"运行分析"触发。

## 策略说明

### v7策略架构

```
三维度评分
├── 技术面 (60%): RSI + MACD + 均线系统
├── 基本面 (30%): 营收/利润/PE快照
└── 舆情面 (10%): LLM情绪分析

买入条件:
- 综合评分 ≥ 1.5
- 成交量连续2日放量
- 恒生指数 > MA20（大盘过滤）

止损策略:
- A: 固定12%
- B: ATR × 2.5 动态
- C: 混合自适应（按波动率自动选择）

盈利保护:
- >30%: 保本止损
- >50%: 锁定10%利润
- >100%: 宽追踪止损
```

## API接口

### 持仓管理

```
GET    /api/positions          # 获取所有持仓
POST   /api/positions          # 添加持仓
PUT    /api/positions/{id}     # 更新持仓
DELETE /api/positions/{id}     # 删除持仓
```

### 股票分析

```
POST /api/analyze              # 分析股票
     Body: {"stock_name": "中芯国际", "ticker": "0981.HK"}
```

### 实时行情

```
GET /api/quote/{ticker}        # 获取实时行情
```

### 任务管理

```
POST /api/tasks/daily-analysis # 手动触发每日分析
```

## LLM舆情接入

当前使用规则引擎模拟LLM分析，如需接入真实LLM:

1. 修改 `backend/services/llm_service.py`
2. 替换 `analyze_sentiment()` 方法为真实API调用
3. 支持通过Agent生成分析（已预留接口）

```python
# 调用Agent生成舆情
from llm_sentiment_agent import generate_prompt

prompt = generate_prompt("中芯国际", "2024-06-01", "2024-06-30")
# 发送给Agent，获取JSON结果
```

## 开发计划

- [x] 基础持仓管理
- [x] 股票数据服务
- [x] v7策略回测
- [x] Web界面
- [x] 定时任务
- [ ] 真实LLM接入
- [ ] 邮件/微信推送
- [ ] 历史回测报告
- [ ] 多用户支持

## 许可证

MIT
