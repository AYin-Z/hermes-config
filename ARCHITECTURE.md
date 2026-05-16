# 架构总览

## 系统拓扑

```
Hermes Agent (Python)
  │
  ├─ config.yaml
  │    memory.provider: memtensor
  │
  ├─ MemTensorProvider          ← __init__.py (457行)
  │    Hermes 官方 MemoryProvider 子类
  │    负责：同步 ingest / 异步 prefetch / memory_search tool
  │    上层 Provider 零改动
  │
  ├─ MemosCoreBridge            ← bridge_client.py (380行)
  │    Transport 自动选择器 (REST → TCP → stdio)
  │    提供 search() / ingest() / recent() / ping() / build_prompt()
  │
  └─ _HttpTransport (~140行)
       JSON-RPC → REST 适配层
       /product/search → search
       /product/add    → ingest
       /product/get_all → recent
       /health          → ping

┌─────────────────────────────────────────┐
│          Docker MemOS Full Server       │
│                                         │
│  memos-api (:8000)  ← REST API 入口     │
│  Neo4j (:7474)       ← 图谱存储          │
│  Qdrant (:6333)      ← 向量存储          │
└─────────────────────────────────────────┘
```

## Transport 分层

```
初始化时检查 MEMOS_API_URL 环境变量？
  ├─ 有 → _HttpTransport → localhost:8000 (Docker REST API)
  │        ping 成功 → 使用
  │        ping 失败 → 关掉，继续往下
  ├─ 无 → _TcpTransport → localhost:18992 (Node 守护进程)
  │        ping 成功 → 使用
  │        ping 失败 → 关掉，继续往下
  └─ 兜底 → _StdioTransport → npx tsx bridge.cts 子进程
```

**生产建议:** 固定 REST，TCP 和 stdio 仅用于调试。

## 数据流

### 记忆写入
```
对话完成 → sync_turn() → pending_ingest (暂存)
        → queue_prefetch() → 先 search (当前轮不污染)
                           → 再 flush pending_ingest → POST /product/add
```

### 记忆搜索
```
用户提问 → prefetch() → _do_recall()
                      → bridge.search() → POST /product/search
                      → 格式化结果 → 注入 prompt
```

## 硬化要点

1. **幂等写入** — `session_id:turn_id` 幂等键，服务端 30s 内存去重
2. **标识字段** — 每个请求显式传 `agent_id` / `workspace_id` / `session_id`
3. **深度健康** — `GET /product/health/detail` 探测 5 层
4. **结构化日志** — `[memtensor] search | query=... | hits=N | took=Nms`
5. **主链路固定** — 启动日志明确输出 transport 选择
