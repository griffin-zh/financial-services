---
name: data-source-postmortem
description: "china-market 数据源失败复盘 + 自净化 loop。触发词:「数据源失败复盘」「fallback 反思」「为什么又走 web」「哪个源老对不上」「数据源不稳」「更新数据源白名单」「router 调优」,或当你刚经历一次 china-market web_fallback / 双写分歧(confidence:low)/ 某源反复熔断,想把教训沉淀下来时。两个 mode:log(记一条失败事件到 failure_log.jsonl)和 reflect(读全量 log,归纳高频 pattern,产出对 router 配置 / web 白名单 / memory 的具体改进建议)。这是把「MCP 失败 → 靠 web 拿到有效数据」的经验持续净化成范式的机制。"
---

# 数据源失败复盘 + 自净化(data-source-postmortem)

把 china-market 每次数据获取失败 / 降级 / web-fetch 兜底沉淀成结构化 log,定期 reflect
归纳 pattern,反哺 `SourceRouter` 配置、`WEB_FALLBACK_WHITELIST.md` 白名单、user memory ——
形成「失败 → 沉淀 → 调优 → 更稳」闭环。这是用户「持续自我净化」诉求的落地。

Log 文件:`plugins/partner-built/china-market/data_cache/failure_log.jsonl`(一行一事件)。

---

## Mode 1 —— log(记录一次失败事件)

**何时触发**:你刚遇到以下任一情况,立即 append 一条 log:
- china-market tool 返回 `web_fallback: true`(结构化源全挂)
- 返回 `confidence: low`(双写分歧)
- 返回 `degraded: true`(降级到备源 / 单源 / stale)
- 你被迫走白名单 web-fetch 才拿到数据
- `get_source_health` 显示某源 circuit `open`(熔断)

**怎么记**:用 Bash append 一行 JSON(不要读取整个文件、不要用重量级工具):

```bash
echo '{"ts":"2026-07-12T18:45:00","tool":"get_daily_bars","symbol":"600519.SH","sources_tried":["akshare","baostock"],"symptom":"akshare proxy 拦截 eastmoney; baostock 单源服务","confidence":"single","final_channel_worked":"baostock","notes":"financial env 有 proxy, akshare 不通"}' >> "d:/work/study/financial-services/plugins/partner-built/china-market/data_cache/failure_log.jsonl"
```

字段约定:
- `ts`:ISO 时间戳
- `tool`:哪个 MCP tool
- `symbol`:标的(可空)
- `sources_tried`:尝试过的结构化源
- `symptom`:失败症状(网络/限流/空返回/接口失效/双写对不上)
- `confidence` / `discrepancy`:若双写分歧,记两源值
- `final_channel_worked`:最终哪条渠道拿到有效数据(某个源 / web 白名单某站点 / 未拿到)
- `notes`:环境/上下文备注

**记完**告诉 user 一句:已记录本次失败到 failure_log,可日后 reflect。

---

## Mode 2 —— reflect(归纳 pattern + 产出改进)

**何时触发**:user 显式要求复盘 / 定期净化,或 log 积累到一定量。

**步骤**:
1. 读 `data_cache/failure_log.jsonl`(全量,通常不大)。
2. 按维度归纳高频 pattern:
   - **哪个源最常失败** → 建议下调其在 router 里的优先级 / 或标记环境不适配(如 baostock socket 在某网络不通、akshare 在某 proxy 后不通)。
   - **哪类数据最常走 web 兜底** → 该数据类型的结构化覆盖不足,建议补源或明确它就走 web。
   - **双写分歧集中在哪些标的/字段** → 可能是某源口径 bug,调 `_compare_daily` 容差或换源。
   - **哪个 web 白名单站点最常救场** → 在 `WEB_FALLBACK_WHITELIST.md` 里把它提到前面;哪些站点从没用过 → 考虑删。
3. 产出**具体改进 diff**(不要泛泛而谈),落到三处:
   - **router 配置**(`mcp_server/config.yaml` 的 `router.*`:breaker_threshold / cooldown / retries / timeout;或 `sources.*.enabled` 开关顺序)。
   - **web 白名单**(`references/WEB_FALLBACK_WHITELIST.md` 增删/排序)。
   - **user memory**(把稳定结论写进 memory,如「baostock 在本网络 socket 不通,优先 akshare+tushare」)。
4. 把改进建议以 diff / 清单形式给 user 确认后再落地。

**reflect 输出模板**:
```
## 数据源复盘(基于 N 条 log,时间跨度 X)
### 高频 pattern
- akshare 失败 P 次,集中在 <环境/时段>,症状 <...>
- 双写分歧 Q 次,集中在 <标的/字段>
- web 兜底 R 次,救场站点 <...>
### 建议改进
1. [router] ...
2. [whitelist] ...
3. [memory] ...
```

---

## 与其它组件的联动

- 数据层:`get_source_health` 提供实时 circuit/成功率快照,reflect 时结合 log 一起看。
- 范式:改进反哺 `a-share-data` 的 Behavior contract 与 `WEB_FALLBACK_WHITELIST.md`。
- 记忆:稳定结论写进 user memory,下次跨会话仍生效。
