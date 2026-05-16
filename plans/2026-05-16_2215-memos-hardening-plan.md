# MemOS-Hermes 接入层硬化计划

> 基于小忆 15 项验收清单，全链路可改（Hermes adapter + MemOS 服务端源码均受控）。
>
> **铁律：本计划仅为实施方案。执行前需用户明确说「执行」或「动手」才可开始改代码。**

**Goal:** 将 MemOS-Hermes 接入层从「能跑」加固为「边界稳定、可观测、可恢复」的生产态。

**架构:** Hermes `__init__.py` → `bridge_client.py` (`MemosCoreBridge` + `_HttpTransport`) → Docker MemOS REST API (`/product/*`) → Neo4j + Qdrant

**版本管理:** 所有改动在 `~/hermes-config` repo 中管理，修改后 git commit。服务端源码 patch 保存为 reference diff。

---

## 现状（调研结论）

| 项目 | 当前状态 |
|------|---------|
| 主链路 | REST 已固定（`MEMOS_API_URL`），但**无启动日志显式声明 transport 选择** |
| 标识字段 | `owner` 默认从 `config.OWNER="hermes"` 取，`session_id` 靠默认推断，**无 `agent_id`/`workspace_id`/`turn_id` 显式传递** |
| 当前轮排除 | 客户端已做（deferred ingest + queue_prefetch 时序），**服务端无排除** |
| 幂等 | 0% |
| 日志 | 散乱，无追踪 ID |
| health | 仅 `{status: "healthy"}`，无依赖/写链/查链深度检查 |
| recent | `get_all` 不可靠（pitfall #20），无 scope 过滤 |

**MemOS 现有字段支持度（关键发现）：**
- `APIADDRequest` 已有 `project_id` + `info` (dict) → `agent_id` 可直接用 `info` 传
- `APISearchRequest` 已有 `session_id` + `readable_cube_ids`
- `GetMemoryPlaygroundRequest` 已有 `mem_cube_ids`
- *不需要改 MemOS 数据模型*，只需在参数中透传和适配

---

## 方案

### Phase 1 — 主链路固定 + 标识字段显式化（Hermes 侧，3 项）

#### Task 1.1: 启动日志打印 transport 选择

**文件:** `~/hermes-config/memos-plugin/adapters/hermes/bridge_client.py`

**改动:** 在 `MemosCoreBridge.__init__()` 中，三种 transport 分支添加明确的 `logger.info()` 日志，格式为：
```
MemOS transport selected: http (rest_api)  → http://localhost:8000
MemOS transport selected: tcp (daemon)     → port 18992
MemOS transport selected: stdio (subprocess)
```

**验证:** 重启 gateway → `journalctl --user -u hermes-gateway | grep "transport selected"` 看到一行确切的日志

**行级改动:** `bridge_client.py` L258、L273、L280 — 替换原 info 日志为统一格式

#### Task 1.2: 请求补全标识字段（bridge_client.py 侧）

**文件:** `~/hermes-config/memos-plugin/adapters/hermes/bridge_client.py`

**改动:** 修改 `_HttpTransport.send()`
- 从环境变量 + 构造函数引入 `_agent_id`、`_workspace_id`
- 每个 method 的 body 中显式注入：
  - `"agent_id": self._agent_id`
  - `"workspace_id": self._workspace_id`
  - `"session_id": params.get("sessionId", self._session_id or "default")`
  - **search 请求**：额外注入 `"exclude_turn_id": self._current_turn_id`（为后续 Task 2.2 准备）

**新增依赖:** `MemosCoreBridge.__init__()` 接受可选参数 `agent_id="hermes"`, `workspace_id="default"`，传给 `_HttpTransport`

**验证:** curl 直接打 `POST /product/search` 看请求体是否含这些字段（或 gateway 日志截获）

#### Task 1.3: 写入幂等键

**文件:** `~/hermes-config/memos-plugin/adapters/hermes/bridge_client.py` + `~/memos-server/src/memos/api/product_models.py`

**Hermes 侧（bridge_client.py _HttpTransport.send ingest 分支）：**
- 在 ingest body 中添加 `"idempotency_key": f"{session_id}:{turn_id}"`
- 从 `params["sessionId"]` + `params.get("turnId", "")` 构造

**MemOS 服务端侧（product_models.py APIADDRequest）：**
- 添加 `idempotency_key: str | None = Field(None)` 字段
- 在 `add` handler 中，相同的 `idempotency_key` 在短时间内（~30s）返回已有结果，不重复写入

**注意:** 幂等逻辑仅针对短时间窗口内的重试，不保证跨重启去重（那需要持久化缓存）。短期足够。

---

### Phase 2 — 服务端侧加固（MemOS 源码，2 项）

#### Task 2.1: Health 扩展为 4 层深度检查

**文件:** `~/memos-server/src/memos/api/server_api.py` + `~/memos-server/src/memos/api/routers/server_router.py`

**新增端点:** `GET /health/detail`
```json
{
  "status": "healthy" | "degraded",
  "service": "memos",
  "version": "2.0.14",
  "checks": {
    "api_alive": true,
    "neo4j": {"status": true, "latency_ms": 12},
    "qdrant": {"status": true, "latency_ms": 8},
    "write_chain": {"status": true, "latency_ms": 350},
    "search_chain": {"status": true, "latency_ms": 180}
  }
}
```

**实现逻辑:**
1. `api_alive` — 固定返回 true
2. `neo4j` — 执行 `MATCH (n) RETURN count(n) LIMIT 1` Cypher，记录耗时
3. `qdrant` — curl 到 `http://localhost:6333/collections`，检查响应
4. `write_chain` — 写入一个临时 memory，立即删除，检查能否写入
5. `search_chain` — 对已知短词语做 search，检查返回结果数

**`/health` 原端点保留不变**（兼容现有 checks）。新增 `/health/detail` 做深度检测。

#### Task 2.2: 服务端当前轮排除（双保险）

**文件:** `~/memos-server/src/memos/api/routers/server_router.py`

在 `search_memories` handler 中，检查请求体是否含 `exclude_turn_id` 或 `exclude_record_ids` 字段，若存在则在 Neo4j 查询中加过滤。

**注意:** 这个改动依赖 Neo4j 的 Cypher 查询语句 — 需找到 `SearchHandler.handle_search_memories()` 内部使用的查询并扩展 WHERE 条件。

**如果改动量过大**（因为 SearchHandler 内部可能有多层抽象），可以将此标记为 Phase 2 的门控项 — 不阻塞 Phase 1。

---

### Phase 3 — 可观测性 + 验收

#### Task 3.1: Hermes 侧结构化日志

**文件:** `~/hermes-config/memos-plugin/adapters/hermes/bridge_client.py` + `__init__.py`

在 `_HttpTransport.send()` 每个 method 分支前后加日志，格式统一：
```
[memtensor] search    | query="..."        | hits=5  | took=182ms
[memtensor] ingest    | session_id="..."   | msgs=2  | took=350ms
[memtensor] recent    | user_id="hermes"   | items=0 | took=12ms
[memtensor] build_... | query="..."        | parts=3 | took=210ms
[memtensor] ping      |                    | ok=true | took=8ms
[memtensor] flush     |                    | status=ok
```

在 `_do_recall()` 中加日志：
```
[memtensor] recall | query="..." | search_hits=5 | recent_fallback=0 | injected=3
```

#### Task 3.2: 可验收测试 — 对照小忆 15 项清单的最小版

创建一个独立的测试脚本 `scripts/__init__` 或独立文件，覆盖 5 项最小验收：

1. **当前轮不自污染** — 发唯一词 → 立即 search → 确认不命中
2. **新会话可召回** — 发唯一词 → 跨 session search → 确认命中
3. **写入不重复** — 同一请求重发 3 次 → 确认 Neo4j 中仅 1 份
4. **主链路固定** — 重启后确认 transport 选择日志正确
5. **日志可追踪** — 检查关键日志包含 tracking 字段

---

## 文件变更清单

| 文件 | 改动 | 影响范围 |
|------|------|---------|
| `~/hermes-config/memos-plugin/adapters/hermes/bridge_client.py` | L27-166 `_HttpTransport` + L244-281 init + L283-329 call | 全部 3 个 Phase |
| `~/hermes-config/memos-plugin/adapters/hermes/__init__.py` | L277-317 `_do_recall` 加日志 | Phase 3 |
| `~/hermes-server/src/memos/api/server_api.py` | 新增 `/health/detail` 端点 | Phase 2 |
| `~/hermes-server/src/memos/api/product_models.py` | `APIADDRequest` 加 `idempotency_key` | Phase 1 |
| `~/hermes-server/src/memos/api/routers/server_router.py` | search 加 `exclude_turn_id` 过滤 | Phase 2 |

---

## 执行顺序

```
Phase 1 ────┬── Task 1.1 (transport 日志) — 15分钟
            ├── Task 1.2 (标识字段) — 1.5小时 
            └── Task 1.3 (幂等键) — 1小时
                 ↓
Phase 2 ────┬── Task 2.1 (health 深度) — 1小时
            └── Task 2.2 (服务端排除) — 2小时 [可能阻塞]
                 ↓
Phase 3 ────┬── Task 3.1 (结构化日志) — 1小时
            └── Task 3.2 (验收测试) — 1小时
```

**总计预估:** 6-8 小时分阶段完成

---

## 风险与回退

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 幂等键写入导致 MemOS handler 异常 | 低 | ingest 失败 | 先只加 request 字段，后端实现先加空白 handler（always-pass） |
| health 深度检查可能拖慢 MemOS | 低 | 延迟增加 | `_health_detail` 设置 5s 总超时，超时项标记为 false |
| search handler 内部架构复杂，exclude 改动大 | 中 | 阻塞 Phase 2 | 标记为「可选」，Phase 1 + 3 先交付 |
| git 未跟踪 memos-server 源码 | 中 | 无法回滚 | 每个 patch 保存为 `.hermes/plans/references/` 下的 diff 文件 |

**回滚预案:**
- Hermes 侧: `cd ~/hermes-config && git checkout -- memos-plugin/` 一键回滚所有改动的 adapter 文件
- MemOS 侧: 源码 bind mount，反向 patch 即可恢复；或 Docker 重启恢复初始镜像（放弃 mount 的改动）

---

## 验证清单（最小验收 — 小忆的 5 条）

- [ ] **当前轮不自污染** — 发 "A123-hermes-test" → 本轮 search 不应返回 → 下一轮应命中
- [ ] **新会话可召回** — 跨 session 追问 "A123-hermes-test" → 应返回准确结果
- [ ] **写入不重复** — 同一消息重试 3 次 → Neo4j 仅 1 份
- [ ] **主链路固定** — gateway 重启后日志明确显示 transport 选择
- [ ] **日志可追踪** — 单条请求能从 search → ingest 完整追踪

---

## 后续演进（非本计划范围）

- feedback 端点对接
- build_prompt 完全等价验收
- skill/policy/world model 接入
- 多 agent 隔离测试
