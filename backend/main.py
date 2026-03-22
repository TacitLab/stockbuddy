"""
Stock Buddy 交易系统 - 主入口
FastAPI + SQLite + APScheduler
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import uvicorn

from database import init_db, SessionLocal
from models import PositionCreate, PositionResponse, StockAnalysisRequest, AnalysisResult
from services.stock_service import StockService
from services.sentiment_service import SentimentService
from services.strategy_service import StrategyService
from services.llm_service import LLMService

# 初始化数据库
init_db()

# 定时任务调度器
scheduler = AsyncIOScheduler()

async def daily_analysis_task():
    """每日定时任务：分析所有持仓股票"""
    print(f"[{datetime.now()}] 开始每日自动分析...")
    db = SessionLocal()
    try:
        stock_service = StockService(db)
        sentiment_service = SentimentService(db)
        strategy_service = StrategyService(db)
        llm_service = LLMService()
        
        # 获取所有持仓
        positions = stock_service.get_all_positions()
        
        for pos in positions:
            try:
                # 1. 更新股票数据
                stock_data = stock_service.update_stock_data(pos.ticker)
                
                # 2. 生成舆情分析
                sentiment = await llm_service.analyze_sentiment(pos.name, pos.ticker)
                sentiment_service.save_sentiment(pos.ticker, sentiment)
                
                # 3. 计算策略信号
                signal = strategy_service.calculate_signal(
                    pos.ticker, 
                    stock_data,
                    sentiment['score']
                )
                
                # 4. 保存分析结果
                stock_service.save_analysis_result(pos.ticker, {
                    'signal': signal,
                    'sentiment': sentiment,
                    'updated_at': datetime.now().isoformat()
                })
                
                print(f"  ✅ {pos.name}: {signal['action']} (评分:{signal['score']:.2f})")
                
            except Exception as e:
                print(f"  ❌ {pos.name}: {e}")
                
        print(f"[{datetime.now()}] 每日分析完成")
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print("🚀 Stock Buddy 交易系统启动")
    
    # 启动定时任务（每天9:00运行）
    scheduler.add_job(
        daily_analysis_task,
        CronTrigger(hour=9, minute=0),
        id='daily_analysis',
        replace_existing=True
    )
    scheduler.start()
    print("⏰ 定时任务已启动（每天9:00）")
    
    yield
    
    # 关闭时
    scheduler.shutdown()
    print("🛑 系统关闭")

app = FastAPI(
    title="Stock Buddy API",
    description="港股AI交易分析系统",
    version="1.0.0",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═════════════════════════════════════════════════════════════════════
# API路由
# ═════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {"message": "Stock Buddy API", "version": "1.0.0"}

# ═════════════════════════════════════════════════════════════════════
# 持仓管理
# ═════════════════════════════════════════════════════════════════════

@app.get("/api/positions", response_model=list[PositionResponse])
async def get_positions():
    """获取所有持仓"""
    db = SessionLocal()
    try:
        service = StockService(db)
        return service.get_all_positions()
    finally:
        db.close()

@app.post("/api/positions", response_model=PositionResponse)
async def create_position(position: PositionCreate):
    """添加持仓"""
    db = SessionLocal()
    try:
        service = StockService(db)
        return service.create_position(position)
    finally:
        db.close()

@app.delete("/api/positions/{position_id}")
async def delete_position(position_id: int):
    """删除持仓"""
    db = SessionLocal()
    try:
        service = StockService(db)
        service.delete_position(position_id)
        return {"message": "删除成功"}
    finally:
        db.close()

@app.put("/api/positions/{position_id}", response_model=PositionResponse)
async def update_position(position_id: int, position: PositionCreate):
    """更新持仓"""
    db = SessionLocal()
    try:
        service = StockService(db)
        return service.update_position(position_id, position)
    finally:
        db.close()

# ═════════════════════════════════════════════════════════════════════
# 分析功能
# ═════════════════════════════════════════════════════════════════════

@app.post("/api/analyze", response_model=AnalysisResult)
async def analyze_stock(request: StockAnalysisRequest):
    """手动分析股票（支持新增股票）"""
    db = SessionLocal()
    try:
        stock_service = StockService(db)
        sentiment_service = SentimentService(db)
        strategy_service = StrategyService(db)
        llm_service = LLMService()
        
        # 1. 获取/更新股票数据
        ticker = request.ticker if request.ticker else stock_service.search_ticker(request.stock_name)
        stock_data = stock_service.update_stock_data(ticker)
        
        # 2. 生成舆情分析（异步）
        sentiment = await llm_service.analyze_sentiment(request.stock_name, ticker)
        sentiment_service.save_sentiment(ticker, sentiment)
        
        # 3. 计算策略信号
        signal = strategy_service.calculate_signal(ticker, stock_data, sentiment['score'])
        
        # 4. 技术分析详情
        tech_analysis = strategy_service.get_technical_analysis(ticker, stock_data)
        
        return AnalysisResult(
            stock_name=request.stock_name,
            ticker=ticker,
            signal=signal,
            sentiment=sentiment,
            technical=tech_analysis,
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.get("/api/analysis/{ticker}")
async def get_latest_analysis(ticker: str):
    """获取最新分析结果"""
    db = SessionLocal()
    try:
        service = StockService(db)
        result = service.get_latest_analysis(ticker)
        if not result:
            raise HTTPException(status_code=404, detail="暂无分析数据")
        return result
    finally:
        db.close()

# ═════════════════════════════════════════════════════════════════════
# 实时行情
# ═════════════════════════════════════════════════════════════════════

@app.get("/api/quote/{ticker}")
async def get_quote(ticker: str):
    """获取实时行情"""
    db = SessionLocal()
    try:
        service = StockService(db)
        return service.get_realtime_quote(ticker)
    finally:
        db.close()

# ═════════════════════════════════════════════════════════════════════
# 手动触发任务
# ═════════════════════════════════════════════════════════════════════

@app.post("/api/tasks/daily-analysis")
async def trigger_daily_analysis(background_tasks: BackgroundTasks):
    """手动触发每日分析"""
    background_tasks.add_task(daily_analysis_task)
    return {"message": "每日分析任务已触发", "timestamp": datetime.now().isoformat()}

# ═════════════════════════════════════════════════════════════════════
# 前端静态文件
# ═════════════════════════════════════════════════════════════════════

app.mount("/app", StaticFiles(directory="../frontend", html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
