# Web-fetch Fallback 白名单 —— 可信证券数据源 + 解析范式

**何时用**:仅当 china-market MCP 返回 `web_fallback: true`(结构化源 akshare/baostock/tushare
全挂),或查询**港股 `.HK`**(MCP 不覆盖)时。这是分层降级的**最后一层**,不是首选。

**铁律**:
1. **只允许本文件列出的白名单站点** —— 不要用随机搜索结果的 A 股财务数字(网页口径乱)。
2. **每条 web-fetch 数据必须标注**:来源 URL + 抓取时间 + 口径提醒。
3. **口径提醒**必说清:CAS vs IFRS、合并 vs 母公司、归母 vs 全部净利、复权 vs 不复权。
4. 拿到后若与后续 MCP 恢复的数据冲突,以 MCP 结构化源为准。
5. 触发一次 web-fetch 就按 `data-source-postmortem` 记一条 log。

---

## A 股(沪深)

| 数据类型 | 白名单站点 | URL pattern | 抓取方式 | 口径坑 |
|---|---|---|---|---|
| 实时行情/现价 | 东方财富 | `quote.eastmoney.com/{sh|sz}{code}.html` | WebFetch 直取 | 分时价,非撮合级 |
| 实时行情/现价 | 新浪财经 | `finance.sina.com.cn/realstock/company/{sh|sz}{code}/nc.shtml` | WebFetch | 同上 |
| 行情/K线/估值 | 雪球 | `xueqiu.com/S/{SH|SZ}{code}` | **web-scraping**(JS 渲染) | 需登录态可能受限 |
| 财报原文(最权威) | 巨潮资讯 | `cninfo.com.cn` 搜代码 → 定期报告 PDF | WebFetch 找公告 → PDF | 原始披露,口径最准 |
| 财报/F10 速览 | 东方财富 F10 | `emweb.securities.eastmoney.com/pc_hsf10/...` | web-scraping | 单季 vs 累计要看清 |
| 估值分位(PE/PB) | 理杏仁 | `lixinger.com`(需注册/部分付费) | WebFetch/scraping | 扣非 vs 全部,注意分位区间 |
| 可转债/分级/ETF | 集思录 | `jisilu.cn` | web-scraping | — |

**A 股财报强口径提醒**:做估值优先用「归属于母公司股东的净利润」;PE 看似便宜先查是否有
一次性损益(投资收益/公允价值变动)膨胀分母 —— 参见 [equity-analysis-gate](../../../../skills/equity-analysis-gate/SKILL.md) Step 2。

---

## 港股(`.HK` —— china-market MCP 完全不覆盖,直接走这里)

| 数据类型 | 白名单站点 | URL pattern | 抓取方式 | 口径坑 |
|---|---|---|---|---|
| 行情/实时/财务 | AAStocks | `aastocks.com/en/stocks/quote/detail-quote.aspx?symbol={5位港股码}` | WebFetch | 港股代码补零到 5 位(00700) |
| 行情/财务/估值 | 东方财富港股 | `quote.eastmoney.com/hk/{code}.html` | WebFetch | 港股财报多为 IFRS/HKFRS |
| 行情/深度 | futu 富途 | `futunn.com/stock/{code}-HK` | web-scraping | Lv2 深度需登录 |
| 行情/K线/讨论 | 雪球港股 | `xueqiu.com/S/{code}`(港股直接用数字) | web-scraping | — |
| 全球/历史/财务 | Yahoo Finance HK | `finance.yahoo.com/quote/{code}.HK` | WebFetch | 币种 HKD,注意与 A 股 CNY 分列 |

**港股强口径提醒**:
- 港股财报口径多为 **IFRS/HKFRS**,与 A 股 **CAS** 不可直接混用;跨市场比较必须分列币种(HKD vs CNY)。
- A+H 双重上市(如 601318.SH / 2318.HK)存在 **A/H 折溢价**,不要把两地价格当同一标的。
- 港股代码习惯补零到 5 位(腾讯 00700),不同站点位数要求不一,注意适配。

---

## 结构化港股升级路径(deferred,willing-to-pay 时启用)

web-fetch 港股是当前兜底,不是长久之计。若要**稳定结构化**港股数据:
- **EODHD**(海外 REST,API key 接入,港股财报/历史强、实时弱)—— 无需券商开户,适合产品化分发。
- **LongPort / Futu OpenAPI**(需券商开户 + 本地网关 + Lv2)—— 真实时,但有开户门槛、单连接标的数限制。

详见 [DATA_SOURCES.md](DATA_SOURCES.md)。
