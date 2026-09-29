# 06 · china-market 代码走读(唯一真实代码 · 深入)

> 这是全仓**唯一值得逐行读的代码**。读完本章你会掌握:A 股数据服务的分层设计、健康感知路由 + 双写交叉、熔断器、缓存抽象,以及 10 个 MCP tool 的统一返回体。这套代码是"教科书式可演进设计"的范例,也是你日后最可能动手改的地方。

## 6.1 它为什么存在

官方的 11 个数据连接器(Daloopa / FactSet / Kensho…)**都不覆盖 A 股(沪深两市)**。`china-market` 补这个缺口([server.py:11-13](../plugins/partner-built/china-market/mcp_server/server.py#L11-L13))。它是一个**共享的远程 SSE MCP 服务**,由 CI 打成镜像发布到 GHCR,Claude Code 与下游产品都作为 client 连**同一个运行实例**。

代码单一源在 [mcp_server/](../plugins/partner-built/china-market/mcp_server/),四个文件:

| 文件 | 层 | 职责 |
|---|---|---|
| `sources.py` | 适配 + 路由 | 三源 adapter + 健康感知路由 + 双写交叉 |
| `cache.py` | 缓存 | `Cache` 抽象 + 内存 TTL / 本地 parquet |
| `server.py` | 服务 | `FastMCP` 暴露 10 个 tool,统一返回体 |
| `config.yaml` | 配置 | 数据源开关、缓存、router 参数 |

## 6.2 分层总览

```
        MCP client (Claude Code / 下游产品)
                    │  SSE
        ┌───────────▼────────────┐
        │  server.py             │  10 个 @mcp.tool(),统一返回体
        │  (FastMCP)             │
        └─────┬──────────┬───────┘
              │          │
     ┌────────▼───┐  ┌───▼──────────────────┐
     │ cache.py   │  │ sources.SourceRouter │  健康感知路由 + 双写交叉
     │ Cache 抽象 │  └───┬──────┬──────┬─────┘
     └────────────┘      │      │      │
                    Akshare Baostock Tushare  ← DataSource(ABC) 的三个 adapter
                    (直连各自 Python 库,归一化到统一列 schema)
```

设计三原则(见 [sources.py:3-12](../plugins/partner-built/china-market/mcp_server/sources.py#L3-L12)):抽象解耦、健康感知动态路由 + 稳定平面双写交叉、三源全挂时结构化 `web_fallback`(而非静默返回空)。

## 6.3 适配层:`DataSource` 抽象 + 三个 adapter

**统一 schema**——所有 adapter 的日线输出都 rename 成同一套列名([sources.py:32](../plugins/partner-built/china-market/mcp_server/sources.py#L32)):

```python
DAILY_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "pct_chg"]
```

**抽象基类** `DataSource(ABC)`([sources.py:112-141](../plugins/partner-built/china-market/mcp_server/sources.py#L112-L141)):声明 8 个 capability(daily / realtime / financial / stock_list / north_flow / dragon_tiger / notices / news),默认全部抛 `SourceUnsupported`;子类只实现自己支持的,并用 `capabilities` 集合声明能力。

**三个 adapter**(各自直连库,互不依赖):

| Adapter | 行号 | 定位 | capabilities |
|---|---|---|---|
| `AkshareSource` | [:144](../plugins/partner-built/china-market/mcp_server/sources.py#L144) | tier-1 主源,覆盖最广,无 token | daily / realtime / financial / stock_list / north_flow / dragon_tiger / notices / news(全 8) |
| `BaostockSource` | [:263](../plugins/partner-built/china-market/mcp_server/sources.py#L263) | tier-2,交易所源,A 股日线最稳,作双写第二源 | daily / stock_list |
| `TushareSource` | [:335](../plugins/partner-built/china-market/mcp_server/sources.py#L335) | tier-3,需 token,规范历史 + 特色数据 | daily / financial / stock_list / north_flow / dragon_tiger |

三者都把各自的中文列名 / 字段 rename 到 `DAILY_COLUMNS`(例:akshare 的 `涨跌幅`→`pct_chg`,baostock 的 `pctChg`→`pct_chg`,tushare 的 `vol`→`volume`),**让上层与数据源彻底解耦**。

> **加一个数据源 = 新增一个 `DataSource` 子类**,不动任何上层。这就是抽象基类的价值,操作见 [08 第 5 条](./08-如何修改与演进.md)。

## 6.4 路由层:健康感知 + 双写交叉(核心)

### 熔断器 `HealthState`

每个源一个 circuit breaker([sources.py:394-438](../plugins/partner-built/china-market/mcp_server/sources.py#L394-L438)),三态:

- `closed`(正常)→ 连续失败达 `threshold`(默认 3)→ 转 `open`;
- `open`(熔断)→ 冷却 `cooldown`(默认 60s)内直接拒绝,不打上游;
- 冷却到期 → `half_open`(半开探活),成功转回 `closed`,再失败立即回 `open`。

`allow()`([:407-414](../plugins/partner-built/china-market/mcp_server/sources.py#L407-L414))是路由前的准入判断。

### 稳定平面:双写交叉 `_dispatch_dual`

对**日线 / 股票列表**这类"不该随源不同而变"的数据,顺序拉 ≥2 个健康源做交叉校验([sources.py:527-557](../plugins/partner-built/china-market/mcp_server/sources.py#L527-L557)),`confidence` 分三档:

| 情况 | confidence | degraded | 含义 |
|---|---|---|---|
| ≥2 源且比对一致 | `high` | false | 交叉校验通过 |
| ≥2 源但比对分歧 | `low` | true | 附 `discrepancy` 两源值 |
| 仅 1 源可得 | `single` | true | 未能交叉 |
| 全挂 | (`web_fallback`) | true | 触发白名单 web-fetch |

比对逻辑 `_compare_daily`([:441-468](../plugins/partner-built/china-market/mcp_server/sources.py#L441-L468)):对齐 `date`,比**口径无关**的 `pct_chg`(涨跌幅不受复权影响),容差 0.5 个百分点,超差即记为分歧并附样本。

### 实时 / 特色平面:有序 fallback `_dispatch_single`

对实时快照、北向、龙虎榜等,走"第一个健康且成功的源"([sources.py:560-577](../plugins/partner-built/china-market/mcp_server/sources.py#L560-L577)),降级到备源时标 `degraded` + warning。

### 全挂兜底:`_web_fallback`

三源全失败时**不返回空**,而是返回 `web_fallback=True` 的结构化 surface([sources.py:579-592](../plugins/partner-built/china-market/mcp_server/sources.py#L579-L592)),由上层 skill 显式授权按白名单 web-fetch。

### 工厂 `build_router`

按 config 开关装配 router([sources.py:629-650](../plugins/partner-built/china-market/mcp_server/sources.py#L629-L650)):akshare 恒在,baostock/tushare 按 `enabled` 开关(tushare 还需非空 token,否则自动跳过)。

## 6.5 缓存层:`Cache` 抽象(演进预留)

[cache.py:1-7](../plugins/partner-built/china-market/mcp_server/cache.py#L1-L7) 的注释直接写明了这是"**平滑演进点**":

> 调用方(server.py 的 tool)只依赖 `Cache` 抽象接口。未来产品化(100 用户)时把实现换成 RedisCache / PostgresCache,并把"请求时拉"改成后台 IngestionJob"定时入库"——server.py 调用方零改动。

三个现成实现:

| 实现 | 行号 | 用途 |
|---|---|---|
| `InMemoryTTLCache` | [:32-58](../plugins/partner-built/china-market/mcp_server/cache.py#L32-L58) | 实时快照,线程安全,默认 5s TTL |
| `LocalParquetCache` | [:61-90](../plugins/partner-built/china-market/mcp_server/cache.py#L61-L90) | 历史日线存 `<symbol>.parquet`(不变数据) |
| `DictCache` | [:93-106](../plugins/partner-built/china-market/mcp_server/cache.py#L93-L106) | 纯内存,测试"缓存接口可替换性" |

注入点在 [server.py:68-69](../plugins/partner-built/china-market/mcp_server/server.py#L68-L69):

```python
_bars_cache = LocalParquetCache(_cache_dir)              # 历史日线
_realtime_cache = InMemoryTTLCache(default_ttl=_realtime_ttl)  # 实时快照
```

> **升级缓存 = 实现一个新 `Cache` 子类 + 改这两行注入**,tool 逻辑一行不动。见 [08 第 7 条](./08-如何修改与演进.md)。

## 6.6 服务层:10 个 MCP tool + 统一返回体

`server.py` 用 `FastMCP` 的 `@mcp.tool()` 装饰器暴露 10 个 tool。**每个 tool 返回统一结构**([server.py:15-17](../plugins/partner-built/china-market/mcp_server/server.py#L15-L17)),由 `_pack_dual`([:113](../plugins/partner-built/china-market/mcp_server/server.py#L113))/ `_pack_single`([:129](../plugins/partner-built/china-market/mcp_server/server.py#L129))打包:

```
{ rows, count, columns, sources, confidence, degraded, discrepancy, warnings, web_fallback }
```

上层 skill 靠这些字段感知数据源、双写一致性、是否需要降级。

**10 个 tool 速查**:

| Tool | 行号 | 平面 | 说明 |
|---|---|---|---|
| `get_daily_bars` | [:149](../plugins/partner-built/china-market/mcp_server/server.py#L149) | 双写 | 日线 OHLCV(不复权),confidence 取最差 |
| `get_stock_list` | [:218](../plugins/partner-built/china-market/mcp_server/server.py#L218) | 双写 | 股票列表(名称/行业) |
| `get_realtime_quote` | [:231](../plugins/partner-built/china-market/mcp_server/server.py#L231) | 单源+TTL | 实时快照,短 TTL 缓存 |
| `get_financial_report` | [:254](../plugins/partner-built/china-market/mcp_server/server.py#L254) | 单源 | 三大财报(income/balance/cashflow) |
| `get_north_flow` | [:275](../plugins/partner-built/china-market/mcp_server/server.py#L275) | 单源 | 北向资金净流入 |
| `get_dragon_tiger` | [:281](../plugins/partner-built/china-market/mcp_server/server.py#L281) | 单源 | 龙虎榜 |
| `get_stock_notices` | [:292](../plugins/partner-built/china-market/mcp_server/server.py#L292) | 单源 | 个股公告(best-effort) |
| `get_stock_news` | [:305](../plugins/partner-built/china-market/mcp_server/server.py#L305) | 单源 | 全市场财经新闻 |
| `get_market_context` | [:318](../plugins/partner-built/china-market/mcp_server/server.py#L318) | 常量 | 估值常量(risk-free/ERP/税率/申万/巨潮) |
| `get_source_health` | [:349](../plugins/partner-built/china-market/mcp_server/server.py#L349) | 诊断 | 各源熔断器状态/成功率/延迟 |

**注意 `get_daily_bars` 的多层降级**([server.py:177-215](../plugins/partner-built/china-market/mcp_server/server.py#L177-L215)):逐 symbol 取数;上游全挂时尝试本地 stale 缓存(`confidence=stale`);confidence 按 `stale < low < single < high` **取最差**([:205-206](../plugins/partner-built/china-market/mcp_server/server.py#L205-L206))——多 symbol 里最弱的那个决定整体可信度。

**`get_market_context`**([:318-346](../plugins/partner-built/china-market/mcp_server/server.py#L318-L346))是纯常量、无外部调用,返回 A 股估值需要的中国特化输入:CNY 币种、中国 10Y 国债 risk-free、Damodaran China ERP、25% 税率、CAS 会计准则、巨潮 filings、申万行业分类、偏好 PE/PB/PEG。这解释了为什么"A 股的 DCF/comps 与美股不同"。

## 6.7 配置与环境变量

[config.yaml](../plugins/partner-built/china-market/mcp_server/config.yaml) 是全仓唯一有实际运行时含义的配置:

```yaml
sources:
  akshare:  { enabled: true }             # tier-1 恒开
  baostock: { enabled: true }             # tier-2 双写第二源
  tushare:  { enabled: false, token: "" } # tier-3,填 token 后设 true
storage:  { path: ./data_cache/market }
cache:    { realtime_ttl: 5 }             # 实时快照短 TTL(秒)
router:
  dual_write: true                        # 双写交叉开关
  breaker_threshold: 3                    # 连续失败几次熔断
  cooldown: 60                            # 熔断冷却秒数
  retries: 2                              # 每源 retry 次数
  timeout: 15                             # 单次调用超时(秒)
```

环境变量([server.py:47-83](../plugins/partner-built/china-market/mcp_server/server.py#L47-L83)):

| 变量 | 默认 | 作用 |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | 镜像里设 `sse`,决定传输方式 |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `8080` | SSE 监听地址 |
| `CHINA_MARKET_CONFIG` | config.yaml 路径 | 覆盖配置文件路径 |
| `CHINA_MARKET_CACHE_DIR` | 相对 plugin root | 覆盖缓存目录到挂载卷 |
| `TUSHARE_TOKEN` | 空 | 注入 token(留空则 router 跳过 tushare) |

## 6.8 怎么把服务跑起来

推荐用镜像;本地调试可从源码起(见 [CLAUDE.md:69-92](../CLAUDE.md#L69-L92)):

```bash
# 方式一:镜像(推荐,下游 compose 也用这个)
docker run --rm -p 8080:8080 ghcr.io/<owner>/china-market-mcp:latest

# 方式二:从源码起(需先装依赖)
python -c "import mcp, akshare, baostock, tushare, pandas, yaml, loguru, pyarrow; print('all ok')"
python -m pip install -r plugins/partner-built/china-market/mcp_server/requirements.txt
MCP_TRANSPORT=sse MCP_PORT=8080 python plugins/partner-built/china-market/mcp_server/server.py
```

起来后 `/mcp` 应看到 `china-market` 状态 `connected`(端点 `http://localhost:8080/sse`,声明在 [china-market/.mcp.json](../plugins/partner-built/china-market/.mcp.json))。**连不上时先确认服务在跑 + 端口已发布,不要因此静默 fallback**([CLAUDE.md:80](../CLAUDE.md#L80))。

## 6.9 A 股路由的行为契约(上层怎么用)

[CLAUDE.md:50-102](../CLAUDE.md#L50-L102) 是这个服务的完整使用契约,要点:

- **触发**:6 位代码(`600519`)/ `.SH`/`.SZ` 后缀 / 中文公司名(贵州茅台)/ 关键词(A股/沪深/科创板…)。
- **第一动作**:确认 `/mcp` 里 `china-market` 为 `connected`。
- **分层降级不是硬禁 web**:看返回体 `confidence`/`degraded`/`web_fallback`;`web_fallback:true` 时按 [WEB_FALLBACK_WHITELIST.md](../plugins/partner-built/china-market/references/WEB_FALLBACK_WHITELIST.md) 的**白名单**站点 web-fetch,标来源 + 口径。
- **跨市场**:A 股 vs 美股,**币种分开列,不做隐式汇率换算**。

三个配套 skill(自动注入中国市场上下文,见 [CLAUDE.md:94-100](../CLAUDE.md#L94-L100)):`china-market-context`(router skill)、`a-share-data`(显式查询)、`data-source-postmortem`(失败复盘自净化)。

## 6.10 stdout 纪律(一个致命细节)

MCP 协议**占用 stdout**,而 baostock/tushare 的 login/query 会往 stdout 打印 → 污染协议。所以 `sources.py` 用 `_silence_stdout`([:74-82](../plugins/partner-built/china-market/mcp_server/sources.py#L74-L82))把所有源调用的 stdout 重定向到 stderr([:513](../plugins/partner-built/china-market/mcp_server/sources.py#L513))。日志也统一走 stderr([server.py:44-45](../plugins/partner-built/china-market/mcp_server/server.py#L44-L45))。

> **改这块代码时,任何新的 `print` / 库打印都必须走 stderr,否则会静默破坏 MCP 协议**。这是最隐蔽的坑,见 [09](./09-验证约定与常见陷阱.md)。

## 6.11 深入参考

- 数据源选型 + 100 用户架构蓝图 + 商用 license 红线:[references/DATA_SOURCES.md](../plugins/partner-built/china-market/references/DATA_SOURCES.md)
- web 兜底白名单:[references/WEB_FALLBACK_WHITELIST.md](../plugins/partner-built/china-market/references/WEB_FALLBACK_WHITELIST.md)
- 无网络确定性测试:[test_data_layer.py](../plugins/partner-built/china-market/test_data_layer.py)(见 [07](./07-工程化与工具链.md))

---

**下一章** → [07-工程化与工具链](./07-工程化与工具链.md):把 scripts / CI / 测试 / git hook 这条纪律链讲清楚。
