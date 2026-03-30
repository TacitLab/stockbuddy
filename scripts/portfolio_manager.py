#!/usr/bin/env python3
"""
多市场股票持仓/关注池管理工具 - 基于 SQLite 管理关注股票、持仓并批量分析。

用法:
    python3 portfolio_manager.py list
    python3 portfolio_manager.py add <代码> --price <买入价> --shares <数量> [--date <日期>] [--note <备注>]
    python3 portfolio_manager.py remove <代码>
    python3 portfolio_manager.py update <代码> [--price <价格>] [--shares <数量>] [--note <备注>]
    python3 portfolio_manager.py analyze [--output <输出文件>]
    python3 portfolio_manager.py watch-list
    python3 portfolio_manager.py watch-add <代码>
    python3 portfolio_manager.py watch-remove <代码>

数据默认保存在: ~/.stockbuddy/stockbuddy.db
"""

import sys
import json
import argparse
import os
import time
from datetime import datetime

try:
    from db import (
        DB_PATH,
        get_watchlist_item,
        init_db,
        list_positions as db_list_positions,
        list_watchlist as db_list_watchlist,
        remove_position as db_remove_position,
        set_watch_status,
        update_position_fields,
        upsert_position,
        upsert_watchlist_item,
    )
    from analyze_stock import fetch_tencent_quote, normalize_stock_code, analyze_stock
except ImportError:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    from db import (
        DB_PATH,
        get_watchlist_item,
        init_db,
        list_positions as db_list_positions,
        list_watchlist as db_list_watchlist,
        remove_position as db_remove_position,
        set_watch_status,
        update_position_fields,
        upsert_position,
        upsert_watchlist_item,
    )
    from analyze_stock import fetch_tencent_quote, normalize_stock_code, analyze_stock


def normalize_code(code: str) -> str:
    return normalize_stock_code(code)["code"]


def ensure_watch_item(code: str, watched: bool = False) -> dict:
    stock = normalize_stock_code(code)
    quote = fetch_tencent_quote(stock["code"])
    name = quote.get("name") if quote else None
    return upsert_watchlist_item(
        code=stock["code"],
        market=stock["market"],
        tencent_symbol=stock["tencent_symbol"],
        name=name,
        exchange=quote.get("exchange", stock.get("exchange")) if quote else stock.get("exchange"),
        currency=quote.get("currency") if quote else None,
        last_price=quote.get("price") if quote else None,
        pe=quote.get("pe") if quote else None,
        pb=quote.get("pb") if quote else None,
        market_cap=quote.get("market_cap") if quote else None,
        week52_high=quote.get("52w_high") if quote else None,
        week52_low=quote.get("52w_low") if quote else None,
        quote_time=quote.get("timestamp") if quote else None,
        is_watched=watched,
        meta=quote or stock,
    )


# ─────────────────────────────────────────────
#  持仓管理
# ─────────────────────────────────────────────

def list_positions():
    init_db()
    positions = db_list_positions()
    if not positions:
        print(json.dumps({"message": "持仓为空", "positions": []}, ensure_ascii=False, indent=2))
        return
    print(json.dumps({
        "total_positions": len(positions),
        "positions": positions,
        "portfolio_db": str(DB_PATH),
        "updated_at": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2))


def add_position(code: str, price: float, shares: int, date: str = None, note: str = ""):
    init_db()
    normalized = normalize_stock_code(code)
    existing = next((p for p in db_list_positions() if p["code"] == normalized["code"]), None)
    if existing:
        print(json.dumps({"error": f"{normalized['code']} 已在持仓中，请使用 update 命令更新"}, ensure_ascii=False))
        return

    watch = ensure_watch_item(normalized["code"], watched=True)
    position = upsert_position(
        code=normalized["code"],
        market=normalized["market"],
        tencent_symbol=normalized["tencent_symbol"],
        buy_price=price,
        shares=shares,
        buy_date=date or datetime.now().strftime("%Y-%m-%d"),
        note=note,
        name=watch.get("name"),
        currency=watch.get("currency"),
        meta=json.loads(watch["meta_json"]) if watch.get("meta_json") else None,
    )
    print(json.dumps({"message": f"已添加 {normalized['code']}", "position": position}, ensure_ascii=False, indent=2))


def remove_position(code: str):
    init_db()
    normalized_code = normalize_code(code)
    removed = db_remove_position(normalized_code)
    if not removed:
        print(json.dumps({"error": f"{normalized_code} 不在持仓中"}, ensure_ascii=False))
        return
    print(json.dumps({"message": f"已移除 {normalized_code}"}, ensure_ascii=False, indent=2))


def update_position(code: str, price: float = None, shares: int = None, note: str = None):
    init_db()
    normalized_code = normalize_code(code)
    position = update_position_fields(normalized_code, price=price, shares=shares, note=note)
    if not position:
        print(json.dumps({"error": f"{normalized_code} 不在持仓中"}, ensure_ascii=False))
        return
    print(json.dumps({"message": f"已更新 {normalized_code}", "position": position}, ensure_ascii=False, indent=2))


# ─────────────────────────────────────────────
#  关注池管理
# ─────────────────────────────────────────────

def list_watchlist():
    init_db()
    items = db_list_watchlist(only_watched=True)
    print(json.dumps({
        "total_watchlist": len(items),
        "watchlist": items,
        "portfolio_db": str(DB_PATH),
        "updated_at": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2))


def add_watch(code: str):
    init_db()
    watch = ensure_watch_item(code, watched=True)
    print(json.dumps({"message": f"已关注 {watch['code']}", "watch": watch}, ensure_ascii=False, indent=2))


def remove_watch(code: str):
    init_db()
    normalized_code = normalize_code(code)
    watch = set_watch_status(normalized_code, False)
    if not watch:
        print(json.dumps({"error": f"{normalized_code} 不在关注池中"}, ensure_ascii=False))
        return
    print(json.dumps({"message": f"已取消关注 {normalized_code}", "watch": watch}, ensure_ascii=False, indent=2))


# ─────────────────────────────────────────────
#  批量分析
# ─────────────────────────────────────────────

def analyze_portfolio(output_file: str = None):
    init_db()
    positions = db_list_positions()
    if not positions:
        print(json.dumps({"message": "持仓为空，无法分析"}, ensure_ascii=False, indent=2))
        return

    results = []
    for i, pos in enumerate(positions):
        code = pos["code"]
        print(f"正在分析 {code} ({i+1}/{len(positions)})...", file=sys.stderr)
        analysis = analyze_stock(code)

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
                "currency": pos.get("currency"),
                "market": pos.get("market"),
            }

        results.append(analysis)

        if i < len(positions) - 1 and not analysis.get("_from_cache"):
            time.sleep(2)

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
    parser = argparse.ArgumentParser(description="多市场股票持仓/关注池管理工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    subparsers.add_parser("list", help="列出所有持仓")

    add_parser = subparsers.add_parser("add", help="添加持仓")
    add_parser.add_argument("code", help="股票代码")
    add_parser.add_argument("--price", type=float, required=True, help="买入价格")
    add_parser.add_argument("--shares", type=int, required=True, help="持有数量")
    add_parser.add_argument("--date", help="买入日期 (YYYY-MM-DD)")
    add_parser.add_argument("--note", default="", help="备注")

    rm_parser = subparsers.add_parser("remove", help="移除持仓")
    rm_parser.add_argument("code", help="股票代码")

    up_parser = subparsers.add_parser("update", help="更新持仓")
    up_parser.add_argument("code", help="股票代码")
    up_parser.add_argument("--price", type=float, help="买入价格")
    up_parser.add_argument("--shares", type=int, help="持有数量")
    up_parser.add_argument("--note", help="备注")

    analyze_parser = subparsers.add_parser("analyze", help="批量分析持仓")
    analyze_parser.add_argument("--output", help="输出JSON文件")

    watch_list_parser = subparsers.add_parser("watch-list", help="列出关注池")
    watch_add_parser = subparsers.add_parser("watch-add", help="添加关注股票")
    watch_add_parser.add_argument("code", help="股票代码")
    watch_remove_parser = subparsers.add_parser("watch-remove", help="取消关注股票")
    watch_remove_parser.add_argument("code", help="股票代码")

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
    elif args.command == "watch-list":
        list_watchlist()
    elif args.command == "watch-add":
        add_watch(args.code)
    elif args.command == "watch-remove":
        remove_watch(args.code)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
