# Financial Services Plugins

Cowork plugins and Claude Managed Agent templates for financial services. Each named agent ships two ways from one source.

## Repository Structure

```
├── plugins/
│   ├── agent-plugins/               #   named agents — one self-contained plugin each
│   │   └── <slug>/
│   │       ├── .claude-plugin/plugin.json
│   │       ├── agents/<slug>.md     #   ← canonical system prompt (one source, two wrappers)
│   │       └── skills/              #   ← bundled copies, synced from vertical-plugins/
│   ├── vertical-plugins/            #   FSI verticals — skill sources, commands, MCPs
│   │   └── <vertical>/
│   │       ├── .claude-plugin/plugin.json
│   │       ├── commands/
│   │       ├── skills/
│   │       └── .mcp.json
│   └── partner-built/               #   partner plugins (LSEG, S&P Global)
├── managed-agent-cookbooks/         # CMA cookbooks (one dir per named agent)
│   └── <slug>/
│       ├── agent.yaml               #   system + skills → ../../plugins/agent-plugins/<slug>/...
│       ├── subagents/*.yaml         #   depth-1 leaf workers
│       ├── steering-examples.json
│       └── README.md                #   security tier + handoff notes
├── claude-for-msft-365-install/     # admin tooling for the Microsoft 365 add-in (separate from FSI plugins)
└── scripts/                         # deploy-managed-agent.sh, check.py, validate.py, orchestrate.py, sync-agent-skills.py
```

Run `python3 scripts/check.py` before committing — it lints every manifest, verifies all `system.file` / `skills.path` / `callable_agents.manifest` references resolve, fails if any `agent-plugins/<slug>/skills/` copy has drifted from its `vertical-plugins/` source, and rejects non-ASCII bytes in a `.ps1` without a UTF-8 BOM.

**Keep `.ps1` files pure ASCII.** Windows PowerShell 5.1 — still the default shell on managed Windows — decodes a BOM-less `.ps1` using the machine's ANSI code page, not UTF-8. An em dash or curly quote becomes mojibake that can contain a literal `"`, which terminates a string and makes the whole script fail to *parse*. Write `--`, not `—`. This is invisible on macOS and fatal on Windows; `check.py` gates it. **Edit skills in `vertical-plugins/`**, then run `python3 scripts/sync-agent-skills.py` to propagate into the agent bundles.

`check.py` also self-installs a `pre-commit` hook (`git config core.hooksPath .githooks` — no Husky/Node). The hook patch-bumps any plugin's `.claude-plugin/plugin.json` `version` so a branch ends up exactly one patch ahead of `main` (bumped once, not per commit — a plugin's `version` gates update delivery to already-installed users). The `version-bump` GitHub Action enforces the same rule on PRs as a backstop. Bypass a single commit with `git commit --no-verify`; bump logic lives in `scripts/version_bump.py`.

## Key Files

- `marketplace.json`: Marketplace manifest - registers all plugins with source paths
- `plugin.json`: Plugin metadata - name, description, version, and component discovery settings
- `commands/*.md`: Slash commands invoked as `/plugin:command-name`
- `skills/*/SKILL.md`: Detailed knowledge and workflows for specific tasks
- `*.local.md`: User-specific configuration (gitignored)
- `mcp-categories.json`: Canonical MCP category definitions shared across plugins

## Development Workflow

1. Edit markdown files directly - changes take effect immediately
2. Test commands with `/plugin:command-name` syntax
3. Skills are invoked automatically when their trigger conditions match

## A-share data routing(china-market plugin)

`partner-built/china-market` 是这个 repo 里**唯一覆盖 A 股**(沪深两市)的数据源。它是一个自包含 stdio MCP server,内部经 `SourceRouter` 对 [akshare](https://github.com/akfamily/akshare) + baostock + tushare 三源做 **health-aware 动态路由 + 稳定平面双写交叉**,并提供两个 skill 自动注入中国市场上下文。

### 触发(任意一条匹配)

- 6 位 A 股代码:`600519`、`688525`、`300750`
- 后缀 `.SH` / `.SZ`:`600519.SH`、`000858.SZ`
- 中文 A 股公司名:贵州茅台、宁德时代、赤峰黄金、佰维存储、…
- 关键词:A 股 / A-share / 沪深 / 上证 / 深证 / 沪市 / 深市 / 创业板 / 科创板 / 北交所

### 行为契约

1. **第一动作**:确认 `/mcp` 里有 `china-market` server(状态 `connected`)。
2. 用 plugin 暴露的 11 个 MCP tool 拉数据(`get_daily_bars` / `get_realtime_quote` / `get_financial_report` / `get_stock_notices` / `get_market_context` / `get_north_flow` / `get_dragon_tiger` / `get_stock_news` / `get_stock_list` / `get_source_health`)。**数据源失败走分层降级,不是硬禁 web**:看返回体 `confidence` / `degraded` / `web_fallback` 字段 —— `web_fallback:true` 时按 `references/WEB_FALLBACK_WHITELIST.md` 的**白名单**站点 web-fetch(仅白名单、标来源+口径);港股 `.HK` MCP 不覆盖,直接走白名单。详见 `a-share-data` skill。
3. **MCP server 跑在 `financial` env**(Python 3.11,装了 `mcp` + akshare/baostock/tushare)—— `mcp` 包要求 Python ≥3.10,quant env 是 3.9 装不了。若在 Bash 里直接跑 akshare 分析 script(不经 MCP),仍用 `conda run -n quant python ...`(quant 有 akshare,是 script 场景的 env)。两者分工:**MCP=financial,直连 script=quant**。
4. `plugins/partner-built/china-market/.claude-plugin/plugin.json` 里 MCP server `command` 指向 `D:/tools/miniconda/envs/financial/python.exe`,这是 single source of truth — 如果改了 env,同步改这里。
5. 跨市场分析(A 股 vs 美股)时,A 股侧用 china-market MCP,美股侧用 web / 已有 connector,**两侧币种分开列**,不要做隐式汇率换算。

### Plugin 没装 / `/mcp` 看不到 china-market

提示用户先跑 install,**不要** fallback:

```bash
claude plugin marketplace add d:/work/study/financial-services
claude plugin install china-market@financial-services-local
```

### 依赖检查

```bash
# MCP server env (financial, Python 3.11 —— mcp 需 ≥3.10):
D:/tools/miniconda/envs/financial/python.exe -c "import mcp, akshare, baostock, tushare, pandas, yaml, loguru, pyarrow; print('all ok')"
# 缺包:
D:/tools/miniconda/envs/financial/python.exe -m pip install -r plugins/partner-built/china-market/mcp_server/requirements.txt
```

### Skill 详情

- **`plugins/partner-built/china-market/skills/china-market-context/SKILL.md`** — Router skill,自动触发;注入 risk-free / ERP / 税率 / 币种 / 会计科目映射 / 申万行业 / 巨潮 filings 等中国市场常量
- **`plugins/partner-built/china-market/skills/a-share-data/SKILL.md`** — 显式数据查询 skill;列举 11 个 MCP tool 用法 + 分层降级范式 + 统一返回体
- **`plugins/partner-built/china-market/skills/data-source-postmortem/SKILL.md`** — 自净化 skill;记录数据源失败/双写分歧到 `failure_log.jsonl`,reflect mode 归纳 pattern 并反哺 router 配置
- **`plugins/partner-built/china-market/references/WEB_FALLBACK_WHITELIST.md`** — web-fetch 兜底白名单(A 股 + 港股)+ 口径提醒
- **`plugins/partner-built/china-market/references/DATA_SOURCES.md`** — baostock vs tushare 选型 + 100 用户架构蓝图 + 商用 license 红线

`dcf-model` / `comps-analysis` / `earnings-analysis` 等核心 skill 是**软引用** MCP(「if a fundamentals provider is available, use it」),所以 china-market 接入后无需 fork 任何官方 skill。
