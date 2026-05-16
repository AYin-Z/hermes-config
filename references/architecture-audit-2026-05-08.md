# MemOS 架构审计 — 2026-05-08

对比官方三条产品线和我们的实际部署。

## 官方三条产品线

| 产品 | 后端 | Agent 适配器 | 端点 |
|---|---|---|---|
| **MemOS Cloud** | 托管服务 | OpenClaw Cloud Plugin | `/search/memory`, `/add/message` |
| **MemOS Local Plugin** | Node.js daemon + SQLite | Hermes/OpenClaw Local Plugin | TCP JSON-RPC :18992 |
| **MemOS Self-Hosted Docker** | Neo4j + Qdrant + FastAPI | **无官方适配器** | `/product/search`, `/product/add` |

## 关键发现

1. **Docker REST API 是通用后端**，不绑定任何 Agent。端点命名（`/product/*`）也跟 Cloud API 不同。
2. **官方给 Hermes 的路是 Local Plugin**（Node.js daemon + SQLite），不是 Docker。
3. **GitHub Issue #71** 已确认 Self-Hosted 和 Cloud Plugin 的 API 不兼容。
4. 社区 fork `ouchanip/memos-openclaw-local` 为 OpenClaw 写了适配层，做的事和我们一样。

## 我们的部署

```
Hermes Gateway
  └─ MemTensorProvider (官方接口)
       └─ MemosCoreBridge (自定义三模式)
            ├─ _HttpTransport → Docker REST API (优先)
            ├─ _TcpTransport  → Node daemon :18992 (备选，目前闲置)
            └─ _StdioTransport → bridge.cts (兜底)
```

## 已知问题

1. **Node.js daemon 白跑** — `ensure_daemon()` 每次启动都 spawn bridge.cts (~200MB)，但因 `MEMOS_API_URL` 已设，实际走 HTTP transport 到 Docker。
2. **两个独立数据库** — daemon 的 SQLite 和 Docker 的 Neo4j+Qdrant 不同步。
3. **缺少任务总结/技能进化** — 这些只在 Local Plugin 的 Node.js 管道中实现，REST API 不做。

## 任务/技能管线不可移植

官方 pipeline（~3000 行 TypeScript）: Episode 生命周期 + 话题关系分类 + 奖励评分 + L2 策略提取 → L3 聚类 → 技能结晶。简化版 Python 重写可行但不值得 — Hermes 已有手动技能创建，功能重叠。
