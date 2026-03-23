#!/usr/bin/env python3
"""
港股持仓管理工具 - 管理持仓列表并批量分析。

用法:
    python3 portfolio_manager.py list
    python3 portfolio_manager.py add <代码> --price <买入价> --shares <数量> [--date <日期>] [--note <备注>]
    python3 portfolio_manager.py remove <代码>
    python3 portfolio_manager.py update <代码> [--price <价格>] [--shares <数量>] [--note <备注>]
    python3 portfolio_manager.py analyze [--output <输出文件>]

持仓文件默认保存在: ~/.hk_stock_portfolio.json
"""

import sys
import json
import argparse
import os
import time
from datetime import datetime
from pathlib import Path

PORTFOLIO_PATH = Path.home() / ".hk_stock_portfolio.json"


def load_portfolio() -> dict:
    """加载持仓数据"""
    if not PORTFOLIO_PATH.exists():
        return {"positions": [], "updated_at": None}
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_portfolio(data: dict):
    """保存持仓数据"""
    data["updated_at"] = datetime.now().isoformat()
    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_code(code: str) -> str:
    """标准化港股代码"""
    code = code.strip().upper()
    if not code.endswith(".HK"):
        digits = code.lstrip("0")
        if digits.isdigit():
            code = code.zfill(4) + ".HK"
    return code


def list_positions():
    """列出所有持仓"""
    portfolio = load_portfolio()
    positions = portfolio.get("positions", [])
    if not positions:
        print(json.dumps({"message": "持仓为空", "positions": []}, ensure_ascii=False, indent=2))
        return
    print(json.dumps({
        "total_positions": len(positions),
        "positions": positions,
        "portfolio_file": str(PORTFOLIO_PATH),
        "updated_at": portfolio.get("updated_at"),
    }, ensure_ascii=False, indent=2))


def add_position(code: str, price: float, shares: int, date: str = None, note: str = ""):
    """添加持仓"""
    code = normalize_code(code)
    portfolio = load_portfolio()
    positions = portfolio.get("positions", [])

    # 检查是否已存在
    for pos in positions:
        if pos["code"] == code:
            print(json.dumps({"error": f"{code} 已在持仓中，请使用 update 命令更新"}, ensure_ascii=False))
            return

    position = {
        "code": code,
        "buy_price": price,
        "shares": shares,
        "buy_date": date or datetime.now().strftime("%Y-%m-%d"),
        "note": note,
        "added_at": datetime.now().isoformat(),
    }
    positions.append(position)
    portfolio["positions"] = positions
    save_portfolio(portfolio)
    print(json.dumps({"message": f"已添加 {code}", "position": position}, ensure_ascii=False, indent=2))


def remove_position(code: str):
    """移除持仓"""
    code = normalize_code(code)
    portfolio = load_portfolio()
    positions = portfolio.get("positions", [])
    new_positions = [p for p in positions if p["code"] != code]
    if len(new_positions) == len(positions):
        print(json.dumps({"error": f"{code} 不在持仓中"}, ensure_ascii=False))
        return
    portfolio["positions"] = new_positions
    save_portfolio(portfolio)
    print(json.dumps({"message": f"已移除 {code}"}, ensure_ascii=False, indent=2))


def update_position(code: str, price: float = None, shares: int = None, note: str = None):
    """更新持仓信息"""
    code = normalize_code(code)
    portfolio = load_portfolio()
    positions = portfolio.get("positions", [])
    found = False
    for pos in positions:
        if pos["code"] == code:
            if price is not None:
                pos["buy_price"] = price
            if shares is not None:
                pos["shares"] = shares
            if note is not None:
                pos["note"] = note
            pos["updated_at"] = datetime.now().isoformat()
            found = True
            print(json.dumps({"message": f"已更新 {code}", "position": pos}, ensure_ascii=False, indent=2))
            break
    if not found:
        print(json.dumps({"error": f"{code} 不在持仓中"}, ensure_ascii=False))
        return
    portfolio["positions"] = positions
    save_portfolio(portfolio)


def analyze_portfolio(output_file: str = None):
    """批量分析所有持仓"""
    # 延迟导入，避免未安装yfinance时也能管理持仓
    try:
        from analyze_stock import analyze_stock
    except ImportError:
        # 尝试从同目录导入
        script_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, script_dir)
        from analyze_stock import analyze_stock

    portfolio = load_portfolio()
    positions = portfolio.get("positions", [])
    if not positions:
        print(json.dumps({"message": "持仓为空，无法分析"}, ensure_ascii=False, indent=2))
        return

    results = []
    for i, pos in enumerate(positions):
        code = pos["code"]
        print(f"正在分析 {code} ({i+1}/{len(positions)})...", file=sys.stderr)
        analysis = analyze_stock(code)

        # 计算盈亏
        if analysis.get("current_price") and pos.get("buy_price"):
            current = analysis["current_price"]
            buy = pos["buy_price"]
            shares = pos.get("shares", 0)
            pnl = (current - buy) * shares
            pnl_pct = (current - buy) / buy * 100

            analysis["portfolio_info"] = {
                "buy_price": buy,
                "shares": shares,
                "buy_date": pos.get("buy_date"),
                "cost": round(buy * shares, 2),
                "market_value": round(current * shares, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "note": pos.get("note", ""),
            }

        results.append(analysis)

        # 批量请求间隔：避免连续请求触发限频（最后一只不需要等待）
        if i < len(positions) - 1 and not analysis.get("_from_cache"):
            time.sleep(2)

    # 汇总
    total_cost = sum(r.get("portfolio_info", {}).get("cost", 0) for r in results)
    total_value = sum(r.get("portfolio_info", {}).get("market_value", 0) for r in results)
    total_pnl = total_value - total_cost

    summary = {
        "analysis_time": datetime.now().isoformat(),
        "total_positions": len(results),
        "total_cost": round(total_cost, 2),
        "total_market_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0,
        "positions": results,
    }

    output = json.dumps(summary, ensure_ascii=False, indent=2, default=str)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"分析结果已保存至 {output_file}", file=sys.stderr)

    print(output)


def main():
    parser = argparse.ArgumentParser(description="港股持仓管理工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # list
    subparsers.add_parser("list", help="列出所有持仓")

    # add
    add_parser = subparsers.add_parser("add", help="添加持仓")
    add_parser.add_argument("code", help="股票代码")
    add_parser.add_argument("--price", type=float, required=True, help="买入价格")
    add_parser.add_argument("--shares", type=int, required=True, help="持有数量")
    add_parser.add_argument("--date", help="买入日期 (YYYY-MM-DD)")
    add_parser.add_argument("--note", default="", help="备注")

    # remove
    rm_parser = subparsers.add_parser("remove", help="移除持仓")
    rm_parser.add_argument("code", help="股票代码")

    # update
    up_parser = subparsers.add_parser("update", help="更新持仓")
    up_parser.add_argument("code", help="股票代码")
    up_parser.add_argument("--price", type=float, help="买入价格")
    up_parser.add_argument("--shares", type=int, help="持有数量")
    up_parser.add_argument("--note", help="备注")

    # analyze
    analyze_parser = subparsers.add_parser("analyze", help="批量分析持仓")
    analyze_parser.add_argument("--output", help="输出JSON文件")

    args = parser.parse_args()

    if args.command == "list":
        list_positions()
    elif args.command == "add":
        add_position(args.code, args.price, args.shares, args.date, args.note)
    elif args.command == "remove":
        remove_position(args.code)
    elif args.command == "update":
        update_position(args.code, args.price, args.shares, args.note)
    elif args.command == "analyze":
        analyze_portfolio(args.output)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
