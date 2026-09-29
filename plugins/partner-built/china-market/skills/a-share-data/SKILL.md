---
name: a-share-data
description: "Explicit data query skill for the china-market MCP server. Use when the user directly asks to fetch A-share data — phrases like 「拉一下 600519 近一年日线」「最近北向资金」「贵州茅台公告」「查个股财务报表」「实时报价」, or any natural-language data request that mentions a Chinese ticker / company. This skill lists the china-market MCP tools, their params, the unified return envelope (sources / confidence / degraded / web_fallback), and the tiered degradation paradigm (structured multi-source → whitelisted web-fetch → surface failure). Pair with china-market-context when the user wants the data turned into an analysis."
---

# A-share Data Query (china-market MCP)

`china-market` MCP server 现在是**自包含多源 + 双写交叉 + 动态路由**的数据层
(akshare + baostock + tushare, 经 `SourceRouter`)。直接调下列 tool 拿 A 股数据。

| Tool | Purpose | Key args | 数据平面 |
|---|---|---|---|
| `get_daily_bars` | 日线 OHLCV (不复权) | `symbols: list[str]`, `start_date`, `end_date` | 稳定·**双写交叉** |
| `get_stock_list` | A 股清单 (含行业, peer universe) | `market ∈ {all,sh,sz}` | 稳定·**双写交叉** |
| `get_realtime_quote` | 实时行情 + 名称 + 涨跌幅 | `symbols: list[str]` | 实时·短 TTL 缓存 |
| `get_financial_report` | 财务三大表 | `symbol`, `report ∈ {income,balance,cashflow}`, `period ∈ {annual,quarterly}` | 稳定·有序 fallback |
| `get_stock_notices` | 个股公告 (年报/中报/季报/重大事项) | `symbol`, `limit` | best-effort |
| `get_disclosure_search` | 巨潮披露检索 (监管/披露结构化直连) | `symbol`, `start_date`, `end_date`, `market="沪深京"`, `keyword` | best-effort |
| `get_interactive_qa` | 投资者互动问答 (深证互动易/上证e互动) | `symbol`, `limit` | best-effort |
| `get_stock_news` | 全市场财经新闻 | `limit` | best-effort |
| `get_north_flow` | 北向资金 (沪股通+深股通) | — | 特色·有序 fallback |
| `get_dragon_tiger` | 单日龙虎榜 | `date` | 特色·有序 fallback |
| `get_market_context` | 风险利率/ERP/税率/行业分类常量 | — | 本地常量 |
| `get_source_health` | 各源 circuit breaker/成功率/延迟 | — | 诊断 |

## Symbol convention

- 沪市 `.SH`(主板/科创板): `600519.SH`, `688981.SH`
- 深市 `.SZ`(主板/创业板): `000858.SZ`, `300750.SZ`
- 6 位代码 `6` 开头 → `.SH`, `0`/`3` 开头 → `.SZ`(北交所 `8` 开头暂未覆盖)

## 统一返回体 (每个 tool 都返回这些字段)

```jsonc
{
  "rows": [...], "count": N, "columns": [...],
  "sources": ["akshare", "baostock"],  // 实际参与的源 (双写时 ≥2)
  "confidence": "high|low|single|stale|none",  // 双写一致性
  "degraded": false,                    // 是否降级到备源/单源/stale
  "discrepancy": null,                  // 双写分歧详情 (附两源值)
  "warnings": [...],                    // 口径/新鲜度/降级提醒
  "web_fallback": false                 // true = 结构化源全挂, 授权走白名单 web-fetch
}
```

## Behavior contract —— 分层降级范式 (取代旧「失败直接报错/禁 web」)

用户问 A 股数据时, 按以下 tier **逐层降级**, 每层都要把数据源与置信度如实告知:

1. **调 `china-market.*`** —— 内部已自动 akshare→baostock(→tushare) 双写交叉 + 动态路由,
   多数情况一次搞定。
2. **看 `confidence` / `degraded`**:
   - `high` → 两源一致, 直接用。
   - `low` → 两源对不上, **必须**向 user 展示 `discrepancy` 里的两源值, 不要静默取一个。
   - `single` / `degraded:true` → 只有一源可得或降级到备源, 标注「数据由 <source> 提供, 未交叉校验」。
   - `stale` → 上游全挂、返回本地缓存, 明确提示数据可能过期。
3. **`web_fallback: true`** → 结构化源全挂。此时**才**进入白名单 web-fetch tier
   (见 `references/WEB_FALLBACK_WHITELIST.md`): **只允许白名单站点**, 且强制标注
   来源 URL + 口径提醒 (CAS/IFRS、合并/母公司、归母)。
4. **白名单也拿不到** → 才向 user 报「数据暂不可得」, 并建议用 `get_source_health` 看哪源熔断。

> 港股 (`.HK`) china-market **不覆盖** → 直接走白名单 web-fetch tier (AAStocks / 东财港股 /
> futu / 雪球港股), 见 whitelist 文档。

## 失败 → 自净化

当发生 web_fallback / 双写分歧 / 某源反复熔断时, 触发 `data-source-postmortem` skill 的
log mode 记一条到 `data_cache/failure_log.jsonl`, 供日后 reflect 归纳并调 router 配置。

## Quick examples (内部参考, 不要 echo 给 user)

| 用户说 | 调什么 |
|---|---|
| "拉 600519 最近一年日线" | `get_daily_bars(["600519.SH"], _, _)` → 看 confidence |
| "看看茅台现在价格" | `get_realtime_quote(["600519.SH"])` |
| "茅台 2023 年报" | `get_financial_report("600519.SH", "income", "annual")` + balance/cashflow |
| "今天北向资金流向" | `get_north_flow()` |
| "宁德时代最近有什么公告" | `get_stock_notices("300750.SZ", limit=20)`, web_fallback 则查巨潮 |
| "茅台有没有被监管问询/处罚" | `get_disclosure_search("600519.SH", keyword="问询函\|处罚\|立案\|监管\|警示")`, 空则查 csrc/sse/szse |
| "宁德时代互动易问了啥" | `get_interactive_qa("300750.SZ", limit=20)` |
| "腾讯 00700.HK 走势" | china-market 不覆盖港股 → 白名单 web-fetch (AAStocks/雪球港股) |
| "哪个数据源老挂" | `get_source_health()` |

如果用户要做估值 / 财报分析 / 跨市场比较, 让 `china-market-context` skill 接管。
