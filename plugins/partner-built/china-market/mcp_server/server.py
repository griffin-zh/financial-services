"""China A-share market data MCP server.

自包含 stdio MCP server: 直连 akshare / baostock / tushare 三源, 经 `SourceRouter`
做 health-aware 动态路由 + 稳定平面双写交叉, 经 `Cache` 抽象做历史 parquet 缓存 +
实时短 TTL 缓存。**不再依赖 Stock/ai_quant** (本机已无该目录)。

为什么存在: 官方 financial-services connectors (Daloopa/FactSet/Kensho) 不覆盖 A 股。
本 server 补这个缺口, 且核心 skill 软引用 MCP ("if a fundamentals provider is
available, use it"), 所以提供一个名为 china-market 的 server 即可, 无需 fork 官方 skill。

统一返回体 (每个 tool): {rows, count, columns, sources, confidence, degraded,
discrepancy, warnings, web_fallback} —— 让上层 skill 能感知数据源、双写一致性、
是否需要降级到白名单 web-fetch。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from loguru import logger
from mcp.server.fastmcp import FastMCP

# 把脚本自身目录加进 sys.path, 让 sibling import 在 `-m mcp_server.server`
# 和直接 `python server.py` 两种启动方式下都成立。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from cache import InMemoryTTLCache, LocalParquetCache  # noqa: E402
from sources import build_router  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

logger.remove()
logger.add(sys.stderr, level="INFO")

_config_path = PLUGIN_ROOT / "mcp_server" / "config.yaml"
with _config_path.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f) or {}

_storage = _config.setdefault("storage", {})
_cache_dir = (PLUGIN_ROOT / _storage.get("path", "./data_cache/market")).resolve()
_realtime_ttl = float(_config.get("cache", {}).get("realtime_ttl", 5.0))

_router = build_router(_config)
_bars_cache = LocalParquetCache(_cache_dir)           # 历史日线, 不变数据
_realtime_cache = InMemoryTTLCache(default_ttl=_realtime_ttl)  # 实时快照, 短 TTL

logger.info(f"china-market MCP ready. cache_dir={_cache_dir} realtime_ttl={_realtime_ttl}s")

mcp = FastMCP("china-market")


# --------------------------------------------------------------------------- #
# 公共 helper                                                                  #
# --------------------------------------------------------------------------- #
def _df_to_records(df: pd.DataFrame | None, max_rows: int = 500) -> list[dict[str, Any]]:
    """统一把 DataFrame 转成 JSON-safe records, 限制行数避免响应过大。"""
    if df is None or df.empty:
        return []
    if len(df) > max_rows:
        df = df.head(max_rows)
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].astype(str)
        elif out[col].dtype == "object":
            # akshare 常返回 datetime.date 对象 (非 datetime64), JSON 无法直接序列化
            out[col] = out[col].map(lambda v: v.isoformat() if hasattr(v, "isoformat") else v)
    return out.where(pd.notna(out), None).to_dict(orient="records")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _pack_dual(result: dict[str, Any], max_rows: int = 2000) -> dict[str, Any]:
    """把 router 的双写结果打成统一返回体。"""
    df = result.get("df")
    return {
        "rows": _df_to_records(df, max_rows=max_rows),
        "count": int(len(df)) if df is not None else 0,
        "columns": list(df.columns) if df is not None and not df.empty else [],
        "sources": result.get("sources", []),
        "confidence": result.get("confidence"),
        "degraded": result.get("degraded", False),
        "discrepancy": result.get("discrepancy"),
        "warnings": result.get("warnings", []),
        "web_fallback": result.get("web_fallback", False),
    }


def _pack_single(result: dict[str, Any], max_rows: int = 500, **extra) -> dict[str, Any]:
    """把 router 的有序 fallback 结果打成统一返回体。"""
    df = result.get("df")
    packed = {
        "rows": _df_to_records(df, max_rows=max_rows),
        "count": int(len(df)) if df is not None else 0,
        "columns": list(df.columns) if df is not None and not df.empty else [],
        "source": result.get("source"),
        "sources": result.get("sources", []),
        "degraded": result.get("degraded", False),
        "warnings": result.get("warnings", []),
        "web_fallback": result.get("web_fallback", False),
    }
    packed.update(extra)
    return packed


# --------------------------------------------------------------------------- #
# 稳定平面 tools (双写交叉)                                                     #
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_daily_bars(
    symbols: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """获取 A 股日线行情 (OHLCV, 不复权), baostock+akshare 双写交叉校验。

    Args:
        symbols: 股票代码列表, 后缀 .SH/.SZ. 例: ["600519.SH", "000858.SZ"].
        start_date: YYYY-MM-DD, 默认 365 天前.
        end_date: YYYY-MM-DD, 默认今天.

    Returns:
        统一返回体, 含 sources / confidence (high|low|single) / discrepancy /
        web_fallback. confidence=low 表示两源 pct_chg 对不上 (见 discrepancy)。
        上游全挂时若有本地缓存, 会返回 stale 数据并在 warnings 标注。
    """
    start_date = start_date or _days_ago(365)
    end_date = end_date or _today()

    frames: list[pd.DataFrame] = []
    all_sources: set[str] = set()
    confidences: list[str] = []
    discrepancies: list[Any] = []
    warnings: list[str] = []
    any_web_fallback = False

    for symbol in symbols:
        result = _router.get_daily(symbol, start_date, end_date)
        df = result.get("df")
        if df is not None and not df.empty:
            _bars_cache.set(symbol, df)  # 刷新缓存 (供上游全挂时兜底)
            frames.append(df)
            all_sources.update(result.get("sources", []))
            confidences.append(result.get("confidence", "single"))
            if result.get("discrepancy"):
                discrepancies.append({"symbol": symbol, **result["discrepancy"]})
            warnings.extend(f"[{symbol}] {w}" for w in result.get("warnings", []))
        else:
            # 上游全挂 → 尝试本地 stale 缓存
            cached = _bars_cache.get(symbol)
            if cached is not None and not cached.empty:
                mask = (cached["date"].astype(str) >= start_date) & (
                    cached["date"].astype(str) <= end_date
                )
                frames.append(cached[mask])
                all_sources.add("local_cache")
                confidences.append("stale")
                warnings.append(f"[{symbol}] 上游全挂, 返回本地 stale 缓存, 请谨慎使用")
            else:
                any_web_fallback = True
                warnings.extend(f"[{symbol}] {w}" for w in result.get("warnings", []))

    merged = pd.concat(frames, ignore_index=True) if frames else None
    # confidence 取最差: stale < low < single < high
    rank = {"stale": 0, "low": 1, "single": 2, "high": 3}
    worst = min(confidences, key=lambda c: rank.get(c, 2)) if confidences else "none"
    return _pack_dual({
        "df": merged,
        "sources": sorted(all_sources),
        "confidence": worst,
        "degraded": worst in ("stale", "low", "single"),
        "discrepancy": discrepancies or None,
        "warnings": warnings,
        "web_fallback": any_web_fallback and merged is None,
    })


@mcp.tool()
def get_stock_list(market: str = "all") -> dict[str, Any]:
    """获取 A 股股票列表 (含名称/行业, 用于 peer universe / 选股), 双写交叉。

    Args:
        market: "all" 全 A | "sh" 仅沪市 | "sz" 仅深市.
    """
    return _pack_dual(_router.get_stock_list(market), max_rows=6000)


# --------------------------------------------------------------------------- #
# 实时平面 tool (短 TTL 缓存 + 有序 fallback)                                   #
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_realtime_quote(symbols: list[str]) -> dict[str, Any]:
    """获取 A 股实时行情快照 (含名称/现价/涨跌幅). 短 TTL 缓存, TTL 内不重复打上游.

    Args:
        symbols: 股票代码列表, 后缀 .SH/.SZ.

    Returns:
        统一返回体。web_fallback=True 时上层应按白名单 (东财/新浪实时页) web-fetch。
    """
    key = "rt:" + ",".join(sorted(symbols))
    cached = _realtime_cache.get(key)
    if cached is not None:
        return {**cached, "cache_hit": True}
    packed = _pack_single(_router.get_realtime(symbols), cache_hit=False)
    if packed["count"] > 0:
        _realtime_cache.set(key, packed)
    return packed


# --------------------------------------------------------------------------- #
# 特色 / 单源 fallback tools                                                    #
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_financial_report(
    symbol: str,
    report: str = "income",
    period: str = "annual",
) -> dict[str, Any]:
    """获取个股财务报表 (年报/季报). akshare(新浪)主, tushare 备.

    Args:
        symbol: 股票代码, 后缀 .SH/.SZ. 例: "600519.SH".
        report: "income" 利润表 | "balance" 资产负债表 | "cashflow" 现金流量表.
        period: "annual" 年报 | "quarterly" 季报.
    """
    if report not in {"income", "balance", "cashflow"}:
        return {"error": f"unknown report '{report}', valid: income/balance/cashflow"}
    return _pack_single(
        _router.get_financial(symbol, report, period),
        max_rows=20, symbol=symbol, report=report, period=period,
    )


@mcp.tool()
def get_north_flow() -> dict[str, Any]:
    """获取北向资金 (沪股通 + 深股通) 净流入. 反映外资态度. akshare 主, tushare 备."""
    return _pack_single(_router.get_north_flow(), max_rows=200)


@mcp.tool()
def get_dragon_tiger(date: str | None = None) -> dict[str, Any]:
    """获取龙虎榜 (单日异动席位). akshare 主, tushare 备.

    Args:
        date: YYYY-MM-DD, 默认最近一个交易日.
    """
    date = date or _days_ago(1)
    return _pack_single(_router.get_dragon_tiger(date), max_rows=200, date=date)


@mcp.tool()
def get_stock_notices(symbol: str, limit: int = 20) -> dict[str, Any]:
    """获取个股公告 (年报/中报/季报/重大事项). akshare best-effort.

    Args:
        symbol: 股票代码, 后缀 .SH/.SZ. 例: "600519.SH".
        limit: 公告条数上限.

    web_fallback=True 时上层应按白名单 (巨潮 cninfo.com.cn) web-fetch 原始公告。
    """
    return _pack_single(_router.get_notices(symbol, limit), max_rows=limit, symbol=symbol)


@mcp.tool()
def get_stock_news(limit: int = 30) -> dict[str, Any]:
    """获取全市场最新财经新闻. akshare best-effort.

    Args:
        limit: 新闻条数上限, 默认 30.
    """
    return _pack_single(_router.get_news(limit), max_rows=limit)


# --------------------------------------------------------------------------- #
# 无外部依赖的常量 tool + 健康度                                                #
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_market_context() -> dict[str, Any]:
    """返回 A 股估值常用的市场常量 (DCF / comps 输入).

    无外部数据调用。上层 skill 生成报告时必须标注 "as of <date>, please verify"。
    """
    return {
        "currency": "CNY",
        "risk_free_rate": {
            "default": 0.027,
            "label": "中国 10Y 国债到期收益率 (baseline)",
            "source": "中央国债登记结算公司, 请在估值前用最新数据复核",
            "as_of": _today(),
        },
        "equity_risk_premium": {
            "default": 0.06,
            "range": [0.055, 0.065],
            "source": "Damodaran China ERP (年度更新)",
        },
        "tax_rate": {"default": 0.25, "label": "中国法定企业所得税率"},
        "accounting_standard": "CAS (中国会计准则)",
        "filing_sources": {
            "primary": "巨潮资讯网 (cninfo.com.cn)",
            "notes": "年报 / 半年报 / 季报, 替代 SEC 10-K/10-Q",
        },
        "industry_classification": "申万行业分类 (Shenwan SWS), 替代 GICS",
        "preferred_multiples": ["PE", "PB", "PEG"],
        "avoid_multiples": ["EV/EBITDA (银行/地产权重大, A 股不主流)"],
    }


@mcp.tool()
def get_source_health() -> dict[str, Any]:
    """返回各数据源的健康度 (circuit breaker 状态/成功率/延迟). 用于诊断与自净化复盘."""
    return {"sources": _router.health_report()}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
