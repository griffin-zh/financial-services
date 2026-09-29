# 10 · 移植到非 Claude 运行时(DeepSeek / oh-my-pi 等)

> 这个仓库是 Anthropic 针对**自家闭源模型 + 自家运行时(Claude Code / Cowork / Managed Agents API)** 设计的。它的 markdown skill 之所以能这么薄,是因为把"确定性 / 复现性"外包给了那个很强的闭源模型。一旦你要把它跑在 **DeepSeek(开源模型)+ oh-my-pi(第三方 agent 运行时)** 上,复现性就没有免费午餐了——本章讲怎么在 **指令遵循 / tool-use / 结构化输出 / 约束解码** 四个维度把它对齐(某些维度甚至能反超)Anthropic 的水平,并给出**从格式转换到工具循环再到安全护栏**的可照抄落地细节。
>
> 前置阅读:[03 核心设计理念](./03-核心设计理念.md)、[05 Managed Agent 与编排](./05-Managed-Agent与编排.md)(安全隔离 + `output_schema` 范式)、[06 china-market 代码走读](./06-china-market代码走读.md)(唯一确定性代码层)。

## 10.1 先分清两个 gap

移植失败通常是因为把两件事混为一谈。请始终分开处理:

| gap | 是什么 | 补法 |
|---|---|---|
| **模型 gap** | DeepSeek 的指令遵循 / tool-use / 结构化能力 ≠ Claude | prompt 改写 + 约束解码 + eval 回归**可逼近**;指令遵循是最难的一维 |
| **运行时 gap** | oh-my-pi 没有 Claude Code 的 **skill 自动激活**、没有 **Managed Agents API**、没有 **version-gate** | 靠**重建 3 个机制**补齐(见 [10.9](#109-运行时移植直接复用-vs-必须重建)) |

> 关键事实:**MCP 这层已经打通。** CLAUDE.md 里已经把 oh-my-pi 定义为 china-market MCP 的下游 client(「Claude Code 与下游 oh-my-pi 都作为 client 连同一个运行实例」,见 [CLAUDE.md](../CLAUDE.md))。所以 `china-market` + 11 个连接器(见 [04](./04-插件与Skill体系.md) 4.3)几乎零改动就能在 oh-my-pi 上复用——移植的重点不在"取数",在**工具怎么被 DeepSeek 正确调用**、"输出的确定性"和"运行时机制"。

## 10.2 一个反转洞见:自托管开源模型能在"约束解码"上反超 Claude API

这是整章最重要的一句话:

> **Claude API 不给你 grammar 级约束**——它的结构化输出靠"模型足够听话"。而你**自托管 DeepSeek** 时,可以用约束解码(guided decoding)在**解码器层面禁止模型生成任何非法输出**。

也就是说,在**结构化输出**这一维,你不需要"追平"Claude,可以直接做得**更硬**:100% 合规是**语法保证**的,而不是概率保证的。这是开源模型 + 自托管相对闭源 API 的真实优势,后面 [10.4](#104-四维对齐核心) 和 [10.8](#108-结构化输出三条路线) 都会用到它。

## 10.3 两个决定性前提

方案随这两点分叉,动手前先对号入座:

1. **DeepSeek 怎么跑?**
   - **自托管**(vLLM / SGLang)→ 拿得到**约束解码**,这是最强的确定性武器(见 [10.8](#108-结构化输出三条路线) 路线一);
   - **只用官方 API**(OpenAI 兼容)→ 只能用 JSON mode / 伪工具法 + 校验重问,拿不到 grammar 级保证。
2. **模型档位**:取数 / 工具 / 结构化产出用 **V3 档**(`deepseek-chat`,function calling 更稳);多步硬推理用 **R1 / reasoning 档**(`deepseek-reasoner` **不支持 tool call**,切勿用它跑工具环)。二者可在编排里按步骤切换。

> ⚠️ DeepSeek 各版本能力(尤其 R1 是否稳定支持 function calling)迭代很快,以你部署时的**当前版本文档为准**,别照抄本章的档位假设。

## 10.4 四维对齐(核心)

| 维度 | Claude 靠什么 | DeepSeek 差距 | 对齐 / 反超手段 | 复用仓库什么 |
|---|---|---|---|---|
| **指令遵循** | 强闭源模型 + Claude 调过的 prompt | 长指令散文、隐式风格、格式纪律不同;**Claude 调的 prompt 在 DeepSeek 上未必最优** | 隐式指令**显式化+分解**;`temperature=0`;硬步用 R1;**用小标注集针对 DeepSeek 重写/编译 prompt**(DSPy 式),别照抄;行为纠偏见 [10.7](#107-驯化-deepseek-的工具行为prompt-对抗) | `agents/<slug>.md` 提示词当模板改写;`steering-examples.json` 当 few-shot 锚点 |
| **tool-use** | 极可靠 tool-calling + MCP | 并行 / 强制调用 / 参数合法性不如 Claude 稳 | 必须调工具时**强制 `tool_choice`**;执行前**用 JSON Schema 校验参数**,不合法就 reask;**工具白名单**;重试+熔断。**格式转换见 [10.5](#105-工具层适配mcp--deepseek-function-calling)、循环与并行见 [10.6](#106-健壮的-tool-use-循环openai-兼容形态)、行为纠偏见 [10.7](#107-驯化-deepseek-的工具行为prompt-对抗)** | china-market MCP + `.mcp.json` 连接器(直接接);[orchestrate.py](../scripts/orchestrate.py) 的 allowlist+schema 缓解;熔断思路见 [sources.py:394](../plugins/partner-built/china-market/mcp_server/sources.py#L394) |
| **结构化输出** | tool-use schema 收口 | API 的 `json_object` 只保证"合法 JSON",**不强制 schema** | 有 strict json_schema 就开;**自托管→约束解码直接喂 schema(100% 合规)**;否则伪工具法 / Instructor 式 **validate+reask 循环**(见 [10.8](#108-结构化输出三条路线)) | **`reader.yaml` 的 `output_schema` 当唯一真源**(见 [05](./05-Managed-Agent与编排.md) 5.4);把 [validate.py](../scripts/validate.py) **普及到所有产结构化产物的 skill** |
| **约束解码** | ❌ Claude API **不提供** | ✅ **自托管才有,是你的王牌** | **SGLang / vLLM + XGrammar / Outlines**,把 `output_schema` 直接作 `guided_json` / grammar 喂进去 | 同上,`output_schema` 直接复用为 grammar 源 |

**把"结构化输出"和"约束解码"两行连起来看**:Anthropic 靠"模型足够听话",你靠"**解码器根本不许它不听话**"。只要你控制推理,输出契约可以焊死。

## 10.5 工具层适配:MCP → DeepSeek function calling

MCP 这层协议已打通,但 **oh-my-pi 上要把 MCP 工具定义翻译成 DeepSeek(OpenAI 兼容)的 `tools` 格式**,模型才认得。这一步平台无关,是移植的第一块地基。

**格式转换要点**(MCP `input_schema` → OpenAI `{"type":"function","function":{name,description,parameters}}`):

| 要点 | 为什么 |
|---|---|
| `$defs` / 嵌套引用**完全展开**,嵌套**约束在 3 层以内** | DeepSeek 对复杂嵌套的稳定性弱于 Claude,拍平更可靠 |
| `server_name` 里的 `-` 转 `_`,来源在 `description` 里标注 | `-` 不是合法函数名字符;标源便于回映射到 MCP 调用 |
| 每个参数 `description` 一句话讲清 + 约束"勿臆造字段" | DeepSeek 对参数 `description` 敏感,含糊即幻觉 |
| 工具总数 ≤15、每条 `description` ≤200 字符 | 冗余描述增加选择困惑与延迟;china-market 的 12 个 tool 天然满足 |

### 骨架 · MCP 工具列表 → OpenAI tools 数组

> 移植方在自己仓库里写的适配层,**不入** financial-services 本仓(见 [09](./09-验证约定与常见陷阱.md) 单一源约定)。

```python
# 遍历 MCP client 拿到的工具列表,产出 DeepSeek 认得的 tools 数组
def mcp_to_openai_tools(mcp_tools, server_name="china-market"):
    tools = []
    for t in mcp_tools:                       # china-market 暴露 12 个:get_daily_bars / get_disclosure_search / …
        schema = deref_and_flatten(t.inputSchema, max_depth=3)  # 展开 $defs,拍平到 ≤3 层
        tools.append({
            "type": "function",
            "function": {
                "name": t.name.replace("-", "_"),                # 合法函数名
                "description": f"[{server_name}] {t.description}"[:200],  # 标源 + 控长
                "parameters": schema,
            },
        })
    return tools                              # 顺序固定 → 利于前缀缓存(见 10.10)
```

> **注意**:工具集若**每轮动态变化**会击穿 DeepSeek 前缀缓存(见 [10.10](#1010-长上下文成本与安全的暗坑))。除非确实需要按权限增减,否则让 `tools` 数组保持稳定顺序。

### MCP 动态能力 ≠ 静态函数列表

MCP 不只是工具列表,还有 Claude 侧"免费"的两类能力,DeepSeek 无等价物,需手动补:

- **resources**:Claude 能主动 `read_resource` 拉文件 / 库记录。DeepSeek 没有,需在工具集外**设计"拉取式"工具**(如 `get_file_content(uri)`),并在 prompt 引导按需调用。
- **prompt 模板**:MCP 服务可提供预设提示词。迁移时手动提取,**融入 System Prompt 或工具描述**,否则模型丢掉"专家角色"。

## 10.6 健壮的 tool-use 循环(OpenAI 兼容形态)

⚠️ 仓库里的 [orchestrate.py](../scripts/orchestrate.py) 是 **Claude / `anthropic` 形态**(SSE `steer` 做 handoff),**不是** OpenAI `tool_calls` 形态。oh-my-pi 上要另写一个 **OpenAI 兼容循环**:用 OpenAI Python SDK 把 `base_url` 指向 DeepSeek 端点,`model="deepseek-chat"`,它会自动处理 `tool_calls`。

**循环契约**(承接 10.4 tool-use 行):

1. 送带 `tools` 定义的消息给 DeepSeek。
2. 响应含 `tool_calls`:逐个解析并执行(MCP 工具经 MCP client 回调),结果以 `role:"tool"` + 对应 `tool_call_id` 追加进消息列表,再次请求让模型综合。
3. 无 `tool_calls`:直接输出 `content`。

**并行 vs 顺序**:DeepSeek 单响应可返回多个 `tool_calls`,但稳定性弱于 Claude——有时会依赖一个**还没执行**的前置结果。对策三选一:① prompt 约束"并行调用之间不得有依赖,有依赖必须分步";② 客户端检查参数是否引用未执行结果,是则拒绝并让模型重规划;③ 保守方案:强制"每次只调一个",由客户端循环(增加轮次,但完全避免并行幻觉)。

### 骨架 · 最小工具循环(参数校验 + 白名单 + 熔断)

```python
from openai import OpenAI
import json, jsonschema

client = OpenAI(base_url="https://api.deepseek.com", api_key="…")  # 或自托管 SGLang/vLLM 端点
ALLOWED = {"get_daily_bars", "get_realtime_quote", "get_financial_report", …}  # 工具白名单

def run_turn(messages, tools, param_schemas, call_mcp, max_rounds=5):
    for _ in range(max_rounds):                          # 最大轮次,防死循环
        resp = client.chat.completions.create(
            model="deepseek-chat", temperature=0,        # 硬步骤要确定性
            messages=messages, tools=tools,
            # 必须调工具时:tool_choice={"type":"function","function":{"name": "…"}}
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:                            # 无工具调用 → 收尾
            return msg.content
        messages.append(msg)
        for tc in msg.tool_calls:
            name, args = tc.function.name, json.loads(tc.function.arguments)
            try:
                if name not in ALLOWED:                   # 白名单
                    raise ValueError(f"tool {name} not allowed")
                jsonschema.validate(args, param_schemas[name])  # 参数合法性,不合法 → reask
                result = call_mcp(name, args)             # 回映射到 MCP 调用
            except Exception as e:
                result = {"error": str(e)}                # 结构化 error,引导模型别反复重试
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False)})
    return {"error": "max tool rounds exceeded"}          # 熔断
```

要点:**强制 `tool_choice`** 逼它在该调时调;**执行前 schema 校验参数**,不合法就把 error 回给模型 reask;**结构化 error** + prompt 指令("临时错误可调参重试一次,致命错误解释并给替代方案,勿反复重试");**最大轮次**熔断。

## 10.7 驯化 DeepSeek 的工具行为(prompt 对抗)

DeepSeek 与 Claude 在工具使用上有细微"个性",用对抗指令针对性矫正——这直接强化 10.4 的**指令遵循**与 **tool-use** 两维:

| 倾向 | 问题 | 矫正 |
|---|---|---|
| 过度调用 | 闲聊也尝试调工具 | System Prompt:"仅在需实时数据 / 外部操作时调用;常识、静态知识、闲聊直接回答" |
| 参数幻觉 | 填未定义字段(如 `lang:"zh"`) | 参数 `description` 加"只允许使用定义的字段,不要添加额外参数" |
| 过早放弃 | 出错即告失败不重试 | prompt:"临时性 error 可调参重试一次;致命错误请解释并建议替代方案" |
| 意图混淆 | 相近工具(如 `get_stock_news` vs `get_stock_notices`)选择摇摆 | `description` 首句写排他性:"本函数仅用于…不要用于…" |

**推荐的 System Prompt 骨架**(克制、带排他说明):

```
你是一个智能助手,可调用以下函数完成用户请求。
- 只有在需要获取外部信息或执行操作时才调用函数;常识 / 闲聊直接回答。
- 严格按定义的参数要求,不要臆造参数。
- 函数结果返回后,基于结果用自然语言回答。
可用函数:{tool_descriptions}
```

**快捷通道**(也是成本手段,见 10.10):对可能不需要工具的请求,**先发一条不带 `tools` 的请求判意图**,确需工具再发带 `tools` 的请求,省去无谓的首 token 延迟。

**回归**:用 10–20 条边界 case(该调 / 不该调各半)测模型行为,再微调对抗指令——这直接接到 [10.13](#1013-骨架--最小-eval-harness跨模型--跨版本回归) 的 eval harness。

## 10.8 结构化输出:三条路线

Claude 的 `tool_use` 常被用来做"结构化提取"。DeepSeek 上**按部署形态分三条路线**,三条都指向**同一份** `output_schema`(仓库里的唯一真源,勿另写):

**路线一 · 自托管 → 约束解码(首选,王牌)**——`guided_json` / grammar 在解码层直接吃 schema,语法级 100% 合规。复用仓库现成 schema(以 `reader.yaml` 的 GL 对账破口结构为例,见 [reader.yaml:35-58](../managed-agent-cookbooks/gl-reconciler/subagents/reader.yaml#L35-L58)):

```python
import json, yaml, jsonschema, requests

# 1) 从 cookbook 的 output_schema 直接取 schema(唯一真源,勿另写一份)
schema = yaml.safe_load(open("subagents/reader.yaml"))["output_schema"]

# 2) 自托管推理:把 schema 作为 guided_json 喂进去 —— 语法上不可能产出非法结构
resp = requests.post("http://localhost:30000/v1/chat/completions", json={
    "model": "deepseek",
    "temperature": 0,
    "messages": [
        {"role": "system", "content": open("agents/gl-reconciler.md").read()},
        {"role": "user",   "content": untrusted_statement_text},
    ],
    "response_format": {"type": "json_schema", "json_schema": {"schema": schema}},
    # vLLM/SGLang 亦可用 extra_body={"guided_json": schema} / {"guided_decoding_backend": "xgrammar"}
}).json()

out = json.loads(resp["choices"][0]["message"]["content"])

# 3) 双保险:即便走 API(无约束解码),也用仓库同一套 jsonschema 后置校验(见 scripts/validate.py)
jsonschema.validate(out, schema)   # 不合法 → reask,绝不把自由文本放行
```

**路线二 · API-only → 伪工具法**——拿不到约束解码时,比 `response_format` 更稳:定义一个 `submit_final_answer` 伪工具,System Prompt 强制"完成所有步骤后**必须调用它提交**,不要在 `content` 直接输出最终答案"。客户端拦截这个特殊调用、把参数当最终输出。它绕过 DeepSeek 原生 JSON mode 对复杂嵌套的"自由发挥",输出严格受 schema 约束:

```json
{"type": "function", "function": {
  "name": "submit_final_answer",
  "description": "完成所有任务后,必须通过此函数提交最终答案。",
  "parameters": {"type": "object",
    "properties": {"summary": {"type": "string"}, "data": { /* 你的 output_schema */ }},
    "required": ["summary", "data"]}}}
```

**路线三 · 兜底解析器**——小概率模型仍在 `content` 直出 JSON 不调函数。加回退逻辑:① 检查有无 `tool_calls`;② 无则从 `content` 抽 JSON 块尝试解析;③ 解析失败,发一条系统消息"你必须调用 `submit_final_answer` 提交最终答案,请重试"(重试 1 次)。避免用户拿到纯文本而丢结构化数据。

## 10.9 运行时移植:直接复用 vs 必须重建

**可直接复用(内容 / 协议与模型无关):**

- **MCP servers**:china-market、11 个连接器——MCP 是开放协议,oh-my-pi 已在连;
- **skill 的 markdown 内容 + `references/`**:当作可注入的上下文 / 模板;
- **`output_schema` / `validate.py`**:当作跨模型通用的输出契约(见 [05](./05-Managed-Agent与编排.md) 5.4、[07](./07-工程化与工具链.md) 7.2);
- **安全隔离范式**:UNTRUSTED reader、最小权限、schema 收口、handoff allowlist——与模型无关,照搬(见 [09](./09-验证约定与常见陷阱.md) 9.3)。

**必须重建(Claude 运行时特有,oh-my-pi 上没有):**

1. **skill 自动激活**:Claude Code 靠 `SKILL.md` 的 `description`(「Use when…」)决定何时注入(见 [04](./04-插件与Skill体系.md) 4.2)。oh-my-pi 上要自建一个**路由器**:读全部 skill 的 `description`,用关键词 / embedding 检索选中并注入。仓库里的 `china-market-context`(router skill,见 [06](./06-china-market代码走读.md) 6.9)就是现成范式,照它做。
2. **Managed Agents 编排**:`/v1/agents` + cookbook 部署换成你自己的 orchestrator;[orchestrate.py](../scripts/orchestrate.py) 是参考骨架(handoff 循环 + prompt-injection 缓解),保留它的安全边界(见 [05](./05-Managed-Agent与编排.md) 5.6)。
3. **MCP 动态能力的降级**:resources / prompt 模板 / 动态工具列表在 DeepSeek 上无等价(见 [10.5](#105-工具层适配mcp--deepseek-function-calling) 子块),要用"拉取式"工具 + 融入 system prompt 补齐;动态工具列表还要和前缀缓存做取舍(见 [10.10](#1010-长上下文成本与安全的暗坑))。
4. **version-gate / 分发机制**:脱离 Claude 分发体系后基本无意义——`version_bump.py`、marketplace 那套可丢;`sync-agent-skills.py` 若你还保留 bundle 结构就留着做卫生(见 [07](./07-工程化与工具链.md) 7.2)。

## 10.10 长上下文、成本与安全的暗坑

除了工具格式和 prompt,还有几类工程陷阱容易在上线后才暴露:

| 暗坑 | 说明 | 对策 |
|---|---|---|
| **长上下文失忆** | DeepSeek 128K(vs Claude 200K),多轮密集调用后早期系统指令被挤出注意力,开始忽略规则 | 每 ~3 轮插一条简短 `role:user` "心跳"复述核心约束(UI 可隐藏);接近上限时用廉价模型摘要历史、为工具结果保留关键数据 |
| **前缀缓存未命中** | system + tools 每轮重发,烧输入 token / 首 token 延迟 | 固定 `messages[0]` 与 `tools` 列表顺序不变 → 命中 DeepSeek 前缀缓存;动态工具集会击穿(权衡是否每轮重建) |
| **多轮调用爆炸** | 一个问题触发 3~5 次模型调用(思考→调工具→整合→再调→总结),总延迟放大 | 快捷通道:先发不带 tools 的请求判意图,需要工具再带 tools 发(见 [10.7](#107-驯化-deepseek-的工具行为prompt-对抗)) |
| **重试烧钱** | 无限循环重试成本失控 | 单次用户交互设**最大 token 预算**(如 50K),超出降级为友好提示 |
| **权限失守** | MCP 的身份权限没了,工具执行器直接暴露给 LLM | 参数**白名单 + 校验**(`file_path` 限定目录,防路径遍历);高风险操作(删 / 转账 / 发信)**人工二次确认**插桩;**prompt 注入防御**在执行层做语义检查,可疑即阻断 + 记录(呼应 [orchestrate.py](../scripts/orchestrate.py) 的注入缓解与 [09](./09-验证约定与常见陷阱.md) 9.3 安全隔离) |

## 10.11 推荐落地栈(自托管路线,最大还原性)

```
推理:   SGLang(或 vLLM)托管 DeepSeek —— V3 档(工具/结构化)+ R1 档(硬推理)
约束:   XGrammar / Outlines,guided_json 直接吃 output_schema
结构化: 自托管走约束解码,API 走伪工具法 + validate 重问;所有产结构化产物的 skill 都配 schema
工具:   MCP 直连 china-market/连接器;MCP→tools 转换(-→_ 命名 + schema 展平);强制 tool_choice + 参数校验 + 重试熔断
路由:   自建 skill router(embedding 检索 description),复刻自动激活
性能:   前缀缓存(system/tools 固定顺序)+ 快捷通道(先无 tools 判意图)+ 单交互 token 预算熔断
护栏:   参数白名单 / 路径校验 / 高风险人工确认 / 注入执行层检查;promptfoo/braintrust 式 eval,golden set 跨模型回归进 CI
编排:   以 orchestrate.py 为蓝本自研,保留 reader 隔离 + allowlist handoff
```

## 10.12 迁移 checklist(务实顺序)

1. **先接 MCP**:确认 oh-my-pi 连上 china-market + 连接器、tool-use 通(与模型能力无关,先排除运行时问题)。oh-my-pi 已是 china-market client,重点验证 11 个连接器。
2. **做工具格式转换**:MCP 工具列表 → OpenAI `tools` 数组(`-`→`_`、schema 展平 ≤3 层、标源),接上健壮工具循环(见 [10.5](#105-工具层适配mcp--deepseek-function-calling)/[10.6](#106-健壮的-tool-use-循环openai-兼容形态))。
3. **给关键 skill 补 schema**:把散文里"该确定的输出"抽成 `output_schema` + 约束解码 / 伪工具法 / validate —— **这一步单独就能消掉 80% 的"跨模型不稳定"焦虑**。
4. **搭最小 eval harness**:每个高价值 skill 选 5–10 个 golden case(含"不该调工具"的边界例),跨 DeepSeek 版本回归。**没有它,你无法量化"对齐到什么程度"**。
5. **按 eval 结果做 prompt 改写 / 编译 / 行为纠偏**:哪个 skill 掉分就针对 DeepSeek 重写(见 [10.7](#107-驯化-deepseek-的工具行为prompt-对抗)),而不是全量手调。
6. **重建 skill router + orchestrator**,保留安全隔离。
7. **加安全护栏 + 成本闸**:参数白名单 / 路径校验 / 高风险人工确认 / 注入执行层检查;前缀缓存 + 快捷通道 + 单交互 token 上限(见 [10.10](#1010-长上下文成本与安全的暗坑))。

## 10.13 骨架 · 最小 eval harness(跨模型 / 跨版本回归)

把"不稳定"变成可观测——golden set + 断言,接进 CI 当"语义层的 [check.py](../scripts/check.py)":

```python
# evals/run.py —— 移植方自建,不入 financial-services 本仓(见 09 单一源约定)
import json, jsonschema, yaml
from your_runtime import run_skill          # oh-my-pi 里跑一个 skill 的封装

CASES = [                                   # 每个高价值 skill 选 5–10 个
    {"skill": "gl-reconciler", "input": "…对账单文本…",
     "must_have": {"status": "breaks_found"}, "min_breaks": 1},
]
schema = yaml.safe_load(open("subagents/reader.yaml"))["output_schema"]

fails = []
for c in CASES:
    out = run_skill(c["skill"], c["input"], model="deepseek-v3", temperature=0)
    try:
        jsonschema.validate(out, schema)                      # ① 结构必须合规
        assert out["status"] == c["must_have"]["status"]      # ② 关键字段命中
        assert len(out.get("breaks", [])) >= c["min_breaks"]  # ③ 语义要点覆盖
    except Exception as e:
        fails.append((c["skill"], str(e)))

print(f"PASS {len(CASES)-len(fails)}/{len(CASES)}")
if fails:                                    # CI 里 exit 1,漂移即拦
    for s, e in fails: print("FAIL", s, e)
    raise SystemExit(1)
```

换模型 / 换版本只改 `model=`,同一套 CASES 重跑——这是**唯一**能回答"我离 Anthropic 水平还差多少"的方法。

> 以上所有骨架(转换器 / 工具循环 / 约束解码 / eval)都是**移植方 / 部署方**在自己仓库里写的适配代码,**不属于** financial-services 本体,不要提交回本仓库(见 [09](./09-验证约定与常见陷阱.md) 单一源约定)。

## 10.14 一句话结论

追平 Anthropic 不是"把 DeepSeek 调得像 Claude"。**指令遵循**靠改写 + 编译 + eval 逼近(最难,靠 harness 量化);**tool-use / 结构化 / 约束解码**这三维,自托管 DeepSeek 反而握有 Claude API 都没有的王牌(grammar 级约束),把**输出契约用约束解码焊死**就能不输甚至更硬。真正要新建的,是仓库里被 Claude 运行时"免费提供"的三件事:**skill 路由、编排器、eval 护栏**——落地细节(格式转换 / 工具循环 / 行为纠偏 / 暗坑)见 [10.5](#105-工具层适配mcp--deepseek-function-calling)–[10.10](#1010-长上下文成本与安全的暗坑)。

---

**回到** → [指南书导读](./README.md) ｜ 上游背景见 [03 核心设计理念](./03-核心设计理念.md)、[05 Managed Agent 与编排](./05-Managed-Agent与编排.md)
