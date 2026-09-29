"""Data-source layer for the china-market MCP server.

设计目标 (对齐 plan「两平面 + 双写交叉 + 动态路由 + 架构预留」):

1. `DataSource` 抽象 + 三个自包含 adapter (akshare / baostock / tushare), 直连各自
   的 library, **不依赖 Stock/ai_quant** (本机 Stock/ 已不存在)。各 adapter 把输出
   归一化成统一列名 schema, 让上层与源解耦。
2. `SourceRouter` 做 health-aware 动态路由: 每源一个 circuit breaker + 成功率/延迟
   统计。稳定平面 (daily) 走双写交叉 —— 顺序拉 >=2 健康源, 比对口径无关字段 (pct_chg),
   一致=high / 分歧=low(附两源值) / 单源=single+degraded。实时/特色数据走有序 fallback。
3. 三源全挂 → 返回 `web_fallback=True` 的结构化 surface, 由上层 (skill) 显式授权
   走白名单 web-fetch, 而不是静默空。

stdout 纪律: MCP 用 stdout 传协议, 而 baostock/tushare 的 login/query 会往 stdout
打字 → 污染协议。所以 `_call` 里所有 source 调用都套 `_silence_stdout` 重定向到 stderr。
双写是**顺序**执行 (非并发), 因此 stdout 重定向无线程竞争。
"""

from __future__ import annotations

import contextlib
import sys
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

import pandas as pd
from loguru import logger

# 归一化后的日线列 schema (所有 adapter 的 fetch_daily 输出对齐这套)
DAILY_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "pct_chg"]

_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="src")


class SourceUnsupported(Exception):
    """该 source 不支持此数据类型 (capability)。"""


class SourceError(Exception):
    """该 source 拉取失败 (网络 / 限流 / 空返回 / 接口失效)。"""


# --------------------------------------------------------------------------- #
# symbol 转换                                                                  #
# --------------------------------------------------------------------------- #
def _code6(symbol: str) -> str:
    """600519.SH -> 600519"""
    return symbol.split(".")[0]


def _suffix_of(code6: str) -> str:
    """按首位推交易所后缀 (与 a-share-data skill 约定一致)。"""
    if code6.startswith(("5", "6", "9")) or code6.startswith("688"):
        return "SH"
    if code6.startswith("8") or code6.startswith("4"):
        return "BJ"
    return "SZ"


def _to_baostock(symbol: str) -> str:
    """600519.SH -> sh.600519"""
    code, suf = symbol.split(".")
    return f"{suf.lower()}.{code}"


def _from_baostock(bs_code: str) -> str:
    """sh.600519 -> 600519.SH"""
    market, code = bs_code.split(".")
    return f"{code}.{market.upper()}"


@contextlib.contextmanager
def _silence_stdout():
    """把 stdout 重定向到 stderr, 防止 baostock/tushare 的打印污染 MCP 协议。"""
    old = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = old


def _call_with_retry(
    fn: Callable[[], Any],
    *,
    retries: int = 2,
    backoff: float = 0.6,
    timeout: float = 15.0,
) -> Any:
    """带 retry + timeout 的调用。timeout 用线程包装 (akshare 无原生 timeout 参数)。

    注意: 超时后底层线程仍在跑 (无法强杀), 但 future.result 会抛 TimeoutError,
    对我们够用 —— 下一次 retry / 降级不受影响。
    """
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            fut = _EXECUTOR.submit(fn)
            return fut.result(timeout=timeout)
        except Exception as e:  # noqa: BLE001 — 统一收敛为 retry
            last_err = e
            if attempt < retries:
                time.sleep(backoff * (2**attempt))
    raise SourceError(str(last_err))


# --------------------------------------------------------------------------- #
# DataSource 抽象 + 三个 adapter                                               #
# --------------------------------------------------------------------------- #
class DataSource(ABC):
    name: str = "base"
    capabilities: set[str] = set()

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def fetch_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        raise SourceUnsupported(f"{self.name} 不支持 daily")

    def fetch_realtime(self, symbols: list[str]) -> pd.DataFrame:
        raise SourceUnsupported(f"{self.name} 不支持 realtime")

    def fetch_financial(self, symbol: str, report: str, period: str) -> pd.DataFrame:
        raise SourceUnsupported(f"{self.name} 不支持 financial")

    def fetch_stock_list(self, market: str) -> pd.DataFrame:
        raise SourceUnsupported(f"{self.name} 不支持 stock_list")

    def fetch_north_flow(self) -> pd.DataFrame:
        raise SourceUnsupported(f"{self.name} 不支持 north_flow")

    def fetch_dragon_tiger(self, date: str) -> pd.DataFrame:
        raise SourceUnsupported(f"{self.name} 不支持 dragon_tiger")

    def fetch_notices(self, symbol: str, limit: int) -> pd.DataFrame:
        raise SourceUnsupported(f"{self.name} 不支持 notices")

    def fetch_news(self, limit: int) -> pd.DataFrame:
        raise SourceUnsupported(f"{self.name} 不支持 news")

    def fetch_disclosure(
        self, symbol: str, start: str, end: str, market: str, keyword: Optional[str]
    ) -> pd.DataFrame:
        raise SourceUnsupported(f"{self.name} 不支持 disclosure")

    def fetch_interactive(self, symbol: str, limit: int) -> pd.DataFrame:
        raise SourceUnsupported(f"{self.name} 不支持 interactive")


class AkshareSource(DataSource):
    """akshare adapter (自包含, 直连 akshare 库)。覆盖最广, 作 tier-1 主源。"""

    name = "akshare"
    capabilities = {
        "daily", "realtime", "financial", "stock_list",
        "north_flow", "dragon_tiger", "notices", "news",
        "disclosure", "interactive",
    }

    def fetch_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        import akshare as ak

        df = ak.stock_zh_a_hist(
            symbol=_code6(symbol),
            period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="",  # 不复权, 保证 close 口径与 baostock adjustflag=3 一致
        )
        if df is None or df.empty:
            raise SourceError("akshare 日线返回空")
        rename = {
            "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
            "最低": "low", "成交量": "volume", "涨跌幅": "pct_chg",
        }
        df = df.rename(columns=rename)
        df["symbol"] = symbol
        df["date"] = df["date"].astype(str)
        return df[[c for c in DAILY_COLUMNS if c in df.columns]]

    def fetch_realtime(self, symbols: list[str]) -> pd.DataFrame:
        import akshare as ak

        spot = ak.stock_zh_a_spot_em()
        if spot is None or spot.empty:
            raise SourceError("akshare 实时快照返回空")
        want = {_code6(s) for s in symbols} if symbols else None
        if want is not None:
            spot = spot[spot["代码"].astype(str).isin(want)]
        out = pd.DataFrame({
            "code": spot["代码"].astype(str),
            "name": spot.get("名称"),
            "price": spot.get("最新价"),
            "pct_chg": spot.get("涨跌幅"),
        })
        out["symbol"] = out["code"].map(lambda c: f"{c}.{_suffix_of(c)}")
        return out

    def fetch_financial(self, symbol: str, report: str, period: str) -> pd.DataFrame:
        import akshare as ak

        report_map = {"income": "利润表", "balance": "资产负债表", "cashflow": "现金流量表"}
        df = ak.stock_financial_report_sina(stock=_code6(symbol), symbol=report_map[report])
        if df is None or df.empty:
            raise SourceError("akshare 财报返回空")
        if period == "annual" and "报告日" in df.columns:
            df = df[df["报告日"].astype(str).str.endswith("1231")]
        return df

    def fetch_stock_list(self, market: str) -> pd.DataFrame:
        import akshare as ak

        spot = ak.stock_zh_a_spot_em()
        if spot is None or spot.empty:
            raise SourceError("akshare 股票列表返回空")
        out = pd.DataFrame({
            "code": spot["代码"].astype(str),
            "name": spot.get("名称"),
        })
        out["symbol"] = out["code"].map(lambda c: f"{c}.{_suffix_of(c)}")
        if market == "sh":
            out = out[out["symbol"].str.endswith(".SH")]
        elif market == "sz":
            out = out[out["symbol"].str.endswith(".SZ")]
        return out

    def fetch_north_flow(self) -> pd.DataFrame:
        import akshare as ak

        # akshare 北向接口历史上多次改名, 尝试几个候选
        for fn_name in ("stock_hsgt_fund_flow_summary_em", "stock_hsgt_north_net_flow_in_em"):
            fn = getattr(ak, fn_name, None)
            if fn is None:
                continue
            try:
                df = fn()
                if df is not None and not df.empty:
                    return df
            except Exception:  # noqa: BLE001 — 换下一个候选
                continue
        raise SourceError("akshare 北向资金接口均失效")

    def fetch_dragon_tiger(self, date: str) -> pd.DataFrame:
        import akshare as ak

        d = date.replace("-", "")
        df = ak.stock_lhb_detail_em(start_date=d, end_date=d)
        if df is None or df.empty:
            raise SourceError("akshare 龙虎榜返回空")
        return df

    def fetch_notices(self, symbol: str, limit: int) -> pd.DataFrame:
        import akshare as ak

        # 个股公告 akshare 接口不稳定, best-effort; 失败让上层降级到 web 白名单 (巨潮)
        df = ak.stock_notice_report(symbol="全部")
        if df is None or df.empty:
            raise SourceError("akshare 公告返回空")
        return df.head(limit)

    def fetch_news(self, limit: int) -> pd.DataFrame:
        import akshare as ak

        df = ak.stock_info_global_em()
        if df is None or df.empty:
            raise SourceError("akshare 财经新闻返回空")
        return df.head(limit)

    def fetch_disclosure(
        self, symbol: str, start: str, end: str, market: str, keyword: Optional[str]
    ) -> pd.DataFrame:
        # 巨潮「信息披露公告-沪深京」结构化检索。监管/披露信息的结构化直连主力:
        # 问询函回复、处罚公告、监管措施都以临时/定期公告形式落在这里, 可按
        # symbol + 日期窗口拉, 再按标题本地过滤 keyword (兼容无 keyword 形参的版本)。
        import akshare as ak

        df = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=_code6(symbol),
            market=market,
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
        )
        if df is None or df.empty:
            raise SourceError("akshare 巨潮披露检索返回空")
        # 巨潮返回中文列 (代码/简称/公告标题/公告时间/公告链接), 归一化;
        # 版本间列名可能漂移 (旧版曾用 网址/公告类型), 只 rename 存在的列, 其余原样保留。
        rename = {
            "代码": "code", "简称": "name", "公告标题": "title",
            "公告类型": "type", "公告时间": "date",
            "公告链接": "url", "网址": "url",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        df["source"] = "cninfo"
        if keyword:
            # 标题列本地正则过滤 —— 传 keyword="问询函|处罚|立案|监管" 即得监管近似检索
            title_col = "title" if "title" in df.columns else df.columns[0]
            df = df[df[title_col].astype(str).str.contains(keyword, na=False, regex=True)]
            if df.empty:
                raise SourceError(f"披露检索无匹配 keyword={keyword}")
        return df

    def fetch_interactive(self, symbol: str, limit: int) -> pd.DataFrame:
        # 投资者互动问答: 沪市走上证 e 互动 (单表含问答), 深市/北交所走深证互动易。
        # best-effort; 接口较新 (akshare ≥1.10.73/74), 挂了让上层降级 web_fallback。
        import akshare as ak

        code = _code6(symbol)
        if _suffix_of(code) == "SH":
            df = ak.stock_sns_sseinfo(symbol=code)
            src = "sse_einteract"
        else:
            # 互动易: stock_irm_cninfo 返回提问 (含回答列 if 版本支持)
            df = ak.stock_irm_cninfo(symbol=code)
            src = "szse_irm"
        if df is None or df.empty:
            raise SourceError("akshare 投资者互动问答返回空")
        rename = {
            "股票代码": "code", "股票简称": "name", "公司简称": "name",
            "问题": "question", "回答": "answer", "回答内容": "answer",
            "提问者": "asker", "回答者": "answerer",
            "提问时间": "ask_time", "问题时间": "ask_time",
            "回答时间": "answer_time", "更新时间": "answer_time",
            "来源": "src_platform", "问题来源": "src_platform",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        df["source"] = src
        return df.head(limit)


class BaostockSource(DataSource):
    """baostock adapter (自包含)。来源交易所, A 股日线/列表最稳, 作双写交叉的第二源。

    无实时 / 无北向龙虎榜 / 无公告新闻。baostock 是全局 session, 需 login;
    login 打印被 `_silence_stdout` (在 router._call 里) 吸收。
    """

    name = "baostock"
    capabilities = {"daily", "stock_list"}
    _logged_in = False

    def _ensure_login(self) -> None:
        import baostock as bs

        if not BaostockSource._logged_in:
            rs = bs.login()
            if rs.error_code != "0":
                raise SourceError(f"baostock login 失败: {rs.error_msg}")
            BaostockSource._logged_in = True

    def fetch_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        import baostock as bs

        self._ensure_login()
        rs = bs.query_history_k_data_plus(
            _to_baostock(symbol),
            "date,open,high,low,close,volume,pctChg",
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag="3",  # 3 = 不复权
        )
        if rs.error_code != "0":
            BaostockSource._logged_in = False  # session 可能掉, 下次重登
            raise SourceError(f"baostock 日线失败: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            raise SourceError("baostock 日线返回空")
        df = pd.DataFrame(rows, columns=rs.fields)
        df = df.rename(columns={"pctChg": "pct_chg"})
        for col in ("open", "high", "low", "close", "volume", "pct_chg"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["symbol"] = symbol
        df["date"] = df["date"].astype(str)
        return df[[c for c in DAILY_COLUMNS if c in df.columns]]

    def fetch_stock_list(self, market: str) -> pd.DataFrame:
        import baostock as bs

        self._ensure_login()
        rs = bs.query_all_stock()
        if rs.error_code != "0":
            BaostockSource._logged_in = False
            raise SourceError(f"baostock 列表失败: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            raise SourceError("baostock 列表返回空")
        df = pd.DataFrame(rows, columns=rs.fields)
        df["symbol"] = df["code"].map(_from_baostock)
        df["name"] = df.get("code_name")
        df["code"] = df["symbol"].map(_code6)
        if market == "sh":
            df = df[df["symbol"].str.endswith(".SH")]
        elif market == "sz":
            df = df[df["symbol"].str.endswith(".SZ")]
        return df[["code", "name", "symbol"]]


class TushareSource(DataSource):
    """tushare Pro adapter (自包含)。规范历史 + 特色数据 (北向/龙虎榜), 作 tier-3 补 / 交叉。

    需 token (config.sources.tushare.token)。无实时 (上一轮已确认无增益)。
    """

    name = "tushare"
    capabilities = {"daily", "financial", "stock_list", "north_flow", "dragon_tiger"}

    def __init__(self, token: str) -> None:
        import tushare as ts

        self._pro = ts.pro_api(token)

    def fetch_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        df = self._pro.daily(
            ts_code=symbol, start_date=start.replace("-", ""), end_date=end.replace("-", "")
        )
        if df is None or df.empty:
            raise SourceError("tushare 日线返回空")
        df = df.rename(columns={"vol": "volume", "pct_chg": "pct_chg", "trade_date": "date"})
        df["symbol"] = symbol
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").astype(str)
        return df[[c for c in DAILY_COLUMNS if c in df.columns]].sort_values("date")

    def fetch_financial(self, symbol: str, report: str, period: str) -> pd.DataFrame:
        api = {"income": self._pro.income, "balance": self._pro.balancesheet,
               "cashflow": self._pro.cashflow}[report]
        df = api(ts_code=symbol)
        if df is None or df.empty:
            raise SourceError("tushare 财报返回空")
        if period == "annual" and "end_date" in df.columns:
            df = df[df["end_date"].astype(str).str.endswith("1231")]
        return df

    def fetch_stock_list(self, market: str) -> pd.DataFrame:
        exchange = {"sh": "SSE", "sz": "SZSE"}.get(market, "")
        df = self._pro.stock_basic(exchange=exchange, list_status="L",
                                   fields="ts_code,symbol,name,industry")
        if df is None or df.empty:
            raise SourceError("tushare 列表返回空")
        return df.rename(columns={"ts_code": "symbol", "symbol": "code"})

    def fetch_north_flow(self) -> pd.DataFrame:
        df = self._pro.moneyflow_hsgt()
        if df is None or df.empty:
            raise SourceError("tushare 北向返回空")
        return df

    def fetch_dragon_tiger(self, date: str) -> pd.DataFrame:
        df = self._pro.top_list(trade_date=date.replace("-", ""))
        if df is None or df.empty:
            raise SourceError("tushare 龙虎榜返回空")
        return df


# --------------------------------------------------------------------------- #
# health-aware SourceRouter                                                    #
# --------------------------------------------------------------------------- #
class HealthState:
    """单源健康状态 + circuit breaker (closed / open / half_open)。"""

    def __init__(self, threshold: int = 3, cooldown: float = 60.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.success = 0
        self.fail = 0
        self.consecutive_failures = 0
        self.latency_ewma: Optional[float] = None
        self.state = "closed"
        self.open_until = 0.0

    def allow(self) -> bool:
        """circuit open 且未到冷却 → 拒绝; 到冷却 → 半开探活。"""
        if self.state == "open":
            if time.monotonic() >= self.open_until:
                self.state = "half_open"
                return True
            return False
        return True

    def record_success(self, latency: float) -> None:
        self.success += 1
        self.consecutive_failures = 0
        self.latency_ewma = (
            latency if self.latency_ewma is None else 0.7 * self.latency_ewma + 0.3 * latency
        )
        self.state = "closed"

    def record_failure(self) -> None:
        self.fail += 1
        self.consecutive_failures += 1
        if self.state == "half_open" or self.consecutive_failures >= self.threshold:
            self.state = "open"
            self.open_until = time.monotonic() + self.cooldown

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "success": self.success,
            "fail": self.fail,
            "consecutive_failures": self.consecutive_failures,
            "latency_ewma": round(self.latency_ewma, 3) if self.latency_ewma else None,
        }


def _compare_daily(a: tuple[str, pd.DataFrame], b: tuple[str, pd.DataFrame]):
    """双写比对: 对齐 date, 比 pct_chg (口径无关, 不受复权影响)。

    返回 None = 一致; 返回 dict = 分歧详情 (附两源值)。容差 0.5 个百分点。
    """
    (na, da), (nb, db) = a, b
    if "pct_chg" not in da.columns or "pct_chg" not in db.columns:
        return None
    ma = da[["date", "pct_chg"]].dropna()
    mb = db[["date", "pct_chg"]].dropna()
    merged = ma.merge(mb, on="date", suffixes=(f"_{na}", f"_{nb}"))
    if merged.empty:
        return {"reason": "两源无重叠日期, 无法交叉校验", "sources": [na, nb]}
    diff = (merged[f"pct_chg_{na}"] - merged[f"pct_chg_{nb}"]).abs()
    bad = merged[diff > 0.5]
    if bad.empty:
        return None
    row = bad.iloc[-1]
    return {
        "field": "pct_chg",
        "mismatched_dates": int(len(bad)),
        "sources": [na, nb],
        "sample": {
            "date": str(row["date"]),
            na: float(row[f"pct_chg_{na}"]),
            nb: float(row[f"pct_chg_{nb}"]),
        },
    }


class SourceRouter:
    """按健康度动态路由 + 稳定平面双写交叉。

    - `get_daily` / `get_stock_list`: 双写交叉 (顺序拉 >=2 健康源, 比对)。
    - 其余: 有序 fallback (第一个健康且成功的源)。
    - 全挂: 返回 web_fallback=True 的 surface。
    """

    def __init__(
        self,
        sources: list[DataSource],
        *,
        breaker_threshold: int = 3,
        cooldown: float = 60.0,
        dual_write: bool = True,
        retries: int = 2,
        timeout: float = 15.0,
    ) -> None:
        self._sources = sources
        self._health = {s.name: HealthState(breaker_threshold, cooldown) for s in sources}
        self._dual_write = dual_write
        self._retries = retries
        self._timeout = timeout

    # -- 内部 -------------------------------------------------------------- #
    def _healthy(self, capability: str) -> list[DataSource]:
        return [
            s for s in self._sources
            if s.supports(capability) and self._health[s.name].allow()
        ]

    def _preferred(self, capability: str) -> Optional[str]:
        for s in self._sources:
            if s.supports(capability):
                return s.name
        return None

    def _call(self, source: DataSource, method: str, args: tuple):
        fn = getattr(source, method)
        health = self._health[source.name]
        start = time.monotonic()
        try:
            with _silence_stdout():
                df = _call_with_retry(
                    lambda: fn(*args), retries=self._retries, timeout=self._timeout
                )
            health.record_success(time.monotonic() - start)
            return df, None
        except SourceUnsupported as e:
            return None, str(e)  # 不算失败, 不计入 breaker
        except Exception as e:  # noqa: BLE001
            health.record_failure()
            logger.warning(f"[{source.name}.{method}] 失败: {e}")
            return None, str(e)

    # -- 双写交叉 ---------------------------------------------------------- #
    def _dispatch_dual(self, method: str, capability: str, args: tuple, compare, cache_df=None):
        healthy = self._healthy(capability)
        results: list[tuple[str, pd.DataFrame]] = []
        for s in healthy:
            df, _ = self._call(s, method, args)
            if df is not None and not df.empty:
                results.append((s.name, df))
                if not self._dual_write or len(results) >= 2:
                    break
        if not results:
            return self._web_fallback([s.name for s in healthy])
        primary_name, primary_df = results[0]
        out: dict[str, Any] = {
            "df": primary_df,
            "sources": [r[0] for r in results],
            "warnings": [],
            "web_fallback": False,
        }
        if len(results) >= 2:
            disc = compare(results[0], results[1])
            out["confidence"] = "low" if disc else "high"
            out["discrepancy"] = disc
            out["degraded"] = bool(disc)
            if disc:
                out["warnings"].append(f"双写分歧: {results[0][0]} vs {results[1][0]}, 见 discrepancy")
        else:
            out["confidence"] = "single"
            out["discrepancy"] = None
            out["degraded"] = True
            out["warnings"].append(f"仅 {primary_name} 单源可得, 未能交叉校验")
        return out

    # -- 有序 fallback ----------------------------------------------------- #
    def _dispatch_single(self, method: str, capability: str, args: tuple):
        healthy = self._healthy(capability)
        preferred = self._preferred(capability)
        tried: list[str] = []
        for s in healthy:
            df, _ = self._call(s, method, args)
            tried.append(s.name)
            if df is not None and not df.empty:
                return {
                    "df": df,
                    "source": s.name,
                    "sources": tried,
                    "degraded": s.name != preferred,
                    "warnings": ([] if s.name == preferred
                                 else [f"降级到备源 {s.name} (主源 {preferred} 不可用)"]),
                    "web_fallback": False,
                }
        return self._web_fallback(tried)

    def _web_fallback(self, tried: list[str]) -> dict[str, Any]:
        return {
            "df": None,
            "source": None,
            "sources": tried,
            "confidence": "none",
            "discrepancy": None,
            "degraded": True,
            "web_fallback": True,
            "warnings": [
                f"所有结构化源失败 (tried={tried or '无健康源'}). "
                "MAY 按 a-share-data skill 的白名单 web-fetch 该 symbol, 并强制标注来源+口径."
            ],
        }

    # -- 对外接口 ---------------------------------------------------------- #
    def get_daily(self, symbol: str, start: str, end: str):
        return self._dispatch_dual("fetch_daily", "daily", (symbol, start, end), _compare_daily)

    def get_stock_list(self, market: str):
        def _cmp(a, b):  # 双写交叉: 比行数量级 (完整清单逐行 diff 无意义)
            (na, da), (nb, db) = a, b
            if abs(len(da) - len(db)) > max(50, 0.1 * max(len(da), len(db))):
                return {"field": "row_count", "sources": [na, nb],
                        "sample": {na: len(da), nb: len(db)}}
            return None
        return self._dispatch_dual("fetch_stock_list", "stock_list", (market,), _cmp)

    def get_realtime(self, symbols: list[str]):
        return self._dispatch_single("fetch_realtime", "realtime", (symbols,))

    def get_financial(self, symbol: str, report: str, period: str):
        return self._dispatch_single("fetch_financial", "financial", (symbol, report, period))

    def get_north_flow(self):
        return self._dispatch_single("fetch_north_flow", "north_flow", ())

    def get_dragon_tiger(self, date: str):
        return self._dispatch_single("fetch_dragon_tiger", "dragon_tiger", (date,))

    def get_notices(self, symbol: str, limit: int):
        return self._dispatch_single("fetch_notices", "notices", (symbol, limit))

    def get_news(self, limit: int):
        return self._dispatch_single("fetch_news", "news", (limit,))

    def get_disclosure(self, symbol: str, start: str, end: str, market: str, keyword):
        return self._dispatch_single(
            "fetch_disclosure", "disclosure", (symbol, start, end, market, keyword)
        )

    def get_interactive(self, symbol: str, limit: int):
        return self._dispatch_single("fetch_interactive", "interactive", (symbol, limit))

    def health_report(self) -> dict[str, Any]:
        return {name: h.snapshot() for name, h in self._health.items()}


def build_router(config: dict[str, Any]) -> SourceRouter:
    """按 config.sources.* 开关构造 router。akshare 恒在; baostock/tushare 按开关。"""
    sources_cfg = config.get("sources", {})
    router_cfg = config.get("router", {})
    sources: list[DataSource] = [AkshareSource()]
    if sources_cfg.get("baostock", {}).get("enabled", True):
        sources.append(BaostockSource())
    ts_cfg = sources_cfg.get("tushare", {})
    if ts_cfg.get("enabled") and ts_cfg.get("token"):
        try:
            sources.append(TushareSource(ts_cfg["token"]))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"tushare 初始化失败, 跳过: {e}")
    logger.info(f"SourceRouter sources: {[s.name for s in sources]}")
    return SourceRouter(
        sources,
        breaker_threshold=router_cfg.get("breaker_threshold", 3),
        cooldown=router_cfg.get("cooldown", 60.0),
        dual_write=router_cfg.get("dual_write", True),
        retries=router_cfg.get("retries", 2),
        timeout=router_cfg.get("timeout", 15.0),
    )
