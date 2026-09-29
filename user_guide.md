# Financial Services Skills 投资者使用指南

> **一句话**:这套 skill 原本是给卖方 analyst / IB / PE / advisor 用的;作为个人投资者,你只需要其中 **10-15 个**,本指南告诉你**什么时候用哪个、为什么这么用、底下是怎么工作的**。

**前置条件(A 股用户必读)**:本指南假设你已经装了 [china-market](plugins/partner-built/china-market/) plugin(A 股数据接入 + 中国市场 context 自动注入)。否则所有 skill 默认会按美股逻辑(SEC 10-K、USD、US Treasury risk-free)跑,不适合 A 股名字。装法见 [china-market/README.md](plugins/partner-built/china-market/README.md)。

---

## 第一部分 · 投资者常见场景 → 该用哪个 skill

### 场景 1:我想找新标的(idea generation / screening)

| 你的诉求 | 推荐 skill | 命令 | 备注 |
|---|---|---|---|
| 按因子筛股(ROE / PE / 增速…) | `idea-generation` | `/screen` | 美股原版按 GICS;A 股配 china-market 后按申万分类 |
| 看一个板块/主题里有哪些公司 | `sector-overview` | `/sector` | 输出行业地图 + 龙头梳理 |
| 找一只新公司的同行可比 | `competitive-analysis` | `/competitive-analysis` | 反向用:输入一家,找出 peers |

### 场景 2:我看上一家公司,要不要深入研究?

| 你的诉求 | 推荐 skill | 命令 | 备注 |
|---|---|---|---|
| 30 秒了解一家公司(一页纸) | `strip-profile` | `/one-pager` | IB 用的 pitch one-pager,信息密度高,投资者也好用 |
| 完整研究一家公司(初次覆盖) | `initiating-coverage` | `/initiate` | 30-50 页 institutional-quality 报告 |
| 财务报表三表速看 | `3-statement-model` | `/3-statement-model` | 抓最近 5 年 IS/BS/CF 填模板 |

### 场景 3:我已经持仓,如何跟踪?

| 你的诉求 | 推荐 skill | 命令 | 备注 |
|---|---|---|---|
| 维护自己的「投资 thesis 笔记本」 | `thesis-tracker` | `/thesis` | 每次发生重大事件 update thesis |
| 列出未来 30/60/90 天 catalyst | `catalyst-calendar` | `/catalysts` | 业绩日 / 政策日 / 解禁日 / 发布会 |
| 每天早上看市场(类似研究所晨会) | `morning-note` | `/morning-note` | 隔夜美股 + 当日宏观日历 + 关注标的预览 |

### 场景 4:财报季 — 快速消化业绩

| 你的诉求 | 推荐 skill | 命令 | 备注 |
|---|---|---|---|
| 财报**前**的预期梳理 | `earnings-preview` | `/earnings-preview` | 关键 metric / consensus / 业绩预告 |
| 财报**后**的点评 | `earnings-analysis` | `/earnings` | 实际 vs 预期、Q&A 要点、模型调整方向 |
| 用新季报刷新自己的财务模型 | `model-update` | `/model-update` | 把新一季实际数代入,自动重算 |

### 场景 5:估值(核心场景)

| 你的诉求 | 推荐 skill | 命令 | 备注 |
|---|---|---|---|
| 内在价值(intrinsic value) | `dcf-model` | `/dcf` | **本指南示例**:[投资建议/茅台600519.md](投资建议/茅台600519.md) 就是用这个跑出来的 |
| 相对估值(看比可比公司贵不贵) | `comps-analysis` | `/comps` | PE / PB / EV/EBITDA / PEG 横向对比 |
| 收购方视角(私募 / 杠杆收购) | `lbo-model` | `/lbo` | 散户基本用不到,但「假设 PE 来收购它」可以做反推 |
| 收购 / 重组案分析 | `merger-model` | `/merger-model` | 看一笔并购对 acquirer 是 accretive 还是 dilutive |

### 场景 6:行业 / 主题研究

| 你的诉求 | 推荐 skill | 命令 |
|---|---|---|
| 一个行业的全景图 | `sector-overview` | `/sector` |
| 行业内竞争格局 | `competitive-analysis` | `/competitive-analysis` |
| 选股初筛 | `idea-generation` | `/screen` |

### 场景 7:跨市场对比(A 股 vs 美股 vs 港股)

| 你的诉求 | 怎么做 |
|---|---|
| 「贵州茅台 vs LVMH 谁更便宜?」 | 直接说自然语 → router skill (`china-market-context`) **自动**为 A 股侧注入 CNY/CAS/申万 context;美股侧保留 US default;最终输出**两列币种分开**的对比表 |
| 「中芯国际 vs TSMC vs SMIC ADR?」 | 同上,A 股 + 港股 + ADR 三栏对照 |

### 场景 8:别人给我一个 Excel model,我怎么 audit?

| 你的诉求 | 推荐 skill | 命令 |
|---|---|---|
| 查公式错误 / 硬编码 / 引用断点 | `audit-xls` | `/debug-model` |
| 清洗 / 标准化数据 | `clean-data-xls` | — |
| 检查 deck 是否有不一致 | `ib-check-deck` | — |

---

## 第二部分 · 不推荐个人投资者用的 skill(为什么)

| Skill | 为什么不适合散户 |
|---|---|
| `cim-builder` / `teaser` / `buyer-list` / `process-letter` / `pitch-deck` / `datapack-builder` / `deal-tracker` | 卖方 IB 工具:写卖项目的 marketing material、跑 sell-side process。除非你自己在做 sell-side,否则用不上 |
| `deal-sourcing` / `deal-screening` / `dd-checklist` / `dd-meeting-prep` / `ic-memo` / `portfolio-monitoring` / `value-creation-plan` / `ai-readiness` | 私募 / VC 投后 / IC 流程工具:目标公司是非上市 portfolio,跟二级市场投资逻辑不一样 |
| `client-review` / `financial-plan` / `portfolio-rebalance` / `client-report` / `investment-proposal` / `tax-loss-harvesting` | Wealth advisor 给客户用的,你给自己用会觉得 overkill(美国 TLH 规则也不适用 A 股) |
| `gl-reconciler` / `month-end-closer` / `statement-auditor` / `valuation-reviewer` / `kyc-screener` | 基金 ops / 合规工具,投资者无关 |

> 这些 skill 都还在,你 prompt 里点名就触发 — 我只是建议你**不主动用**。

---

## 第三部分 · Skill 实现原理总结

### 1. Skill 本质是什么

每个 skill 就是一个 markdown 文件:`<plugin>/skills/<skill-name>/SKILL.md`。结构如下:

```
---
name: dcf-model
description: "Real DCF model creation for equity valuation. Use when..."
---

# DCF Model Builder
... (skill body: 几十到上千行的方法论 + 例子 + 反例)
```

**没有可执行代码、没有 binary、没有 server**(MCP 除外)。是**纯 prompt**。

### 2. 触发机制 — description 字段是 trigger

Claude 在每轮对话开始时,会把所有可用 skill 的 `name + description` 加载到 context。当你的话里出现 description 里写的 keyword(例如 "DCF"、"intrinsic value"、"valuation"),Claude 自动 **Read** 对应的 SKILL.md 当 system instruction 跑。

所以:
- **description 越具体、关键词越丰富,触发越准** — 这就是为什么 [china-market-context/SKILL.md](plugins/partner-built/china-market/skills/china-market-context/SKILL.md#L3) 的 description 把茅台 / 宁德 / 申万 / .SH / .SZ 都列出来。
- 你也可以**显式调用** — 说「按 dcf-model skill 给 600519 估值」就强制触发,不需要赌 keyword match。
- 一次会话可以**多个 skill 叠加** — 例如 `china-market-context` + `dcf-model` 同时生效,前者给「中国市场参数」、后者给「DCF 方法论」。

### 3. Skill body 内部一般包含什么

以 `dcf-model` 为例(1264 行),典型 skill body 结构:

| 区段 | 内容 |
|---|---|
| Critical Constraints | 「禁止 hardcode、必须用公式、要分步给用户看、不允许跳过 sensitivity table」等硬规则 |
| Step-by-step workflow | Step 1 数据取数 → Step 2 历史分析 → Step 3 收入预测 → … → Step 10 sensitivity |
| `<correct_patterns>` | 正例:正确的公式结构、正确的 sensitivity 表布局 |
| `<common_mistakes>` | 反例:错误的简化、错误的行引用、错误的字体颜色 |
| Excel structure spec | 列宽 / 字体 / 颜色 / 边框 / 数字格式的硬规定 |
| Deliverable checklist | 交付前必跑的验证项 |

读完这种 skill 你会发现:**它不是给 Claude 自由发挥,而是把一个资深 analyst 脑子里的 muscle memory 写成检查清单**。

### 4. 数据从哪来

skill 自己**不抓数据**,而是 routing 到三类来源:

| 来源 | 怎么调 | 投资者用得最多的 |
|---|---|---|
| **MCP server** | skill 里写「if a fundamentals MCP is available, use it」,Claude 自动调 MCP tool | A 股 → [china-market MCP](plugins/partner-built/china-market/mcp_server/server.py)(9 个 tool);美股 → Daloopa / FactSet / S&P Kensho(需要付费 API) |
| **User-provided** | 你直接贴在 prompt 里 | 自己手抄的数据、研报截图 |
| **Web search** | skill 允许时退化到 web 搜 | 当前股价、宏观数据 |

**A 股的关键**:[china-market MCP](plugins/partner-built/china-market/mcp_server/server.py) 把 [Stock/ai_quant/data/](../Stock/ai_quant/data/) 里的 akshare wrapper 包成 stdio MCP server,暴露 9 个 tool(日线、实时报价、三大表、公告、新闻、北向资金、龙虎榜、股票列表、市场常量)。Skill 调这些 tool 时,数据走 **akshare**(免费,东方财富/新浪/巨潮聚合)— 不需要任何付费 key。

### 5. Excel / PowerPoint 输出原理

| 输出类型 | 用的库 | 走哪个 skill |
|---|---|---|
| `.xlsx` 财务模型 | `openpyxl`(纯 Python 写公式串)| `xlsx-author` + 任何模型 skill 调它 |
| `.pptx` 演示文稿 | `python-pptx`(填模板,不重画) | `pptx-author` + 任何 deck skill 调它 |
| 公式重算(deliver 前) | LibreOffice headless via `recalc.py` | 上游 xlsx skill 提供,可选 |

**关键约束(skill 强制)**:Excel 里**所有数字必须是公式**,不能是 Python 算出来的硬编码。这样你打开 Excel 改一个 assumption,全模型自动更新。

> 例外:本机没装 LibreOffice 时,用 **Python mirror** 替代 — 即在写 Excel 之前在 Python 里把每条公式预期值算一遍,验证零除零 / 无穷大 / `#REF!`。本指南示例的茅台 DCF 就走的这条路(307 个公式 mirror 全过)。

### 6. 中国市场 patch 是怎么工作的

这是 **plugin 化扩展** 的范例,值得单独讲:

```
用户:「帮我给 600519 做 DCF」

↓ Claude 看到 "600519" + "DCF"
↓ description 关键词匹配:
  - dcf-model(关键词:DCF / valuation / intrinsic value)
  - china-market-context(关键词:6 位 ticker / .SH / 茅台 …)

↓ 两个 skill 同时 load 进 system context

↓ dcf-model 走到 Step 1「取数」:
  - 原版会去 Daloopa MCP
  - china-market-context 里有一张「数据源 routing 表」:
    Daloopa → china-market.get_financial_report
    SEC EDGAR → 巨潮资讯网

↓ Claude 自动改去 china-market MCP

↓ dcf-model 走到 Step 6「WACC」:
  - 原版默认 risk-free = US 10Y Treasury
  - china-market-context 强制:risk-free = 中国 10Y 国债 2.7%
  - 原版默认 ERP = 5%
  - china-market-context 强制:ERP = 6% (Damodaran China)
  - 原版默认 tax = 21%
  - china-market-context 强制:tax = 25%(CAS 法定)

↓ Excel 输出币种 CNY,披露文件引用「年报」(非 10-K)
```

**核心 idea**:不 fork 任何官方 skill,只是用**第二个 skill 注入上下文**,让上游 skill 在分支判断时走「中国线路」。

参考:[china-market-context SKILL.md](plugins/partner-built/china-market/skills/china-market-context/SKILL.md)

---

## 第四部分 · 快速参考表

### 投资者最常用 15 个 skill

| Skill | Command | 场景 | 重要度 |
|---|---|---|---|
| `dcf-model` | `/dcf` | 估值 | ★★★★★ |
| `comps-analysis` | `/comps` | 相对估值 | ★★★★★ |
| `earnings-analysis` | `/earnings` | 财报点评 | ★★★★★ |
| `earnings-preview` | `/earnings-preview` | 财报前预期 | ★★★★ |
| `model-update` | `/model-update` | 财报后更新模型 | ★★★★ |
| `3-statement-model` | `/3-statement-model` | 看三大报表 | ★★★★ |
| `initiating-coverage` | `/initiate` | 新公司深度研究 | ★★★★ |
| `sector-overview` | `/sector` | 行业研究 | ★★★★ |
| `idea-generation` | `/screen` | 选股 | ★★★ |
| `competitive-analysis` | `/competitive-analysis` | 找 peers | ★★★ |
| `morning-note` | `/morning-note` | 每日晨会 | ★★★ |
| `catalyst-calendar` | `/catalysts` | 事件日历 | ★★★ |
| `thesis-tracker` | `/thesis` | 持仓 thesis 维护 | ★★★ |
| `strip-profile` | `/one-pager` | 公司速览 | ★★★ |
| `audit-xls` | `/debug-model` | 审计 Excel | ★★ |

### A 股专用(china-market plugin)

| Skill / Tool | 类型 | 用途 |
|---|---|---|
| `china-market-context` | 自动触发 router skill | 注入 CNY / 中国 10Y / 申万 / 巨潮 等上下文 |
| `a-share-data` | 显式触发 data skill | MCP tool 速查 |
| `get_daily_bars` | MCP tool | 历史日线 |
| `get_realtime_quote` | MCP tool | 实时报价 |
| `get_financial_report` | MCP tool | 三大表 |
| `get_stock_notices` | MCP tool | 个股公告 |
| `get_stock_news` | MCP tool | 财经新闻 |
| `get_north_flow` | MCP tool | 北向资金 |
| `get_dragon_tiger` | MCP tool | 龙虎榜 |
| `get_stock_list` | MCP tool | A 股清单(选股用) |
| `get_market_context` | MCP tool | 市场常量(risk-free / ERP / tax) |

---

## 第五部分 · 一个完整示例(看完就会用)

> 假设你想分析 **600519 贵州茅台**,流程如下:

1. **新建一个 Claude Code 会话**,直接说:
   > 「帮我给 600519 做 DCF,Base case 默认」

2. Claude 自动触发:
   - `china-market-context`(因为「600519」匹配 6 位 ticker)
   - `dcf-model`(因为「DCF」匹配)

3. Claude 调 `china-market` MCP:
   - `get_market_context()` 拿到 risk-free=2.7% / ERP=6% / tax=25%
   - `get_financial_report("600519.SH", "income", "annual")` 拿 6 年利润表
   - `get_daily_bars(["600519.SH"], 3Y)` 拿日线(为算 beta)

4. Claude **暂停** 把 raw inputs 给你看,等你确认(skill 硬规定:不允许 end-to-end 一把梭)

5. 你说 OK,Claude 接着跑 Step 2-10,最后用 `openpyxl` 输出 [600519_DCF_Model.xlsx](plugins/partner-built/china-market/600519_DCF_Model_2026-05-21.xlsx)(双 sheet + 3 个 sensitivity 表 + 307 公式)

6. 你打开 Excel,改 B4 cell(1=Bear / 2=Base / 3=Bull),全模型自动切换情景

7. 看 [投资建议/茅台600519.md](投资建议/茅台600519.md) 那种总结,你心里就有数了

---

## 第六部分 · 进阶 · 自己改 skill

skill 是 markdown,直接编辑文件即可:

- 改方法论 → 编辑 `<skill-name>/SKILL.md` body
- 改触发关键词 → 编辑 frontmatter 的 `description`
- 加新 skill → 在 `<vertical>/skills/` 下新建目录 + `SKILL.md`,然后跑 [scripts/sync-agent-skills.py](scripts/sync-agent-skills.py) 同步到 agent bundle

例如:你的「我的茅台 thesis」可以写成一个私人 skill(`my-thesis-moutai`),让 Claude 每次提到茅台时自动加载你历年的判断笔记。

---

## 免责声明

本指南列出的所有 skill 都是 **draft analyst work product** 生成器(估值模型、研报草稿、IC memo …),**不构成投资建议**。最终判断和合规性由你自己负责。
