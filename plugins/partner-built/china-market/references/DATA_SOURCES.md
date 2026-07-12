# china-market 数据源选型 + 架构蓝图

本文件回答三件事:①稳定平面 baostock vs Tushare Pro 怎么选;②实时/稳定两平面怎么分;
③未来 100 用户产品化怎么演进。配套代码在 `mcp_server/{sources,cache}.py`,范式在
`a-share-data` skill + `WEB_FALLBACK_WHITELIST.md`。

---

## 0. 本次实测的真实发现(honest,直接影响选型)

搭建时在两个 conda env 各测了一遍,结果**互补**:

| env | Python | akshare | baostock | 结论 |
|---|---|---|---|---|
| quant | 3.9.25 | ✅ 通(直连 HTTP) | ❌ socket 10002007 不可达 | 装不了 mcp(需 ≥3.10) |
| financial | 3.11.15 | ❌ proxy 拦 eastmoney | ✅ login success + 拉到数据 | **MCP server 的家**(有 mcp) |

**没有任何一个 env 两源同时可用**。这不是 bug,正是本项目要解决的现实:任一源都可能因
网络/proxy/socket 策略在某环境不可达。`SourceRouter` 在两种情况下都正确降级到可用源 ——
这就是多源 + 动态路由的价值证明。

**部署结论**:
- MCP server 跑在 **`financial` env**(Python 3.11,`mcp` 只能装这)。`plugin.json` 已指向它。
- baostock 走私有 TCP socket(端口 10030),部分网络/sandbox 会拦;akshare 走 HTTP 更易穿透
  但会被 proxy 影响。**二者失败模式不同,恰好互补** → 双写交叉的意义。
- tushare 走 HTTPS REST + token,穿透性最好但需 token + 积分,当前默认关闭。

---

## 1. baostock vs Tushare Pro 充分对比

| 维度 | baostock | Tushare Pro |
|---|---|---|
| 费用 | 完全免费 | 积分制(注册送基础分,高级接口需攒/充分) |
| 注册 | 免注册,`bs.login()` 即用 | 需注册取 token |
| 数据来源 | 交易所权威源 | 聚合 + 规范化 |
| 传输 | 私有 TCP socket(易被网络策略拦) | HTTPS REST(穿透性好) |
| A 股日线 | ✅ 日/周/月频,不复权/前/后复权 | ✅ 全,分钟线需高积分 |
| 财报 | ✅ 季度 profit/balance/cashflow 指标 | ✅ 规范三大表 + 特色 |
| 特色数据 | ❌ 无北向/龙虎榜 | ✅ 北向(`moneyflow_hsgt`)/龙虎榜(`top_list`) |
| 实时 | ❌ 无 | ⚠️ 名义有,实为转发公开接口,无增益 |
| 港股/美股 | ❌ 无 | ⚠️ 有限 |
| SLA | 无(个人/公益,曾不可达) | 弱(2025-08 曾整周停运) |
| **商用 license** | ❌ 无商用条款 | ✅ 有商业授权渠道 |

**选型结论 —— 不是二选一,是双写交叉**(用户拍板):
- **稳定平面(日线/列表)双写 akshare + baostock**,router 按健康度动态选,pct_chg 交叉校验。
- **tushare 作 tier-3 补**:覆盖 baostock 缺的**特色数据**(北向/龙虎榜)+ 规范历史交叉。默认
  `enabled: false`,在 `config.yaml` 填 token 后开启。
- 二者失败模式不同(socket vs REST vs proxy),多源本身就是抗单点。

来源:[五大数据源测评](https://zhuanlan.zhihu.com/p/2016966946948654738)、
[Tushare 2025-08 停运事件](https://www.cls.cn/detail/2125736)、
[三源配置对比](https://zeeklog.com/san-da-shu-ju-yuan-zhong-ji-pei-zhi-zhi-nan-tushare-akshare-baostockshen-du-dui-bi-fen-xi-3)。

---

## 2. 两平面设计

| 平面 | 数据 | 特性 | 策略 |
|---|---|---|---|
| **稳定** | 日线/财报/清单 | 可预取、可缓存 | 多源双写交叉 + 动态路由 + 本地 parquet 缓存 |
| **实时** | 现价/五档 | 不可预取 | 短 TTL(3–5s)内存缓存 + akshare/web-fetch,tushare 不参与 |

实时为什么不上券商 API:用户当前选 web-fetch + 短 TTL(不开户、零成本)。真·实时(撮合级)
唯一正解是券商 API,列为 deferred(见 §4)。

---

## 3. 100 用户产品化架构蓝图

**核心判断**:100 并发直打 akshare/baostock/tushare,三个都会挂 —— 跟选谁无关。正解是
**客户请求 ≠ 上游调用**:

```
客户 (N 并发)  →  Cache 层 (DB/时序库)  ←  IngestionJob (单消费者, 可控频次)  →  多源交叉
   读缓存, 毫秒级, 无上游压力         定时/增量入库, 交叉校验          只有这一层碰第三方源
```

**当前代码已按这个终局分层(架构预留,依赖倒置)**:
- `Cache` 抽象(`cache.py`)→ 现在 `LocalParquetCache` + `InMemoryTTLCache`,未来换
  `RedisCache` / `PostgresCache` **零改调用方**。
- `DataSource` 抽象 + `SourceRouter`(`sources.py`)→ 现在「请求时拉」,未来把 router 塞进
  后台 `IngestionJob`「定时入库」,`server.py` tool 不动。

演进只改实现层,不动 tool 接口 —— 这是从单机平滑长到多用户服务的关键。

**⚠️ 商用 license 演进红线**:双写里的 akshare(抓公开网页)、baostock(个人项目无商用条款)
**均无商用授权**。单机自用无碍;**一旦对外收费**,双写中的无授权源必须替换为有商用授权的:
- Tushare Pro 商业版(有授权渠道)
- 付费 REST(EODHD 等)
不替换直接商用有法律风险。这是产品化前必须处理的,不是可选项。

---

## 4. Deferred upgrades(willing-to-pay 时启用)

| 需求 | 方案 | 门槛 |
|---|---|---|
| 真·实时行情(A股/港股) | 券商 API:Futu OpenAPI / LongPort OpenAPI | 开户 + 本地网关(OpenD)+ Lv2 权限;单连接标的数受限 |
| 结构化港股(财报/历史) | EODHD REST | 纯 API key,无需开户,实时偏弱,适合产品化分发 |
| 稳定 A 股 + 商用授权 | Tushare Pro 商业版 | 付费 + 商务合作 |

港股当前走 web-fetch 白名单(`WEB_FALLBACK_WHITELIST.md`),EODHD/券商 API 是日后升级项。

来源:[Futu OpenAPI 文档](https://openapi.futunn.com/futu-api-doc/)、
[LongPort OpenAPI](https://open.longportapp.com/zh-HK/docs)。

---

## 5. 配置速查(`mcp_server/config.yaml`)

```yaml
sources:
  akshare: {enabled: true}                    # tier-1, 恒开
  baostock: {enabled: true}                   # tier-2, 双写第二源
  tushare: {enabled: false, token: ""}        # tier-3, 填 token 后开启(北向/龙虎榜)
cache: {realtime_ttl: 5}                       # 实时短 TTL
router:                                        # 动态路由 / circuit breaker
  dual_write: true
  breaker_threshold: 3
  cooldown: 60
  retries: 2
  timeout: 15
```
