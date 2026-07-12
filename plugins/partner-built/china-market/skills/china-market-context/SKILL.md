---
name: china-market-context
description: "Inject China A-share market context into financial analysis. Trigger automatically whenever the user mentions a 6-digit Chinese stock ticker (e.g. 600519, 000858, 300750), a .SH or .SZ suffix, a well-known Chinese company name (贵州茅台、宁德时代、招商银行、比亚迪、中芯国际 …), or explicitly says A-share / 沪深 / 上证 / 深证 / 沪市 / 深市 / 创业板 / 科创板. Sets risk-free rate to China 10Y government bond yield, equity risk premium to the China-specific ERP, currency to CNY, tax rate to 25%, accounting standard to CAS (中国会计准则), filing references to 年报/半年报/季报 (NOT 10-K/10-Q via SEC EDGAR), and peer universe selection to 申万行业分类 (Shenwan SWS). Works alongside dcf-model, comps-analysis, earnings-analysis, 3-statement-model and competitive-analysis skills — this skill only injects context, it does not replace any modeling skill. Use the china-market MCP server (get_daily_bars, get_realtime_quote, get_financial_report, get_market_context, …) as the primary fundamentals/quotes data source for A-share names, in place of Daloopa / FactSet / S&P Kensho / Morningstar."
---

# China A-share Market Context

When you are about to analyze a Chinese A-share company (沪深两市), **do not use the US defaults baked into dcf-model / comps-analysis / earnings-analysis**. Use the values below instead, and call the `china-market` MCP server for fundamentals and quotes.

This skill **does not run a model itself**. It is a context patch that the calling skill (DCF, comps, earnings, etc.) must respect.

## Trigger signals (match any one)

- A 6-digit ticker — `600519`, `000858`, `300750`, `688981`
- Suffix `.SH` or `.SZ` — `600519.SH`, `000858.SZ`
- Chinese exchange names — 上证 / 上交所 / 深证 / 深交所 / 沪市 / 深市 / 沪深 / 创业板 / 科创板 / 北交所
- Well-known Chinese A-share company in Chinese — 贵州茅台、宁德时代、招商银行、比亚迪、中芯国际、平安银行、立讯精密、海康威视、五粮液、长江电力、隆基绿能
- Explicit phrase — "A 股 / A-share / China stock"

If only some of the above are present but the company is **also dual-listed in HK/US** (e.g. 中国平安 has 601318.SH AND 2318.HK), still apply this context for the A-share side and tell the user clearly which listing the analysis applies to.

## Required substitutions

| Field | US default (in upstream skill) | China A-share value |
|---|---|---|
| Currency | USD | **CNY** (人民币元) |
| Risk-free rate | US 10Y Treasury yield | **China 10Y government bond yield** — call `get_market_context` MCP tool, default baseline 2.7% (must be labeled "as of …, please verify") |
| Equity risk premium | ~5.0% (US ERP) | **6.0%** (Damodaran China ERP, range 5.5–6.5%) |
| Marginal tax rate | 21% (US federal) | **25%** (中国法定企业所得税率) — 高新技术企业按 15%, 用户确认后再改 |
| Accounting standard | US GAAP | **CAS (中国会计准则)** |
| Primary filings | SEC 10-K / 10-Q (EDGAR) | **巨潮资讯网 (cninfo.com.cn)** — 年报 / 半年报 / 季报 |
| Peer universe | GICS sector / sub-industry | **申万行业分类 (Shenwan SWS)** L2 同板块, fallback 中证行业 |
| Preferred valuation multiples | EV/EBITDA, P/E, P/B | **P/E, P/B, PEG**(EV/EBITDA 在银行/地产/券商权重大的 A 股 universe 不主流, 谨慎使用)|
| Reporting frequency | 4 full quarterly disclosures | Q1 / Q3 是简报, Q2 中报、Q4 年报相对详细 |
| Conference call source | Earnings call transcript (Aiera/MT Newswire) | **业绩说明会纪要** (上证 e 互动 / 深证互动易 / 全景网), 中文为主 |

## CAS → IFRS-ish line item mapping (for DCF/3-statement)

When `get_financial_report` returns 中文 line items, translate them to the schema dcf-model expects:

| 中文 (CAS) | English equivalent |
|---|---|
| 营业总收入 / 营业收入 | Revenue / Net sales |
| 营业总成本 / 营业成本 | COGS (营业成本) + Operating expenses |
| 销售费用 | Selling & marketing expense |
| 管理费用 | General & administrative expense |
| 研发费用 | R&D expense |
| 财务费用 | Net interest expense |
| 营业利润 | Operating income (口径略有差异, 含投资收益) |
| 利润总额 | Pre-tax income |
| 所得税费用 | Income tax expense |
| 净利润 | Net income (含少数股东权益) |
| 归属于母公司股东的净利润 | Net income attributable to parent (≈ US GAAP net income) |
| 基本每股收益 | Basic EPS |
| 经营活动产生的现金流量净额 | Cash flow from operations |
| 投资活动产生的现金流量净额 | Cash flow from investing |
| 筹资活动产生的现金流量净额 | Cash flow from financing |

**重要**: A 股 "净利润" 默认含少数股东权益, 做 DCF 时务必用 "归属于母公司股东的净利润" 做 per share 估值.

## Data source routing (use china-market MCP, not Daloopa/FactSet/Kensho)

In the upstream skill prompts you will see lines like *"If a fundamentals MCP server is available (e.g. Daloopa), pull X"*. Substitute as follows:

| Upstream skill needs | Call this china-market MCP tool |
|---|---|
| Historical OHLCV / 价格 | `get_daily_bars(symbols, start_date, end_date)` |
| Current quote / 实时报价 | `get_realtime_quote(symbols)` |
| Income statement / 利润表 | `get_financial_report(symbol, report="income", period="annual")` |
| Balance sheet / 资产负债表 | `get_financial_report(symbol, report="balance", ...)` |
| Cash flow / 现金流量表 | `get_financial_report(symbol, report="cashflow", ...)` |
| Filings list / 公告 | `get_stock_notices(symbol)` |
| Market news / 财经新闻 | `get_stock_news(limit=N)` |
| Risk-free / ERP / tax / 行业分类 | `get_market_context()` |
| 北向资金 (外资态度) | `get_north_flow()` |
| 龙虎榜 (单日异动席位) | `get_dragon_tiger(date)` |

**数据源失败时走分层降级 (取代旧「禁止 fallback」硬规)**:china-market 现在是多源
(akshare/baostock/tushare) 双写交叉 + 动态路由。看返回体的 `confidence` / `degraded` /
`web_fallback` 字段: `low` 分歧必须展示 discrepancy 两源值; `web_fallback:true` 时**才**
按 `references/WEB_FALLBACK_WHITELIST.md` 的**白名单**站点 web-fetch (仅白名单, 强制标来源+口径),
而不是从随机网页抓 A 股财务数字。详见 `a-share-data` skill 的 Behavior contract。

## When the user asks for cross-market comparison

If the user wants 「比较 600519 和 NVDA」/ 「贵州茅台 vs LVMH」 etc.:

1. For the A-share side, use this context + china-market MCP.
2. For the US side, keep the upstream US defaults (10Y Treasury, US ERP, GICS, etc.).
3. **In the final report, present two valuation tables side by side with currency columns clearly marked (CNY vs USD).** Do not convert to a single currency unless the user explicitly asks — exchange-rate noise dominates short-horizon estimates.
4. Note divergent multiples: A-share companies frequently trade at very different PE / PB vs US peers due to liquidity, capital controls, and retail investor share — flag the multiple gap, do not silently average across markets.

## Cross-listing handling (preview, v2 will expand)

- A-share + H-share dual-listed (601318.SH / 2318.HK, 600028.SH / 0386.HK …): say which listing the analysis covers, and note the A/H 折溢价.
- A-share + ADR (e.g. 中石油 / PTR delisted): default to A-share, mention ADR sunset.

## Disclaimer to include in output

Any DCF / comps / IC memo / earnings note for an A-share company must end with:

> 本分析基于公开数据 (akshare / baostock / tushare 多源交叉聚合), 财务报表口径为中国会计准则 (CAS). 估值假设和市场常量 (risk-free, ERP, 行业分类) 为参考默认值, 实际使用请以最新数据复核. 若数据来自 web-fetch 兜底, 已在正文标注来源与口径. **不构成投资建议**.
