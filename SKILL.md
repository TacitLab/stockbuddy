---
name: stock-buddy
description: 港股分析助手，提供港股技术面和基本面综合分析，给出买入/卖出操作建议。支持单只股票查询分析、持仓批量分析和持仓管理。当用户提到"港股"、"股票分析"、"持仓分析"、"买入建议"、"卖出建议"、港股代码（如 0700.HK、700）或港股公司名称（如腾讯、阿里、比亚迪）时触发此技能。
---

# 港股分析助手 (Stock Buddy)

## 概述

港股技术面与基本面综合分析工具，输出量化评分和明确操作建议（强烈买入/买入/持有/卖出/强烈卖出）。

三大核心场景：
1. **单只股票分析** — 对指定港股进行完整技术面+基本面分析，给出操作建议
2. **持仓批量分析** — 对用户所有持仓股票批量分析，给出各股操作建议和整体盈亏统计
3. **持仓管理** — 增删改查持仓记录

## 环境准备

首次使用时运行安装脚本，确认 Python 依赖就绪：

```bash
bash {{SKILL_DIR}}/scripts/install_deps.sh
```

所需依赖：`numpy`、`pandas`（无需 yfinance，已改用腾讯财经数据源）

## 核心工作流

### 场景一：分析单只股票

触发示例："分析腾讯"、"0700.HK 能不能买"、"看看比亚迪怎么样"、"帮我看下 9988"

**步骤：**

1. **识别股票代码**
   - 用户提供数字代码 → 标准化为 `XXXX.HK` 格式（自动补零）
   - 用户提供中文名称 → 查阅 `references/hk_stock_codes.md` 匹配对应代码
   - 无法匹配时 → 询问用户确认具体代码

2. **执行分析脚本**
   ```bash
   python3 {{SKILL_DIR}}/scripts/analyze_stock.py <代码> --period 6mo
   ```
   可选周期参数：`1mo` / `3mo` / `6mo`（默认）/ `1y` / `2y` / `5y`

   **缓存机制**：脚本内置 10 分钟缓存，同一股票短时间内重复分析不会重复请求腾讯财经。若用户明确要求"刷新数据"或"重新分析"，加 `--no-cache` 参数强制刷新。清除所有缓存：`--clear-cache`。

3. **解读并呈现结果**
   - 脚本输出 JSON 格式分析数据
   - 按 `references/output_templates.md` 中"单只股票分析报告"模板转化为用户友好的中文报告
   - **结尾必须附上风险免责提示**

### 场景二：持仓批量分析

触发示例："分析我的持仓"、"看看我的股票"、"持仓怎么样了"

**步骤：**

1. **检查持仓数据**
   ```bash
   python3 {{SKILL_DIR}}/scripts/portfolio_manager.py list
   ```

2. **持仓为空时** → 引导用户添加持仓（参见场景三的添加操作）

3. **执行批量分析**
   ```bash
   python3 {{SKILL_DIR}}/scripts/portfolio_manager.py analyze
   ```

4. **解读并呈现结果**
   - 按 `references/output_templates.md` 中"持仓批量分析报告"模板呈现
   - 包含每只股票的操作建议和整体盈亏汇总
   - **结尾必须附上风险免责提示**

### 场景三：持仓管理

触发示例："添加腾讯持仓"、"我买了 100 股比亚迪"、"删除阿里持仓"

| 操作 | 命令 |
|------|------|
| 添加 | `python3 {{SKILL_DIR}}/scripts/portfolio_manager.py add <代码> --price <买入价> --shares <数量> [--date <日期>] [--note <备注>]` |
| 查看 | `python3 {{SKILL_DIR}}/scripts/portfolio_manager.py list` |
| 更新 | `python3 {{SKILL_DIR}}/scripts/portfolio_manager.py update <代码> [--price <价格>] [--shares <数量>] [--note <备注>]` |
| 移除 | `python3 {{SKILL_DIR}}/scripts/portfolio_manager.py remove <代码>` |

添加持仓时，若用户未提供日期，默认使用当天日期。若用户提供了自然语言信息（如"我上周花 350 买了 100 股腾讯"），提取价格、数量、日期等参数后执行命令。

## 分析方法论

综合评分体系覆盖技术面（约 60% 权重）和基本面（约 40% 权重），最终评分范围约 -10 到 +10：

| 评分区间 | 操作建议 |
|----------|----------|
| ≥ 5 | 🟢🟢 强烈买入 |
| 2 ~ 4 | 🟢 买入 |
| -1 ~ 1 | 🟡 持有/观望 |
| -4 ~ -2 | 🔴 卖出 |
| ≤ -5 | 🔴🔴 强烈卖出 |

详细的技术指标解读与评分标准参见 `references/technical_indicators.md`。

## 重要注意事项

- 所有分析仅供参考，**不构成投资建议**
- 数据来源为 **腾讯财经**，实时准确
- 港股没有涨跌停限制，波动风险更大
- 每次分析结果末尾**必须**附上风险免责提示
- 技术分析在市场极端情况下可能失效
- 建议用户结合宏观经济环境、行业趋势和公司基本面综合判断

## 资源文件

| 文件 | 用途 |
|------|------|
| `scripts/analyze_stock.py` | 核心分析脚本，获取数据并计算技术指标和基本面评分 |
| `scripts/portfolio_manager.py` | 持仓管理脚本，支持增删改查和批量分析 |
| `scripts/install_deps.sh` | Python 依赖安装脚本 |
| `references/technical_indicators.md` | 技术指标详解和评分标准 |
| `references/hk_stock_codes.md` | 常见港股代码与中文名称映射表 |
| `references/output_templates.md` | 分析报告输出模板 |
