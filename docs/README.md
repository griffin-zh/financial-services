# financial-services 专业指南书

> 一份面向"深入理解 + 未来演进"的中文说明书,配套 `anthropics/financial-services` 仓库。
> 全书基于对仓库源码的逐行核对撰写,所有 `文件:行号` 引用均指向仓库内真实位置。

## 一句话认识这个仓库

`financial-services` **不是一个可运行的金融后端应用**,而是 **Anthropic 官方的「Claude for Financial Services」参考资产仓库**:一套 file-based 的 **Claude 插件(Cowork / Claude Code)+ Claude Managed Agent 部署模板**,面向投行、股票研究、私募股权、财富管理、基金行政等 FSI 场景。

它的核心是**约定与纪律**,不是代码:280 个 `.md`、44 个 `.json`、41 个 `.yaml`,而真正会运行的代码只有一处——`china-market` 的 A 股数据 MCP 服务(约 1100 行 Python)。理解这个仓库,本质上是理解四条主线:

1. **一源两包装**——同一个 agent 既是插件,又是 Managed Agent,共享同一份系统提示词;
2. **单一源同步**——skill 的权威源只在 `vertical-plugins/`,agent bundle 里的是禁止手改的副本;
3. **版本门控**——插件 `version` 决定已安装用户能否收到更新,由 git hook + CI 自动维护;
4. **分层降级 + 依赖倒置**——china-market MCP 用抽象基类、工厂、熔断器写出可平滑演进的数据层。

## 怎么读这本书

按你的目的选一条线:

- **新手 / 想全面理解** → 顺序读 01 → 02 → 03 → 04 → 05 → 06 → 07,最后看 09。
- **想改造 / 演进这个仓库** → 先读 03(设计理念,全书的钥匙),再直接跳 08(操作手册),遇到细节回查对应章节。
- **只关心 A 股数据代码(china-market)** → 03 的「分层降级 + 依赖倒置」一节 + 06(代码走读)+ 08 的第 5/6/7 条。
- **想移植到别的模型 / agent(如 DeepSeek + oh-my-pi)** → 03(理念)+ 05(隔离与 schema)+ 06(唯一确定性代码)打底,再读 10(移植对齐)。

## 目录

| 章节 | 主题 | 一句话摘要 |
|---|---|---|
| [01-项目全景与定位](./01-项目全景与定位.md) | 是什么 / 不是什么 | FSI 插件市场 + Managed Agent 模板;为何"没有真实交易引擎" |
| [02-仓库结构与目录地图](./02-仓库结构与目录地图.md) | 目录逐条注解 | 三分法布局 + "我要改 X 该去哪"路径速查表 |
| [03-核心设计理念](./03-核心设计理念.md) | 全书的钥匙 | 一源两包装、单一源同步、版本门控、file-based |
| [04-插件与Skill体系](./04-插件与Skill体系.md) | 插件怎么组成 | plugin / skill / command / connector / hook 的构成与触发 |
| [05-Managed-Agent与编排](./05-Managed-Agent与编排.md) | 托管部署形态 | agent.yaml、depth-1 子 agent、安全隔离、部署脚本 |
| [06-china-market代码走读](./06-china-market代码走读.md) | 唯一真实代码 · 深入 | 适配层 / 路由层 / 缓存层 / MCP 服务逐层拆解 |
| [07-工程化与工具链](./07-工程化与工具链.md) | 脚本、CI、测试 | check.py / sync / version-bump / deploy 与三条 CI |
| [08-如何修改与演进(操作手册)](./08-如何修改与演进.md) | 面向未来 · 核心 | 9 类演进场景:改哪些文件 → 跑哪些脚本 → 怎么验证 |
| [09-验证、约定与常见陷阱](./09-验证约定与常见陷阱.md) | 别踩坑 | 提交前 checklist + drift / stdout / 币种 / license 红线 |
| [10-移植到非Claude运行时](./10-移植到非Claude运行时.md) | 进阶 · 跨模型 | 移到 DeepSeek + oh-my-pi:指令/tool-use/结构化/约束解码如何对齐甚至反超 |

## 重要免责边界(务必先知道)

仓库里所有 agent **只产出草稿供合格专业人士复核**——它们不做投资建议、不执行交易、不绑定风险、不过账、不审批开户,每个输出都停在"待人签字"这一步(见 [README.md:7-8](../README.md#L7-L8))。这正是**为什么仓库里找不到真实的交易 / 清算 / 支付引擎代码**——这是有意的产品边界,不是缺失。理解这一点,能帮你在演进时守住同一条安全线。

## 与本书配套的权威源文件

本书是"导读 + 结构化讲解",不替代源文件。随时对照这些权威文档:

- 仓库总说明:[../README.md](../README.md)、[../CLAUDE.md](../CLAUDE.md)、[../user_guide.md](../user_guide.md)
- 插件注册中心:[../.claude-plugin/marketplace.json](../.claude-plugin/marketplace.json)
- china-market 架构蓝图:[../plugins/partner-built/china-market/references/DATA_SOURCES.md](../plugins/partner-built/china-market/references/DATA_SOURCES.md)
