"""China A-share market data MCP server.

自包含 MCP server: 直连 akshare / baostock / tushare 三源, 经 `SourceRouter`
做 health-aware 动态路由 + 稳定平面双写交叉, 经 `Cache` 抽象做历史 parquet 缓存 +
实时短 TTL 缓存。**不再依赖 Stock/ai_quant** (本机已无该目录)。

传输 env 驱动: `MCP_TRANSPORT` 默认 stdio (本地插件 / 调试); 预构建镜像里设为 sse,
监听 `MCP_HOST`/`MCP_PORT`, 供 oh-my-pi 与远程 Claude Code 同连一个实例。配置/缓存
路径可用 `CHINA_MARKET_CONFIG` / `CHINA_MARKET_CACHE_DIR` 覆盖, `TUSHARE_TOKEN` 注入 token。

为什么存在: 官方 financial-services connectors (Daloopa/FactSet/Kensho) 不覆盖 A 股。
本 server 补这个缺口, 且核心 skill 软引用 MCP ("if a fundamentals provider is
available, use it"), 所以提供一个名为 china-market 的 server 即可, 无需 fork 官方 skill。

统一返回体 (每个 tool): {rows, count, columns, sources, confidence, degraded,
discrepancy, warnings, web_fallback} —— 让上层 skill 能感知数据源、双写一致性、
是否需要降级到白名单 web-fetch。
"""

from __future__ import annotations

import os
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

_config_path = Path(
    os.getenv("CHINA_MARKET_CONFIG", str(PLUGIN_ROOT / "mcp_server" / "config.yaml"))
)
with _config_path.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f) or {}

# 允许用 env 覆盖 tushare token (容器 / CI 注入; 留空则 router 自动跳过 tushare)。
_ts_token = os.getenv("TUSHARE_TOKEN", "").strip()
if _ts_token:
    _config.setdefault("sources", {})["tushare"] = {"enabled": True, "token": _ts_token}

_storage = _config.setdefault("storage", {})
# 缓存目录: 默认相对 plugin root; 容器 / 远程部署用 CHINA_MARKET_CACHE_DIR 覆盖到挂载卷。
_cache_env = os.getenv("CHINA_MARKET_CACHE_DIR", "").strip()
if _cache_env:
    _cache_dir = Path(_cache_env).resolve()
else:
    _cache_dir = (PLUGIN_ROOT / _storage.get("path", "./data_cache/market")).resolve()
_realtime_ttl = float(_config.get("cache", {}).get("realtime_ttl", 5.0))

_router = build_router(_config)
_bars_cache = LocalParquetCache(_cache_dir)           # 历史日线, 不变数据
_realtime_cache = InMemoryTTLCache(default_ttl=_realtime_ttl)  # 实时快照, 短 TTL

logger.info(f"china-market MCP ready. cache_dir={_cache_dir} realtime_ttl={_realtime_ttl}s")

# transport: 默认 stdio (本地插件 / 调试); 容器镜像里由 MCP_TRANSPORT=sse 覆盖并监听 host/port。
# 同一份代码既供 Claude Code(stdio 或远程连预发布镜像)也供 oh-my-pi(SSE)消费。
_transport = os.getenv("MCP_TRANSPORT", "stdio")
if _transport == "stdio":
    mcp = FastMCP("china-market")
else:
    mcp = FastMCP(
        "china-market",
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8080")),
    )


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
# 监管 / 披露 / 投资者互动 tools (中文深度调研专用, 有序 fallback)              #
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_disclosure_search(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    market: str = "沪深京",
    keyword: str | None = None,
) -> dict[str, Any]:
    """检索个股的巨潮信息披露公告 (监管/披露信息结构化直连主力).

    问询函回复、行政处罚、监管措施、立案等以临时/定期公告形式落在巨潮, 可按代码 +
    日期窗口拉, 再用 keyword 按公告标题过滤逼近「监管事项」。这是「监管信息结构化直连」
    的首选, 不必先走 WebSearch。

    Args:
        symbol: 股票代码, 6 位或后缀 .SH/.SZ. 例: "600519.SH".
        start_date: YYYY-MM-DD, 默认 365 天前.
        end_date: YYYY-MM-DD, 默认今天.
        market: 巨潮市场域, 默认 "沪深京" (可选 "沪深"/"沪市"/"深市"/"北交所").
        keyword: 公告标题过滤正则. 监管近似检索传 "问询函|关注函|处罚|立案|监管|警示函".

    Returns:
        统一返回体, 归一列含 title/type/date/url/source. web_fallback=True 时上层
        应按白名单 (巨潮 cninfo.com.cn / 交易所官网 sse/szse) web-fetch 原始公告。
        注意: CSRC 处罚 / 交易所问询函无专用结构化接口, 此为标题关键词近似, 非官方全量。
    """
    start_date = start_date or _days_ago(365)
    end_date = end_date or _today()
    return _pack_single(
        _router.get_disclosure(symbol, start_date, end_date, market, keyword),
        max_rows=200, symbol=symbol, keyword=keyword,
    )


@mcp.tool()
def get_interactive_qa(symbol: str, limit: int = 20) -> dict[str, Any]:
    """获取投资者互动问答 (深证互动易 / 上证 e 互动). akshare best-effort.

    业绩说明会外的一手 Q&A: 沪市走上证 e 互动 (问答一表), 深市/北交所走深证互动易。
    对监管关注、经营异动、市场传闻的公司回应有一手价值。

    Args:
        symbol: 股票代码, 6 位或后缀 .SH/.SZ. 例: "300750.SZ".
        limit: 问答条数上限, 默认 20.

    Returns:
        统一返回体, 归一列含 question/answer/asker/ask_time/answer_time/source。
        web_fallback=True 时上层可按白名单交易所互动平台页 web-fetch。
    """
    return _pack_single(_router.get_interactive(symbol, limit), max_rows=limit, symbol=symbol)


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
    logger.info(f"Starting china-market MCP server (transport={_transport})")
    mcp.run(transport=_transport)


if __name__ == "__main__":
    main()
