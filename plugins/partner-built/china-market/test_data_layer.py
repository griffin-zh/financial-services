"""china-market 数据层确定性验证 (synthetic sources, 不依赖网络)。

覆盖 plan 验证清单: 双写一致/分歧、circuit breaker、有序 fallback、web_fallback surface、
短 TTL 缓存、缓存接口可替换性 (DictCache 注入 server tool)。
"""
import sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "mcp_server"))

import pandas as pd
import sources as S
from cache import InMemoryTTLCache, DictCache

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
results = []
def check(name, cond):
    results.append(cond)
    print(f"  [{PASS if cond else FAIL}] {name}")


def make_daily(symbol, pct_list, start_day=15):
    return pd.DataFrame({
        "symbol": symbol,
        "date": [f"2026-04-{start_day+i:02d}" for i in range(len(pct_list))],
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "volume": 1000, "pct_chg": pct_list,
    })


class FakeSource(S.DataSource):
    capabilities = {"daily", "financial", "realtime"}
    def __init__(self, name, daily_pcts=None, fail=False):
        self.name = name
        self._daily_pcts = daily_pcts
        self._fail = fail
        self.calls = 0
    def fetch_daily(self, symbol, start, end):
        self.calls += 1
        if self._fail:
            raise S.SourceError(f"{self.name} 故意失败")
        return make_daily(symbol, self._daily_pcts)
    def fetch_realtime(self, symbols):
        self.calls += 1
        if self._fail:
            raise S.SourceError("rt fail")
        return pd.DataFrame({"symbol": symbols, "price": [1.0]*len(symbols)})


print("\n== 1. 双写一致 → confidence high ==")
a = FakeSource("akshare", [1.0, 2.0, -0.5])
b = FakeSource("baostock", [1.0, 2.0, -0.5])
r = S.SourceRouter([a, b], dual_write=True, retries=0)
res = r.get_daily("600519.SH", "2026-04-15", "2026-04-25")
check("sources 含两源", set(res["sources"]) == {"akshare", "baostock"})
check("confidence == high", res["confidence"] == "high")
check("discrepancy 为空", res["discrepancy"] is None)
check("degraded == False", res["degraded"] is False)

print("\n== 2. 双写分歧 → confidence low + discrepancy 附两源值 ==")
a = FakeSource("akshare", [1.0, 2.0, -0.5])
b = FakeSource("baostock", [1.0, 2.0, 9.9])  # 第 3 天对不上 (差 10.4 > 0.5 容差)
r = S.SourceRouter([a, b], dual_write=True, retries=0)
res = r.get_daily("600519.SH", "2026-04-15", "2026-04-25")
check("confidence == low", res["confidence"] == "low")
check("discrepancy 非空", res["discrepancy"] is not None)
check("discrepancy 含两源值", res["discrepancy"] and "akshare" in res["discrepancy"]["sample"]
      and "baostock" in res["discrepancy"]["sample"])
check("degraded == True", res["degraded"] is True)
print("       discrepancy sample:", res["discrepancy"]["sample"] if res["discrepancy"] else None)

print("\n== 3. circuit breaker: 连续失败 → 熔断 → 不再选中 ==")
bad = FakeSource("akshare", fail=True)
good = FakeSource("baostock", [1.0, 2.0])
r = S.SourceRouter([bad, good], dual_write=True, breaker_threshold=2, cooldown=100, retries=0)
r.get_daily("600519.SH", "2026-04-15", "2026-04-25")  # bad fail #1
r.get_daily("600519.SH", "2026-04-15", "2026-04-25")  # bad fail #2 → open
h = r.health_report()
check("akshare 熔断 open", h["akshare"]["state"] == "open")
check("baostock 顶上服务", h["baostock"]["success"] >= 1)
calls_before = bad.calls
res = r.get_daily("600519.SH", "2026-04-15", "2026-04-25")  # bad 已熔断, 不该再被调
check("熔断后不再调用坏源", bad.calls == calls_before)
check("熔断后仍能出数(baostock 单源)",
      res["df"] is not None and not res["df"].empty and res["confidence"] == "single")

print("\n== 4. circuit breaker 冷却后半开探活 ==")
bad2 = FakeSource("akshare", fail=True)
good2 = FakeSource("baostock", [1.0])
r = S.SourceRouter([bad2, good2], breaker_threshold=1, cooldown=0.3, retries=0)
r.get_daily("x.SH", "2026-04-15", "2026-04-16")  # fail → open (threshold=1)
check("立即熔断", r.health_report()["akshare"]["state"] == "open")
time.sleep(0.35)
check("冷却后 allow() 半开放行", r._health["akshare"].allow() is True)

print("\n== 5. 三源全挂 → web_fallback surface (非静默空) ==")
r = S.SourceRouter([FakeSource("akshare", fail=True), FakeSource("baostock", fail=True)],
                   dual_write=True, retries=0)
res = r.get_daily("600519.SH", "2026-04-15", "2026-04-25")
check("web_fallback == True", res["web_fallback"] is True)
check("有 warning 授权 web-fetch", any("web-fetch" in w for w in res["warnings"]))
check("df 为空但非异常", res["df"] is None)

print("\n== 6. 有序 fallback: 主源挂 → 备源 + degraded 标记 ==")
r = S.SourceRouter([FakeSource("akshare", fail=True), FakeSource("baostock", [1.0])], retries=0)
res = r.get_realtime(["600519.SH"])
check("降级到 baostock", res["source"] == "baostock")
check("degraded == True", res["degraded"] is True)
check("warning 说明降级", any("降级" in w for w in res["warnings"]))

print("\n== 7. InMemoryTTLCache 短 TTL ==")
c = InMemoryTTLCache(default_ttl=0.2)
c.set("k", {"v": 1})
check("TTL 内命中", c.get("k") == {"v": 1})
time.sleep(0.25)
check("TTL 过期 miss", c.get("k") is None)

print("\n== 8. 缓存接口可替换性: DictCache 注入 server tool 零改动 ==")
import mcp_server.server as srv  # 需 financial env (有 mcp)
srv._router = S.SourceRouter([FakeSource("akshare", [1.0, 2.0, 3.0])], retries=0)
srv._bars_cache = DictCache()          # 换成纯字典实现
srv._realtime_cache = InMemoryTTLCache(default_ttl=1.0)
out = srv.get_daily_bars(["600519.SH"], "2026-04-15", "2026-04-25")
check("server tool 用 DictCache 仍出数", out["count"] == 3)
check("stale 兜底: 再查已写入 DictCache", srv._bars_cache.get("600519.SH") is not None)
# 模拟上游全挂, 应从 DictCache 取 stale
srv._router = S.SourceRouter([FakeSource("akshare", fail=True)], retries=0)
out2 = srv.get_daily_bars(["600519.SH"], "2026-04-15", "2026-04-25")
check("上游全挂 → 返回 stale 缓存", out2["count"] == 3 and out2["confidence"] == "stale")
check("stale 有过期警告", any("stale" in w for w in out2["warnings"]))

print("\n== 9. 短 TTL 缓存命中 (server get_realtime_quote) ==")
srv._router = S.SourceRouter([FakeSource("akshare", [1.0])], retries=0)
srv._realtime_cache = InMemoryTTLCache(default_ttl=5.0)
q1 = srv.get_realtime_quote(["600519.SH"])
fake = srv._router._sources[0]
calls_after_first = fake.calls
q2 = srv.get_realtime_quote(["600519.SH"])  # 应命中缓存, 不再打源
check("第一次 cache_hit == False", q1.get("cache_hit") is False)
check("第二次 cache_hit == True", q2.get("cache_hit") is True)
check("TTL 内不重复打源", fake.calls == calls_after_first)

print(f"\n{'='*50}")
print(f"总计 {len(results)} 项, 通过 {sum(results)}, 失败 {len(results)-sum(results)}")
sys.exit(0 if all(results) else 1)
