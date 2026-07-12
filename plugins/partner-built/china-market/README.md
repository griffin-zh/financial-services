# china-market — A-share data plugin for `financial-services`

把 `anthropics/financial-services` 现有的 DCF / comps / earnings / 3-statement 等 skill 接到中国 A 股(沪深两市)上,不 fork 任何官方 skill,只新增一个本地 MCP server + 一个自动触发的 router skill。

港股 (`.HK`) 留作 v2,本版只覆盖 A 股(`.SH` / `.SZ`)。

## 为什么需要这个 plugin

`financial-services` 自带的 11 个 MCP connector(Daloopa / FactSet / S&P Kensho / Morningstar …)全是美式数据源,A 股完全不覆盖。但好消息是,核心 skill(`dcf-model`、`comps-analysis` …)对 MCP 是**软引用**(「if a fundamentals provider is available, use it」),对 US specifics(10Y Treasury / GICS / SEC EDGAR)是**默认值**而非硬阻断。

所以扩展 A 股不需要 fork,只需要:

1. **提供一个 `china-market` MCP server**,让 skill 在分析 A 股名字时能取到数据
2. **提供一个自动触发的 router skill**(`china-market-context`),在用户提到 6 位 ticker / `.SH/.SZ` / 中文公司名时,把 risk-free / ERP / 币种 / 行业分类等上下文打补丁

## 目录结构

```
china-market/
├── .claude-plugin/plugin.json       # 内联 mcpServers,指 stdio Python server
├── mcp_server/
│   ├── server.py                    # MCP entry, wraps Stock/ai_quant/data/
│   ├── config.yaml                  # 只启用 akshare (免费, 无 token)
│   ├── requirements.txt
│   └── __init__.py
├── skills/
│   ├── china-market-context/SKILL.md   # 自动触发, 注入市场上下文
│   └── a-share-data/SKILL.md           # 显式触发, MCP tool 速查
└── README.md
```

## 依赖与耦合

MCP server **复用** `d:/work/study/Stock/ai_quant/data/` 已有的 `DataManager` + `AKShareSource`,不重复实现。这是唯一外部耦合 —— 必须设置环境变量 `STOCK_PROJECT_ROOT` 指向 Stock 项目根目录(默认 `d:/work/study/Stock`)。已在 `plugin.json` 里写死,跨机器使用时按需改。

## 安装

```bash
# 1. 装 MCP server 依赖
pip install -r plugins/partner-built/china-market/mcp_server/requirements.txt
# (akshare / mcp / pandas / pyarrow / pyyaml / loguru)

# 2. 注册 marketplace (本地路径)
claude plugin marketplace add d:/work/study/financial-services

# 3. 装 plugin
claude plugin install china-market@financial-services-local

# 4. (可选) 也装核心方法论 plugin
claude plugin install financial-analysis@financial-services-local
```

启动 Claude Code 之后,`/mcp` 命令应能看到 `china-market` server,`/help` 里能找到 `china-market-context` 和 `a-share-data` 两个 skill。

## MCP tool 清单

| Tool | 用途 |
|---|---|
| `get_daily_bars` | 日线 OHLCV(qfq, 含缓存) |
| `get_realtime_quote` | 实时行情快照(东方财富) |
| `get_financial_report` | 利润表 / 资产负债表 / 现金流量表(年报/季报) |
| `get_stock_notices` | 个股公告(年报/中报/季报/重大事项) |
| `get_stock_news` | 全市场财经新闻 |
| `get_north_flow` | 北向资金实时净流入 |
| `get_dragon_tiger` | 单日龙虎榜 |
| `get_stock_list` | A 股清单 + 行业(用于 peer universe) |
| `get_market_context` | 风险利率 / ERP / 税率 / 行业分类等市场常量 |

## 验证(必须手动跑过)

1. **MCP 独立可启动**
   ```bash
   cd plugins/partner-built/china-market
   PYTHONPATH=. STOCK_PROJECT_ROOT=d:/work/study/Stock python -m mcp_server.server
   # 应输出 "china-market MCP server ready. Active sources: ['akshare']" 后挂起等待 stdio 输入
   ```

2. **Plugin 装载** —— `/mcp` 命令看到 `china-market`,`/help` 里能搜到两个 skill。

3. **Router skill 自动触发** —— 新会话只说「帮我看下 600519 这家公司」,Claude 应自动加载 `china-market-context`,并在回复里**主动**提到 CNY 计价、中国 10Y 国债 risk-free。

4. **DCF 联跑** —— 「用 dcf-model 给 600519 做估值」,验证:
   - Claude 调用 `china-market` MCP,不去找 daloopa
   - WACC 输入用中国 10Y 国债,不是 US Treasury
   - Excel 输出币种是 CNY

5. **联合分析 happy path** —— 「比较 600519 和 NVDA 的 valuation」,Claude 应同时用 china-market 取 600519、用 web/已有 connector 取 NVDA,在最终输出**两列币种分开**、估值口径差异有标注。

6. **`scripts/check.py` 全绿** —— `python3 scripts/check.py` 在 financial-services 根目录运行,marketplace 链接检查通过,drift 检查不触发(没 bundle 到任何 agent)。

## 不在本版范围

- ❌ 港股 `.HK`(留 v2,akshare 的 `stock_hk_*` 接口包一层就行)
- ❌ 财报 PDF 深度提取(留 v2,巨潮 PDF → markitdown → earnings-analysis)
- ❌ Tushare 增强(留 v2,需要 token)
- ❌ Bundle 到 pitch-agent 等 agent-plugin(留按需,跑 `sync-agent-skills.py` 即可)

## License

Apache-2.0,与上游 `financial-services` 一致。
