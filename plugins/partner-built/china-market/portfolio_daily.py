"""
每日持仓检查 + 风险预警工具.

输入: d:/work/study/financial-services/投资建议/我的投资现状 (GBK 编码,持仓清单)
输出:
  - 控制台:精炼快照 + 触发的预警
  - d:/work/study/financial-services/投资建议/日报/<YYYY-MM-DD>.md:完整 daily snapshot
  - d:/work/study/financial-services/投资建议/日报/snapshots.parquet:历史所有快照(用于月报和趋势)
  - d:/work/study/financial-services/投资建议/日报/<YYYY-MM>/月报.md:月度 roll-up(每月初自动生成上个月)

风险规则(6 条,默认阈值):
  R1 单股单日波动 ≥ ±5%       → 当日剧烈波动
  R2 单股集中度 > 20%          → 单标过重
  R3 单股累计盈亏 < −10%       → 跌过止损线
  R4 单股累计盈亏 > +20%       → 超止盈线
  R5 行业集中度 > 40%          → 行业过度集中
  R6 港股暴露 > 50%            → 货币 / 单一市场风险

用法:
  python portfolio_daily.py            # 当日检查
  python portfolio_daily.py --month    # 强制生成上月月报
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd
from loguru import logger

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PORTFOLIO_FILE = Path("d:/work/study/financial-services/投资建议/我的投资现状")
REPORT_DIR = Path("d:/work/study/financial-services/投资建议/日报")
SNAPSHOTS_FILE = REPORT_DIR / "snapshots.parquet"

# 持仓名称 → 代码 + 市场 + 行业的人工 mapping
SYMBOL_MAP = {
    "新标准券":      {"code": "CASH_GC",  "market": "现金等价", "industry": "现金"},
    "赤峰黄金":      {"code": "600988",   "market": "A股",      "industry": "黄金 / 有色"},
    "恒瑞医药(A股)": {"code": "600276",   "market": "A股",      "industry": "创新药"},
    "汇丰控股":      {"code": "00005",    "market": "港股",     "industry": "银行 / 综合金融"},
    "恒生科技ETF":   {"code": "03088",    "market": "港股 ETF", "industry": "港股科技"},
    "恒瑞医药(港股)":{"code": "01276",    "market": "港股",     "industry": "创新药"},
}

RISK = {
    "single_day_pct": 0.05,    # R1 单日波动
    "concentration_max": 0.20, # R2 单股集中度
    "stop_loss": -0.10,        # R3 止损
    "take_profit": 0.20,       # R4 止盈
    "sector_max": 0.40,        # R5 行业集中度
    "hk_max": 0.50,            # R6 港股暴露
}

logger.remove()
logger.add(sys.stderr, level="INFO", format="<level>{message}</level>")

# ---------------------------------------------------------------------------
# Parse 持仓
# ---------------------------------------------------------------------------

def _norm_name(name: str) -> str:
    # 全角括号 → 半角(以匹配 SYMBOL_MAP 里的 key)
    return re.sub(r"\s+", "", name).replace("（", "(").replace("）", ")")


def parse_portfolio() -> pd.DataFrame:
    """读 GBK 编码的持仓文件, 返回标准化 DataFrame.

    Columns: name, code, market, industry, currency, qty, cost, prev_price, prev_value
    (prev_price 来自文件里的"现价", prev_value = 文件里的市值, 用于和最新拉到的实时价对比)
    """
    text = PORTFOLIO_FILE.read_text(encoding="gb18030")
    rows = []
    current_currency = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("一、人民币") or "人民币仓位" in line:
            current_currency = "CNY"
            continue
        if line.startswith("二、港元") or "港元仓位" in line or "港币仓位" in line:
            current_currency = "HKD"
            continue
        if line.startswith("证券名称"):
            continue
        parts = re.split(r"\s+|\t+", line)
        if len(parts) < 6:
            continue
        try:
            name = _norm_name(parts[0])
            qty_str = parts[1].replace("手", "").replace("股", "").replace("份", "")
            qty = float(qty_str.replace(",", ""))
            price = float(parts[2].replace(",", ""))
            cost = float(parts[3].replace(",", ""))
            value = float(parts[4].replace(",", "").replace("+", ""))
        except (ValueError, IndexError):
            continue
        info = SYMBOL_MAP.get(name)
        if info is None:
            logger.warning(f"未识别的标的:{name},跳过")
            continue
        rows.append({
            "name": name, "code": info["code"], "market": info["market"],
            "industry": info["industry"], "currency": current_currency,
            "qty": qty, "cost": cost, "prev_price": price, "prev_value": value,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Fetch latest prices
# ---------------------------------------------------------------------------

def _fetch_a_share_close(code: str) -> float | None:
    today = datetime.now()
    start = (today - timedelta(days=10)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                start_date=start, end_date=end, adjust="qfq")
        if df is not None and not df.empty:
            return float(df.iloc[-1]["收盘"])
    except Exception as e:
        logger.warning(f"A 股 {code} 拉价失败: {e}")
    return None


def _fetch_hk_close(code: str) -> float | None:
    today = datetime.now()
    start = (today - timedelta(days=15)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    try:
        df = ak.stock_hk_hist(symbol=code, period="daily",
                              start_date=start, end_date=end, adjust="qfq")
        if df is not None and not df.empty:
            return float(df.iloc[-1]["收盘"])
    except Exception as e:
        logger.warning(f"港股 {code} 拉价失败: {e}")
    return None


def _fetch_fx() -> float:
    """HKD → CNY 汇率. 失败回退 0.92"""
    try:
        df = ak.currency_boc_sina(symbol="港币")
        if df is not None and not df.empty:
            # 现钞买入价口径, /100 换算 (中行牌价是 1HKD = X CNY * 100)
            v = float(df.iloc[0]["中行折算价"])
            return v / 100 if v > 10 else v
    except Exception:
        pass
    return 0.92


def fetch_prices(portfolio: pd.DataFrame) -> pd.DataFrame:
    """对 portfolio 拉最新价,补 last_price / last_value / day_pct 三列.

    如网络故障拉不到,fallback 到 prev_price,并标记 stale=True 让 render 提醒.
    """
    last_prices: list[float] = []
    stale_flags: list[bool] = []
    for _, r in portfolio.iterrows():
        if r["market"] == "现金等价":
            last_prices.append(r["prev_price"])
            stale_flags.append(False)
            continue
        code = r["code"]
        if r["market"] == "A股":
            p = _fetch_a_share_close(code)
        else:
            p = _fetch_hk_close(code)
        if p is None:
            last_prices.append(r["prev_price"])
            stale_flags.append(True)
        else:
            last_prices.append(p)
            stale_flags.append(False)
    portfolio = portfolio.copy()
    portfolio["last_price"] = last_prices
    portfolio["stale"] = stale_flags
    portfolio["last_value"] = portfolio["qty"] * portfolio["last_price"]
    portfolio["day_pct"] = (portfolio["last_price"] / portfolio["prev_price"] - 1).fillna(0)
    portfolio["pnl_value"] = (portfolio["last_price"] - portfolio["cost"]) * portfolio["qty"]
    portfolio["pnl_pct"] = (portfolio["last_price"] / portfolio["cost"] - 1).fillna(0)
    return portfolio


# ---------------------------------------------------------------------------
# Risk checks
# ---------------------------------------------------------------------------

def run_risk_checks(p: pd.DataFrame, fx_rate: float) -> list[dict]:
    """跑 6 条风险规则,返回 list of {rule, severity, msg}"""
    alerts: list[dict] = []

    # 用 CNY 统一度量
    p = p.copy()
    p["value_cny"] = p.apply(
        lambda r: r["last_value"] * fx_rate if r["currency"] == "HKD" else r["last_value"],
        axis=1,
    )
    total = p["value_cny"].sum()

    # R1 单日波动
    for _, r in p.iterrows():
        if abs(r["day_pct"]) >= RISK["single_day_pct"]:
            sev = "严重" if abs(r["day_pct"]) >= 0.08 else "中度"
            alerts.append({"rule": "R1 单日波动", "severity": sev,
                           "name": r["name"],
                           "msg": f"{r['name']} 单日 {r['day_pct']*100:+.2f}% (阈值 ±{RISK['single_day_pct']*100:.0f}%)"})

    # R2 单股集中度 (排除现金等价)
    non_cash = p[p["market"] != "现金等价"]
    for _, r in non_cash.iterrows():
        share = r["value_cny"] / total
        if share > RISK["concentration_max"]:
            sev = "严重" if share > 0.35 else "中度"
            alerts.append({"rule": "R2 单股集中度", "severity": sev,
                           "name": r["name"],
                           "msg": f"{r['name']} 占总仓 {share*100:.1f}% (阈值 {RISK['concentration_max']*100:.0f}%)"})

    # R3 止损 / R4 止盈
    for _, r in p.iterrows():
        if r["market"] == "现金等价":
            continue
        if r["pnl_pct"] <= RISK["stop_loss"]:
            alerts.append({"rule": "R3 止损线", "severity": "中度",
                           "name": r["name"],
                           "msg": f"{r['name']} 盈亏 {r['pnl_pct']*100:+.2f}% (止损阈值 {RISK['stop_loss']*100:.0f}%)"})
        elif r["pnl_pct"] >= RISK["take_profit"]:
            alerts.append({"rule": "R4 止盈线", "severity": "提示",
                           "name": r["name"],
                           "msg": f"{r['name']} 盈亏 {r['pnl_pct']*100:+.2f}% (止盈阈值 {RISK['take_profit']*100:.0f}%)"})

    # R5 行业集中度
    industry_share = (non_cash.groupby("industry")["value_cny"].sum() / total).sort_values(ascending=False)
    for ind, share in industry_share.items():
        if share > RISK["sector_max"]:
            sev = "严重" if share > 0.50 else "中度"
            alerts.append({"rule": "R5 行业集中度", "severity": sev,
                           "name": ind,
                           "msg": f"行业「{ind}」占总仓 {share*100:.1f}% (阈值 {RISK['sector_max']*100:.0f}%)"})

    # R6 港股暴露
    hk_share = p[p["currency"] == "HKD"]["value_cny"].sum() / total
    if hk_share > RISK["hk_max"]:
        sev = "中度" if hk_share < 0.65 else "严重"
        alerts.append({"rule": "R6 港股暴露", "severity": sev,
                       "name": "港股",
                       "msg": f"港股占总仓 {hk_share*100:.1f}% (阈值 {RISK['hk_max']*100:.0f}%)"})

    return alerts


# ---------------------------------------------------------------------------
# Render daily markdown
# ---------------------------------------------------------------------------

def render_daily(p: pd.DataFrame, alerts: list[dict], fx_rate: float, snap_date: date) -> str:
    p = p.copy()
    p["value_cny"] = p.apply(
        lambda r: r["last_value"] * fx_rate if r["currency"] == "HKD" else r["last_value"],
        axis=1,
    )
    total_cny = p["value_cny"].sum()
    p["weight"] = p["value_cny"] / total_cny

    cny_total = p[p["currency"] == "CNY"]["last_value"].sum()
    hkd_total = p[p["currency"] == "HKD"]["last_value"].sum()
    cash_share = p[p["market"] == "现金等价"]["value_cny"].sum() / total_cny

    lines = []
    lines.append(f"# 持仓日报 — {snap_date}\n")
    lines.append(f"**总资产(CNY 折算):¥{total_cny/10000:.2f} 万**(HKD/CNY = {fx_rate:.4f})\n")
    lines.append(f"- 人民币仓位:¥{cny_total/10000:.2f} 万")
    lines.append(f"- 港币仓位:HKD {hkd_total/10000:.2f} 万 → ¥{hkd_total*fx_rate/10000:.2f} 万")
    lines.append(f"- 现金等价占比:**{cash_share*100:.1f}%**\n")

    stale_count = int(p.get("stale", pd.Series([False]*len(p))).sum())
    if stale_count > 0:
        lines.append(f"> ⚠ **{stale_count} 笔标的实时价拉取失败**(网络故障),使用持仓文件中的现价占位。单日波动 = 0% 仅说明无新数据,不代表真实波动。\n")

    # 风险预警 (突出)
    if alerts:
        lines.append(f"## ⚠ 风险预警 — 触发 {len(alerts)} 条\n")
        by_sev = {"严重": [], "中度": [], "提示": []}
        for a in alerts:
            by_sev.setdefault(a["severity"], []).append(a)
        for sev in ["严重", "中度", "提示"]:
            if not by_sev[sev]:
                continue
            lines.append(f"### {sev}")
            for a in by_sev[sev]:
                lines.append(f"- **[{a['rule']}]** {a['msg']}")
            lines.append("")
    else:
        lines.append("## ✓ 无风险预警触发\n")

    # 持仓明细
    lines.append("## 持仓明细\n")
    lines.append("| 标的 | 代码 | 市场 | 数量 | 现价 | 成本 | 市值(原币) | 累计盈亏 | 单日 | 仓位% |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in p.iterrows():
        ccy = "¥" if r["currency"] == "CNY" else "HK$"
        pnl_str = f"{r['pnl_pct']*100:+.2f}%" if r["market"] != "现金等价" else "—"
        day_str = f"{r['day_pct']*100:+.2f}%" if r["market"] != "现金等价" else "—"
        lines.append(
            f"| {r['name']} | {r['code']} | {r['market']} | {r['qty']:.0f} | "
            f"{ccy}{r['last_price']:.2f} | {ccy}{r['cost']:.2f} | "
            f"{ccy}{r['last_value']:,.0f} | {pnl_str} | {day_str} | {r['weight']*100:.1f}% |"
        )

    # 行业 / 市场分布
    lines.append("\n## 行业分布(占总仓 %)\n")
    ind = p.groupby("industry")["value_cny"].sum().sort_values(ascending=False) / total_cny
    lines.append("| 行业 | 占比 |")
    lines.append("|---|---:|")
    for k, v in ind.items():
        lines.append(f"| {k} | {v*100:.1f}% |")

    lines.append("\n## 市场分布\n")
    mkt = p.groupby("currency")["value_cny"].sum().sort_values(ascending=False) / total_cny
    lines.append("| 货币 | 占比 |")
    lines.append("|---|---:|")
    for k, v in mkt.items():
        lines.append(f"| {k} | {v*100:.1f}% |")

    lines.append(f"\n---\n_由 portfolio_daily.py 自动生成 at {datetime.now():%Y-%m-%d %H:%M}_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persist snapshot
# ---------------------------------------------------------------------------

def append_snapshot(p: pd.DataFrame, fx_rate: float, snap_date: date) -> None:
    p = p.copy()
    p["snap_date"] = snap_date
    p["fx_rate"] = fx_rate
    p["value_cny"] = p.apply(
        lambda r: r["last_value"] * fx_rate if r["currency"] == "HKD" else r["last_value"],
        axis=1,
    )
    keep = ["snap_date", "name", "code", "market", "industry", "currency",
            "qty", "cost", "prev_price", "last_price", "last_value", "value_cny",
            "day_pct", "pnl_pct", "fx_rate"]
    new = p[keep]
    if SNAPSHOTS_FILE.exists():
        old = pd.read_parquet(SNAPSHOTS_FILE)
        old = old[old["snap_date"] != snap_date]  # 同日重跑覆盖
        combined = pd.concat([old, new], ignore_index=True)
    else:
        combined = new
    SNAPSHOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(SNAPSHOTS_FILE, index=False)


# ---------------------------------------------------------------------------
# Monthly roll-up
# ---------------------------------------------------------------------------

def render_monthly(year_month: str) -> str | None:
    if not SNAPSHOTS_FILE.exists():
        return None
    df = pd.read_parquet(SNAPSHOTS_FILE)
    df["snap_date"] = pd.to_datetime(df["snap_date"])
    df["ym"] = df["snap_date"].dt.strftime("%Y-%m")
    sub = df[df["ym"] == year_month]
    if sub.empty:
        return None

    by_day = sub.groupby("snap_date")["value_cny"].sum().sort_index()
    start_v = by_day.iloc[0]
    end_v = by_day.iloc[-1]
    peak = by_day.max()
    trough = by_day.min()
    days = len(by_day)

    lines = [f"# 持仓月报 — {year_month}\n"]
    lines.append(f"**期初:¥{start_v/10000:.2f} 万 → 期末:¥{end_v/10000:.2f} 万**")
    lines.append(f"- 当月回报:{(end_v/start_v-1)*100:+.2f}%")
    lines.append(f"- 月内高点:¥{peak/10000:.2f} 万")
    lines.append(f"- 月内低点:¥{trough/10000:.2f} 万")
    lines.append(f"- 最大回撤:{(trough/peak-1)*100:.2f}%")
    lines.append(f"- 交易日数:{days}\n")

    # 各标的当月贡献
    lines.append("## 各标的当月表现\n")
    lines.append("| 标的 | 期初市值(¥万) | 期末市值(¥万) | 当月回报 |")
    lines.append("|---|---:|---:|---:|")
    for name, g in sub.groupby("name"):
        g = g.sort_values("snap_date")
        if len(g) < 2:
            continue
        s = g.iloc[0]["value_cny"]
        e = g.iloc[-1]["value_cny"]
        ret = (e / s - 1) * 100 if s > 0 else 0
        lines.append(f"| {name} | {s/10000:.2f} | {e/10000:.2f} | {ret:+.2f}% |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", action="store_true",
                    help="额外生成上个月的月报")
    ap.add_argument("--date", help="指定 snapshot 日期 (YYYY-MM-DD), 默认今天")
    args = ap.parse_args()

    snap_date = date.fromisoformat(args.date) if args.date else date.today()
    logger.info(f"=== 持仓日报 {snap_date} ===")

    if not PORTFOLIO_FILE.exists():
        logger.error(f"持仓文件不存在:{PORTFOLIO_FILE}")
        return 1

    portfolio = parse_portfolio()
    logger.info(f"读到 {len(portfolio)} 笔持仓")

    portfolio = fetch_prices(portfolio)
    fx_rate = _fetch_fx()
    logger.info(f"HKD/CNY = {fx_rate:.4f}")

    alerts = run_risk_checks(portfolio, fx_rate)
    if alerts:
        logger.warning(f"风险预警 {len(alerts)} 条:")
        for a in alerts:
            tag = {"严重": "[!!]", "中度": "[!]", "提示": "[i]"}.get(a["severity"], "[?]")
            logger.warning(f"  {tag} [{a['rule']}] {a['msg']}")
    else:
        logger.info("✓ 无风险预警触发")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md = render_daily(portfolio, alerts, fx_rate, snap_date)
    out_file = REPORT_DIR / f"{snap_date}.md"
    out_file.write_text(md, encoding="utf-8")
    logger.info(f"日报已写:{out_file}")

    append_snapshot(portfolio, fx_rate, snap_date)

    # 月报:每月 1 日自动生成上月,或 --month 显式触发
    if args.month or snap_date.day <= 3:
        last_month_end = snap_date.replace(day=1) - timedelta(days=1)
        ym = last_month_end.strftime("%Y-%m")
        md_month = render_monthly(ym)
        if md_month:
            month_dir = REPORT_DIR / ym
            month_dir.mkdir(parents=True, exist_ok=True)
            (month_dir / "月报.md").write_text(md_month, encoding="utf-8")
            logger.info(f"月报已写:{month_dir / '月报.md'}")
        else:
            logger.info(f"月报数据不足 ({ym}, snapshots 不存在或无数据)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
