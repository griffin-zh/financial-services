---
name: cn-deep-research
description: "中文财经/监管领域深度调研的路由 skill。当用户要对 A 股公司、中国宏观或监管事项做多源、可核查的深度调研 —— 例如「帮我全面调研宁德时代的监管与业绩风险」「XX 公司尽调」「A股尽调」「监管尽调」「舆情+监管调研」「中文 deep research」—— 时触发。它把请求路由到 cn-deep-research workflow(内置 deep-research 的中文平行版)：检索锁定中文财经媒体+监管官方+券商研报域名，先调 china-market MCP 结构化工具再补定向 WebSearch。区别于内置 /deep-research(英文/美国区为主)。"
---

# 中文 Deep-Research 路由

用户要做**中文财经/监管深度调研**时，不要用内置 `deep-research`(检索偏英文/美国区)，改用
`cn-deep-research` workflow —— 它把检索导向中文财经媒体 + 监管官方域名，并优先用
`china-market` MCP 的结构化工具直连公告/披露/互动易/新闻。

## 触发后先澄清(2-3 个问题，除非用户已给全)

1. **标的**：具体 A 股公司/代码？还是宏观/主题(如"半导体设备国产替代")？
2. **时间窗**：关注最近多久(如近 1 年 / 2024 全年 / 某事件前后)？
3. **关注维度**：监管风险 / 业绩 / 舆情 / 财务质量 / 竞争格局 —— 侧重哪些？

## 调用

把澄清后的问题揉进一句话，作为 args 传给 workflow：

```
Workflow({ name: "cn-deep-research", args: "宁德时代 2024 监管问询与业绩风险，侧重商誉与关联交易" })
```

> 命名发现在会话启动时完成。若刚新建/编辑过脚本、本会话报 `Workflow "cn-deep-research" not found`，
> 改用绝对路径兜底(等价)：
> `Workflow({ scriptPath: "<repo>/.claude/workflows/cn-deep-research.js", args: "..." })`

workflow 内部四阶段：scope(中文五角度) → gather(MCP 结构化优先 + allowed_domains 定向检索) →
verify(按来源 tier 加权对抗核查) → synthesize(分级引用 + 口径声明的中文报告)。

## 前置条件

- `china-market` MCP 需 `connected`(`/mcp` 查)。未连时 workflow 仍能跑(退化为纯 web 检索)，
  但拿不到结构化公告/监管数据 —— 提醒用户先起服务(见 `financial-services/CLAUDE.md` 运行说明)。
- 港股 `.HK` MCP 不覆盖，workflow 会退到白名单 web-fetch。

## 不要用它的场景

- 单点数据查询(拉行情/某个财报数字) → 用 `a-share-data` skill 直接调 MCP，别起整个 workflow。
- 英文/美股/国际主题调研 → 用内置 `deep-research`。
