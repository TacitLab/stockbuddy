/**
 * Stock Buddy 前端逻辑
 */

const API_BASE = 'http://localhost:8000/api';

// 页面状态
let currentPage = 'dashboard';
let positions = [];

// ═════════════════════════════════════════════════════════════════════
// 初始化
// ═════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initEventListeners();
    loadDashboard();
});

function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.dataset.page;
            switchPage(page);
        });
    });
}

function initEventListeners() {
    // 刷新按钮
    document.getElementById('refresh-btn').addEventListener('click', () => {
        loadCurrentPage();
    });
    
    // 运行分析
    document.getElementById('run-analysis-btn').addEventListener('click', async () => {
        await runDailyAnalysis();
    });
    
    // 添加持仓
    document.getElementById('add-position-btn').addEventListener('click', () => {
        showModal('add-position-modal');
    });
    
    document.getElementById('cancel-add').addEventListener('click', () => {
        hideModal('add-position-modal');
    });
    
    document.querySelector('.modal-close').addEventListener('click', () => {
        hideModal('add-position-modal');
    });
    
    document.getElementById('add-position-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await addPosition();
    });
    
    // 股票分析
    document.getElementById('analyze-btn').addEventListener('click', async () => {
        const input = document.getElementById('stock-search').value.trim();
        if (input) {
            await analyzeStock(input);
        }
    });
    
    document.getElementById('stock-search').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            document.getElementById('analyze-btn').click();
        }
    });
}

// ═════════════════════════════════════════════════════════════════════
// 页面切换
// ═════════════════════════════════════════════════════════════════════

function switchPage(page) {
    currentPage = page;
    
    // 更新导航状态
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.page === page) {
            item.classList.add('active');
        }
    });
    
    // 切换页面内容
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(`page-${page}`).classList.add('active');
    
    // 更新标题
    const titles = {
        dashboard: '总览',
        positions: '持仓管理',
        analysis: '股票分析',
        sentiment: '舆情监控',
        settings: '设置'
    };
    document.getElementById('page-title').textContent = titles[page];
    
    // 加载页面数据
    loadCurrentPage();
}

function loadCurrentPage() {
    switch (currentPage) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'positions':
            loadPositions();
            break;
        case 'sentiment':
            loadSentiment();
            break;
    }
}

// ═════════════════════════════════════════════════════════════════════
// 数据加载
// ═════════════════════════════════════════════════════════════════════

async function loadDashboard() {
    try {
        const response = await fetch(`${API_BASE}/positions`);
        positions = await response.json();
        
        updateDashboardStats();
        renderPositionsTable();
    } catch (error) {
        console.error('加载失败:', error);
        showError('数据加载失败');
    }
}

function updateDashboardStats() {
    const totalValue = positions.reduce((sum, p) => sum + (p.market_value || 0), 0);
    const totalCost = positions.reduce((sum, p) => sum + (p.shares * p.cost_price), 0);
    const totalPnl = totalValue - totalCost;
    const totalPnlPercent = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
    
    document.getElementById('total-value').textContent = formatMoney(totalValue);
    document.getElementById('total-pnl').textContent = `${totalPnl >= 0 ? '+' : ''}${formatMoney(totalPnl)} (${totalPnlPercent.toFixed(2)}%)`;
    document.getElementById('total-pnl').className = `stat-change ${totalPnl >= 0 ? 'positive' : 'negative'}`;
    
    document.getElementById('position-count').textContent = positions.length;
    
    // 统计买入信号
    const buySignals = positions.filter(p => p.pnl_percent < -5).length; // 简化逻辑
    document.getElementById('buy-signals').textContent = buySignals;
}

function renderPositionsTable() {
    const tbody = document.getElementById('positions-tbody');
    
    if (positions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-state">暂无持仓</td></tr>';
        return;
    }
    
    tbody.innerHTML = positions.map(p => {
        const pnlClass = p.pnl >= 0 ? 'positive' : 'negative';
        const signal = p.pnl_percent < -10 ? 'BUY' : p.pnl_percent > 20 ? 'SELL' : 'HOLD';
        const signalClass = signal.toLowerCase();
        
        return `
            <tr>
                <td><strong>${p.stock_name}</strong></td>
                <td>${p.ticker}</td>
                <td>${p.shares}</td>
                <td>${p.cost_price.toFixed(3)}</td>
                <td>${(p.current_price || 0).toFixed(3)}</td>
                <td>${formatMoney(p.market_value || 0)}</td>
                <td class="${pnlClass}">${p.pnl >= 0 ? '+' : ''}${formatMoney(p.pnl)} (${p.pnl_percent.toFixed(2)}%)</td>
                <td><span class="signal-tag ${signalClass}">${signal}</span></td>
                <td>
                    <button class="btn btn-sm" onclick="viewPosition(${p.id})">详情</button>
                </td>
            </tr>
        `;
    }).join('');
}

async function loadPositions() {
    try {
        const response = await fetch(`${API_BASE}/positions`);
        positions = await response.json();
        
        const tbody = document.getElementById('manage-positions-tbody');
        
        if (positions.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-state">暂无持仓</td></tr>';
            return;
        }
        
        tbody.innerHTML = positions.map(p => {
            const pnlClass = p.pnl >= 0 ? 'positive' : 'negative';
            
            return `
                <tr>
                    <td>${p.stock_name}</td>
                    <td>${p.ticker}</td>
                    <td>${p.shares}</td>
                    <td>${p.cost_price.toFixed(3)}</td>
                    <td>${(p.current_price || 0).toFixed(3)}</td>
                    <td class="${pnlClass}">${p.pnl >= 0 ? '+' : ''}${formatMoney(p.pnl)}</td>
                    <td>${p.strategy}</td>
                    <td>
                        <button class="btn btn-sm btn-danger" onclick="deletePosition(${p.id})">删除</button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (error) {
        console.error('加载失败:', error);
    }
}

async function loadSentiment() {
    const list = document.getElementById('sentiment-list');
    
    if (positions.length === 0) {
        list.innerHTML = '<p class="empty-state">请先添加持仓股票</p>';
        return;
    }
    
    list.innerHTML = '<p class="empty-state">舆情分析功能开发中...</p>';
}

// ═════════════════════════════════════════════════════════════════════
// 持仓操作
// ═════════════════════════════════════════════════════════════════════

async function addPosition() {
    const data = {
        stock_name: document.getElementById('pos-name').value,
        ticker: document.getElementById('pos-ticker').value,
        shares: parseInt(document.getElementById('pos-shares').value),
        cost_price: parseFloat(document.getElementById('pos-cost').value),
        strategy: document.getElementById('pos-strategy').value,
        notes: document.getElementById('pos-notes').value
    };
    
    try {
        const response = await fetch(`${API_BASE}/positions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            hideModal('add-position-modal');
            document.getElementById('add-position-form').reset();
            loadCurrentPage();
            showSuccess('持仓添加成功');
        } else {
            throw new Error('添加失败');
        }
    } catch (error) {
        showError('添加失败: ' + error.message);
    }
}

async function deletePosition(id) {
    if (!confirm('确定删除此持仓吗？')) return;
    
    try {
        const response = await fetch(`${API_BASE}/positions/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadPositions();
            showSuccess('删除成功');
        }
    } catch (error) {
        showError('删除失败');
    }
}

// ═════════════════════════════════════════════════════════════════════
// 股票分析
// ═════════════════════════════════════════════════════════════════════

async function analyzeStock(input) {
    const resultDiv = document.getElementById('analysis-result');
    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = '<div class="result-loading">分析中，请稍候...</div>';
    
    try {
        // 判断是名称还是代码
        const isTicker = input.endsWith('.HK') || /^\d{4,5}$/.test(input);
        
        const requestData = isTicker 
            ? { stock_name: input, ticker: input }
            : { stock_name: input };
        
        const response = await fetch(`${API_BASE}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestData)
        });
        
        const result = await response.json();
        
        if (response.ok) {
            renderAnalysisResult(result);
        } else {
            throw new Error(result.detail || '分析失败');
        }
    } catch (error) {
        resultDiv.innerHTML = `<div class="result-card"><p class="negative">分析失败: ${error.message}</p></div>`;
    }
}

function renderAnalysisResult(result) {
    const resultDiv = document.getElementById('analysis-result');
    
    const signalClass = result.signal.action.toLowerCase();
    const sentimentClass = result.sentiment.score >= 0 ? 'positive' : 'negative';
    
    resultDiv.innerHTML = `
        <div class="result-card">
            <div class="result-header">
                <div>
                    <div class="result-title">${result.stock_name} (${result.ticker})</div>
                    <div style="color: var(--text-secondary); font-size: 13px; margin-top: 4px;">
                        分析时间: ${new Date(result.timestamp).toLocaleString()}
                    </div>
                </div>
                <span class="signal-tag ${signalClass}">${result.signal.action}</span>
            </div>
            
            <div class="result-body">
                <div class="result-item">
                    <div class="result-label">综合评分</div>
                    <div class="result-value" style="color: ${result.signal.score >= 0 ? 'var(--success)' : 'var(--danger)'}">
                        ${result.signal.score >= 0 ? '+' : ''}${result.signal.score.toFixed(2)}
                    </div>
                </div>
                <div class="result-item">
                    <div class="result-label">当前价格</div>
                    <div class="result-value">${result.technical.current_price.toFixed(3)}</div>
                </div>
                <div class="result-item">
                    <div class="result-label">建议仓位</div>
                    <div class="result-value">${(result.signal.position_ratio * 100).toFixed(0)}%</div>
                </div>
            </div>
        </div>
        
        <div class="result-card">
            <h4 style="margin-bottom: 16px;">技术分析</h4>
            <div class="result-body">
                <div class="result-item">
                    <div class="result-label">RSI</div>
                    <div class="result-value">${result.technical.rsi.toFixed(1)}</div>
                </div>
                <div class="result-item">
                    <div class="result-label">趋势</div>
                    <div class="result-value" style="font-size: 16px;">${result.technical.trend === 'UP' ? '上涨📈' : result.technical.trend === 'DOWN' ? '下跌📉' : '震荡➡️'}</div>
                </div>
                <div class="result-item">
                    <div class="result-label">止损位</div>
                    <div class="result-value">${(result.signal.stop_loss * 100).toFixed(1)}%</div>
                </div>
            </div>
        </div>
        
        <div class="result-card">
            <h4 style="margin-bottom: 16px;">舆情分析</h4>
            <div style="display: flex; align-items: center; gap: 16px; margin-bottom: 12px;">
                <span style="font-size: 32px; font-weight: 700; color: ${sentimentClass};">
                    ${result.sentiment.score > 0 ? '+' : ''}${result.sentiment.score}
                </span>
                <span>${result.sentiment.label}</span>
            </div>
            <div style="color: var(--text-secondary); font-size: 14px;">
                <strong>影响因素:</strong> ${result.sentiment.factors.join('、')}
            </div>
            <div style="color: var(--text-secondary); font-size: 14px; margin-top: 8px;">
                <strong>展望:</strong> ${result.sentiment.outlook}
            </div>
        </div>
        
        <div class="result-card">
            <h4 style="margin-bottom: 16px;">分析理由</h4>
            <ul style="color: var(--text-secondary); font-size: 14px; padding-left: 20px;">
                ${result.signal.reasons.map(r => `<li>${r}</li>`).join('')}
            </ul>
        </div>
    `;
}

// ═════════════════════════════════════════════════════════════════════
// 任务操作
// ═════════════════════════════════════════════════════════════════════

async function runDailyAnalysis() {
    const btn = document.getElementById('run-analysis-btn');
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span> 分析中...';
    
    try {
        const response = await fetch(`${API_BASE}/tasks/daily-analysis`, {
            method: 'POST'
        });
        
        if (response.ok) {
            showSuccess('每日分析任务已启动');
        } else {
            throw new Error('启动失败');
        }
    } catch (error) {
        showError('启动失败: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>▶️</span> 运行分析';
    }
}

// ═════════════════════════════════════════════════════════════════════
// 工具函数
// ═════════════════════════════════════════════════════════════════════

function formatMoney(amount) {
    if (amount === undefined || amount === null) return '--';
    if (amount >= 100000000) {
        return (amount / 100000000).toFixed(2) + '亿';
    } else if (amount >= 10000) {
        return (amount / 10000).toFixed(2) + '万';
    }
    return amount.toFixed(2);
}

function showModal(id) {
    document.getElementById(id).classList.remove('hidden');
}

function hideModal(id) {
    document.getElementById(id).classList.add('hidden');
}

function showSuccess(message) {
    // 简化实现，实际可用 toast
    console.log('✅', message);
}

function showError(message) {
    console.error('❌', message);
    alert(message);
}

// ═════════════════════════════════════════════════════════════════════
// 其他功能
// ═════════════════════════════════════════════════════════════════════

function viewPosition(id) {
    const pos = positions.find(p => p.id === id);
    if (pos) {
        alert(`股票: ${pos.stock_name}\n代码: ${pos.ticker}\n持仓: ${pos.shares}股\n成本: ${pos.cost_price}\n策略: ${pos.strategy}\n\n${pos.notes || ''}`);
    }
}
