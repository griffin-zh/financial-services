# 04 · 插件与 Skill 体系

> 读完本章你会知道:一个插件由哪些零件组成,skill 和 command 有什么区别、怎么触发,数据连接器怎么接,以及 hook 挂点在哪。

## 4.1 一个 plugin 的解剖

不管是 vertical、agent 还是 partner,插件都由这几种零件构成:

| 零件 | 文件 | 作用 | frontmatter / 结构契约 |
|---|---|---|---|
| **插件元数据** | `.claude-plugin/plugin.json` | 声明 name / version / description / author | `version` 语义化,gate 更新投递 |
| **Skill** | `skills/<name>/SKILL.md` | 领域知识 + 方法论,Claude 按需自动调用 | frontmatter `name` + `description` |
| **Command** | `commands/<name>.md` | 用户显式触发的 slash 动作 | frontmatter `description` + `argument-hint` |
| **Connector** | `.mcp.json` | 把 Claude 接到外部数据(MCP server) | `mcpServers` 对象 |
| **Hook** | `hooks/hooks.json` | Claude Code 生命周期自动化挂点 | 数组(当前多为空 `[]`) |

一个真实的 `plugin.json`([financial-analysis](../plugins/vertical-plugins/financial-analysis/.claude-plugin/plugin.json)):

```json
{
  "name": "financial-analysis",
  "version": "0.1.0",
  "description": "Core financial modeling and analysis tools: DCF, comps, LBO, ...",
  "author": { "name": "Anthropic FSI" }
}
```

## 4.2 Skill vs Command:自动 vs 手动

这是初学者最容易混淆的一对概念:

|  | Skill | Command |
|---|---|---|
| 触发方式 | **自动**——Claude 判断当前任务匹配就调用 | **手动**——用户显式敲 `/plugin:command` |
| 触发依据 | frontmatter 的 `description`(写清"什么时候用") | 用户主动调用 |
| 承载 | 详细方法论、约束、步骤 | 一个具体动作的入口(常引用某个 skill) |
| 例子 | `dcf-model`、`comps-analysis`、`earnings-analysis` | `/dcf`、`/comps`、`/earnings` |

**关键点:skill 的 `description` 不是文档,是触发器**。看 [dcf-model/SKILL.md:3](../plugins/vertical-plugins/financial-analysis/skills/dcf-model/SKILL.md#L3) 的 description 结尾:

> "...**Use when** users need to value a company using DCF methodology, request intrinsic value analysis, or ask for detailed financial modeling..."

那句 "Use when …" 就是告诉 Claude 何时自动激活这个 skill。所以**写 skill 时,description 要把触发场景写全写准**,否则 skill 该触发时不触发、不该触发时乱触发。

Command 的调用语法是 `/<plugin>:<command>`(见 [CLAUDE.md:39](../CLAUDE.md#L39)),在会话里也常简写成 `/comps`、`/dcf`。

## 4.3 数据连接器(MCP Integrations)

所有第三方数据连接器**集中**在核心插件 `financial-analysis` 的 `.mcp.json`,其余插件共享(见 [README.md:117-119](../README.md#L117-L119))。11 个连接器全是远程 HTTP MCP([financial-analysis/.mcp.json](../plugins/vertical-plugins/financial-analysis/.mcp.json)):

```json
{
  "mcpServers": {
    "daloopa":    { "type": "http", "url": "https://mcp.daloopa.com/server/mcp" },
    "morningstar":{ "type": "http", "url": "https://mcp.morningstar.com/mcp" },
    "sp-global":  { "type": "http", "url": "https://kfinance.kensho.com/integrations/mcp" },
    "factset":    { "type": "http", "url": "https://mcp.factset.com/mcp" },
    "moodys":     { "type": "http", "url": "https://api.moodys.com/genai-ready-data/m1/mcp" },
    "...":        "..."
  }
}
```

完整 11 个:Daloopa、Morningstar、S&P Global(Kensho)、FactSet、Moody's、MT Newswires、Aiera、LSEG、PitchBook、Chronograph、Egnyte(见 [README.md:121-133](../README.md#L121-L133))。

三个要点:

1. **访问需订阅 / API key**——这些是各家商业数据服务,连接器只是"接线",不含凭证。
2. **软引用设计**——核心 skill(dcf-model / comps / earnings)以"if a fundamentals provider is available, use it"的方式软引用 MCP(见 [CLAUDE.md:102](../CLAUDE.md#L102)),所以接入新数据源(如 china-market)**无需 fork 任何官方 skill**。
3. **china-market 是特例**——它不在这份清单里,而是自建的 SSE MCP 服务(`{ "type": "sse", "url": "http://localhost:8080/sse" }`),因为官方连接器都不覆盖 A 股。详见 [06](./06-china-market代码走读.md)。

## 4.4 Hook 挂点(当前预留)

多个插件带 `hooks/hooks.json`,当前多为空数组 `[]`(如 financial-analysis、equity-research、investment-banking 等)。这是 Claude Code hook 的**现成挂点**——你想加"提交前自动跑某校验""生成文件后自动重命名"之类的自动化,就往对应插件的 `hooks/hooks.json` 里加。操作见 [08 第 8 条](./08-如何修改与演进.md)。

## 4.5 三类 plugin 的完整清单

**7 个 vertical**(源头,见 [marketplace.json:6-41](../.claude-plugin/marketplace.json#L6-L41)):
`financial-analysis`(核心)、`investment-banking`、`equity-research`、`private-equity`、`wealth-management`、`fund-admin`、`operations`。

**10 个 agent**(具名,见 [marketplace.json:42-91](../.claude-plugin/marketplace.json#L42-L91)):
`pitch-agent`、`market-researcher`、`earnings-reviewer`、`meeting-prep-agent`、`model-builder`、`gl-reconciler`、`kyc-screener`、`valuation-reviewer`、`month-end-closer`、`statement-auditor`。

**3 个 partner** + 1 个独立工具(见 [marketplace.json:92-111](../.claude-plugin/marketplace.json#L92-L111)):
`lseg`、`sp-global`、`china-market`;以及 `claude-for-msft-365-install`(独立 IT 工具)。

> 合计 21 个插件,全部登记在 [marketplace.json](../.claude-plugin/marketplace.json)。

## 4.6 Skill & Command 全表在哪查

README 里有按 vertical 折叠的完整 skill/command 对照表,**本书不重抄**——需要时直接查:

- financial-analysis:[README.md:162-181](../README.md#L162-L181)
- investment-banking:[README.md:183-198](../README.md#L183-L198)
- equity-research:[README.md:200-215](../README.md#L200-L215)
- private-equity:[README.md:217-233](../README.md#L217-L233)
- wealth-management:[README.md:235-247](../README.md#L235-L247)

## 4.7 安装与试用(建立"用户视角")

改之前,先以用户身份用一次,能帮你理解你在改什么(见 [README.md:57-76](../README.md#L57-L76)):

```bash
# 添加市场
claude plugin marketplace add anthropics/financial-services
# 先装核心(带所有连接器)
claude plugin install financial-analysis@claude-for-financial-services
# 再按需装具名 agent / 垂直
claude plugin install pitch-agent@claude-for-financial-services
claude plugin install equity-research@claude-for-financial-services
```

装完后:agent 出现在 Cowork dispatch,skill 相关时自动触发,command 随手可用。

---

**下一章** → [05-Managed-Agent与编排](./05-Managed-Agent与编排.md):看同一批 agent 换成"托管部署"形态时,多出来的 agent.yaml、子 agent、安全隔离是怎么回事。
