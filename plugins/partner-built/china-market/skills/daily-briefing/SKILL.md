---
name: daily-briefing
description: "Generate a personalized daily A-share briefing driven by the user's derived watchlist (Shenwan industries + recently-discussed stocks). Use when asked for 「每日简报」「今日简报」「我的关注」「自选盯盘」 or when a system prompt injects a watchlist of industries + stocks and asks for a daily market briefing. Orchestrates china-market MCP tools (realtime quotes, north flow, news, notices, disclosures, dragon-tiger) plus financial-scripts ratio checks into a fixed three-section Chinese markdown briefing with a trailing machine-readable JSON block. Pair with a-share-data for the tool contract and tiered degradation rules."
---

# Daily Briefing (自选驱动每日简报)

输入契约: 调用方 (api-server briefing_service) 在 prompt 里注入
`{industries: [{code, name}], stocks: [{symbol, name, mentions}]}` — 行业来自用户
onboarding 自选 (申万一级), 个股来自其近 30 天会话讨论记录的加权 Top-N。

## 工具编排 (分层, 尽量批量, 控制轮次)

1. **大盘**: `get_realtime_quote(["000001.SH","399001.SZ","399006.SZ","000300.SH"])`
   + `get_north_flow()` + `get_stock_news(limit=20)` → 3-5 句市场主线。
2. **行业主题**: 每个关注行业, 从 `get_stock_news` / `get_dragon_tiger` 归纳当日
   主题与催化。**没有板块聚合 tool** — 由成分股与新闻推断时, `confidence` 如实标
   `low`, 不要过度自信。
3. **个股机会/风险**: 先批量 `get_realtime_quote(全部自选 symbols)`, 再逐股:
   - **R1** 单日涨跌 ≥ ±5% → 剧烈波动预警;
   - **公告/披露**: `get_stock_notices` / `get_disclosure_search` (近 7 天; 关注
     业绩预告、增减持、问询函、处罚、立案);
   - **龙虎榜**: `get_dragon_tiger` 是否上榜;
   - **财务异常**: 必要时 `get_financial_report` + `financial-scripts.financial_ratio_check`。
   无异动个股一句话带过。自选为空 → 跳过本节, 聚焦大盘与行业。

## 数据纪律

遵循 `a-share-data` 的分层降级范式: 结构化 MCP 优先 → `degraded`/`web_fallback`
时走白名单 web-fetch (优先 sina, 避开 eastmoney) → 拿不到如实说明, 绝不编造数字。
每条要点注明数据来源与置信度。

## 输出契约 (固定, 供前端解析)

简体中文 markdown, 三节结构「大盘概览 / 行业主题 / 个股预警」, 500-900 字。
**正文之后必须追加一个 fenced ```json 块** (调用方按最后一个 json 块抽取):

```json
{
  "as_of": "YYYY-MM-DD",
  "market_overview": {"summary": "...", "confidence": "high|low|none"},
  "sectors": [{"industry_code": "801080", "name": "电子", "theme": "...", "signals": ["..."], "confidence": "low"}],
  "stocks": [{"symbol": "688981.SH", "name": "中芯国际", "opportunities": ["..."], "risks": ["..."], "alerts": [{"rule": "R1", "detail": "单日 +6.2%"}], "confidence": "high"}],
  "degraded": false,
  "disclaimer": "本简报由 AI 依据公开数据生成, 不构成投资建议。"
}
```

> 注意: api-server 侧 `briefing_service.build_prompt` 内联了本契约的精简副本作为
> 兜底 (omp 未发现本 skill 时功能不受影响)。修改契约时**两处同步**。
