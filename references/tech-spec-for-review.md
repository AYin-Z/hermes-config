# Hermes × MemOS 本地自托管技术方案

> 写于 2026-05-09，供 MemOS 官方团队审阅  
> 部署者：殷政 (Ayin) | 环境：Ubuntu 26.04 家庭服务器

---

## 一、架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    Hermes Agent                         │
│  ┌─────────────┐    ┌──────────────┐                   │
│  │ memory 工具  │    │memory_search │  ← 内置记忆工具    │
│  └──────┬──────┘    └──────┬───────┘                   │
│         │                  │                            │
│  ┌──────▼──────────────────▼───────┐                    │
│  │   MemTensorProvider (389行)     │  ← MemoryProvider  │
│  │   适配器: adapters/hermes/       │     接口实现       │
│  └──────────────┬──────────────────┘                    │
│                 │                                       │
│  ┌──────────────▼──────────────────┐                    │
│  │  MemosCoreBridge (329行)        │  ← 传输层抽象      │
│  │  优先 HTTP → 回退 TCP → stdio   │                    │
│  └──────────────┬──────────────────┘                    │
└─────────────────┼───────────────────────────────────────┘
                  │ HTTP REST (localhost:8000)
┌─────────────────▼───────────────────────────────────────┐
│              MemOS Full Server (v2.0.14)                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │ FastAPI  │  │  24 个   │  │ LLM: DeepSeek V4 Pro  │   │
│  │ :8000    │  │ REST端点  │  │ Embed: bge-large-zh  │   │
│  └──────────┘  └──────────┘  └──────────────────────┘   │
│         │              │                                │
│  ┌──────▼──┐    ┌──────▼──────┐                         │
│  │  Neo4j  │    │   Qdrant    │   ← 存储层 (Docker)    │
│  │ 5.26.6  │    │  v1.15.3    │                         │
│  │ :7474   │    │ :6333       │                         │
│  └─────────┘    └─────────────┘                         │
└─────────────────────────────────────────────────────────┘
         ▲                   ▲
         │                   │
┌────────┴───────────────────┴───────────────────────────┐
│              Claude Code (可选)                          │
│  ┌──────────────────────────────────────┐               │
│  │  MemOS MCP Server (15 tools)         │  ← stdio MCP  │
│  │  通过 Neo4j HTTP + MemOS REST 调取   │               │
│  └──────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────┘
```

---

## 二、MemOS 部署

### 2.1 容器栈（Docker Compose）

来自 `github.com/MemTensor/MemOS` 官方仓库的 `docker/docker-compose.yml`，三容器：

| 容器 | 镜像 | 端口 | 用途 |
|------|------|------|------|
| `memos-api-docker` | 本地 build (Dockerfile) | 8000 | FastAPI REST 服务 |
| `neo4j-docker` | neo4j:5.26.6 | 7474, 7687 | 图数据库 |
| `qdrant-docker` | qdrant/qdrant:v1.15.3 | 6333, 6334 | 向量数据库 |

源码通过 volume mount (`../src:/app/src`) 实时同步，代码修改即时生效无需重建镜像。

### 2.2 环境变量 (`.env`)

**LLM（记忆提取）**：
```
MOS_CHAT_MODEL_PROVIDER=openai
MOS_CHAT_MODEL=deepseek-v4-pro
OPENAI_API_KEY=sk-xxx...
OPENAI_API_BASE=https://api.deepseek.com/v1
```

**Embedding（语义检索）**：
```
MOS_EMBEDDER_BACKEND=universal_api
MOS_EMBEDDER_PROVIDER=openai
MOS_EMBEDDER_MODEL=bge-large-zh-v1.5
MOS_EMBEDDER_API_BASE=http://host.docker.internal:8082/v1
EMBEDDING_DIMENSION=1024
```

Embedding 由宿主机 `llama-server` 提供（端口 8082），模型 `bge-large-zh-v1.5.Q8_0`（GGUF，约 400MB），通过 Docker `extra_hosts: host.docker.internal:host-gateway` 从容器内访问。

### 2.3 当前运行状态

| 组件 | 状态 | 内存总量 |
|------|:--:|------|
| MemOS API :8000 | ✅ v2.0.14 | — |
| Neo4j :7474 | ✅ 5.26.6 | 706+ memories |
| Qdrant :6333 | ✅ 1.15.3 | — |
| Embedding :8082 | ✅ bge-large-zh | — |

---

## 三、Hermes 集成方案

### 3.1 核心挑战

MemOS 本地插件版（`@memtensor/memos-local-hermes-plugin@1.0.4`）使用 **TCP JSON-RPC** 连接本地 daemon（端口 18992）。而 MemOS Full Server 暴露的是 **HTTP REST API**（端口 8000）。

协议不匹配，不能直接互换。

### 3.2 解决方案：HTTP Transport Adapter

**最简方案**：在现有 `bridge_client.py`（173 行）中新增 `_HttpTransport` 类（约 140 行），将 MemOS REST API 包装为 JSON-RPC 格式，复用上层全部 `MemTensorProvider` 逻辑（389 行）。

**文件**：`adapters/hermes/bridge_client.py`，新增类 `_HttpTransport`

**方法映射**：

| JSON-RPC method | MemOS REST | 说明 |
|:---|:---|:---|
| `ping` | `GET /health` | 健康检查 |
| `search` | `POST /product/search` | 语义搜索 |
| `ingest` | `POST /product/add` | 写入记忆 |
| `build_prompt` | `POST /product/search` + 格式化 | 生成记忆上下文 |
| `recent` | `POST /product/get_all` | 获取近期记忆 |
| `flush` | no-op | REST 即时生效 |

**连接选择逻辑**（`MemosCoreBridge.__init__`）：
1. 优先：检测环境变量 `MEMOS_API_URL` → 使用 HTTP transport
2. 回退：尝试 TCP daemon (port 18992)
3. 最终回退：spawn stdio 子进程

```python
class MemosCoreBridge:
    def __init__(self):
        http_url = os.environ.get("MEMOS_API_URL", "")
        if http_url:
            self._transport = _HttpTransport(http_url)
            if self.ping():
                return   # ← 我们走这条路径
        # ... fallback to TCP, then stdio ...
```

通过 systemd drop-in 将 `MEMOS_API_URL=http://localhost:8000` 注入 Hermes gateway 进程环境。

### 3.3 适配过程中解决的问题

**Bug 1：Pydantic `internal_info` 类型不匹配**  
Neo4j 返回的 `internal_info` 字段为 JSON 字符串，而 MemOS Pydantic model 要求 `dict`。所有 search 结果因此被校验层抛弃，返回空。  
→ **修复**：patch `from_dict` 方法，增加 `isinstance(val, str) → json.loads(val)` 兼容。

**Bug 2：Embedding 超时**  
默认超时 5 秒，llama-server 在 CPU 上处理 1024 维向量偶发超时。  
→ **修复**：设置环境变量 `MOS_EMBEDDER_TIMEOUT=30`。

**Bug 3：版本字符串 stale**  
`server_api.py` 硬编码 `version="1.0.1"`，但实际运行的是 v2.0.14 代码。  
→ **修复**：patch 为 `version="2.0.14"`。

### 3.4 Hermes 如何使用记忆

```
用户发送消息
      │
      ▼
Hermes Gateway
      │
      ├── sync_turn: 提取上轮对话 → ingest → MemOS /product/add
      │
      └── 构造 system prompt
           │
           ├── memory_search(query, top_k=8)
           │      │
           │      ▼
           │   _HttpTransport.search()
           │      │
           │      ▼
           │   POST /product/search + 格式转换
           │
           └── 注入结果到 context → LLM 生成回复
```

---

## 四、Claude Code MCP 集成（附加）

为让 Claude Code 也能使用同一套记忆系统，构建了独立的 MCP Server：

**文件**：`~/.hermes/mcp-servers/memos-mcp/server.py`（~280 行）  
**技术**：Python + FastMCP + stdio transport  
**数据通路**：MemOS REST API（端口 8000）+ Neo4j HTTP API（端口 7474）

**15 个工具**：

| 工具 | 后端 | 功能 |
|------|------|------|
| `memos_health` | `GET /health` | 健康检查 |
| `memos_search` | `POST /product/search` | 语义搜索 |
| `memos_add` | `POST /product/add` | 添加记忆 |
| `memos_stats` | Neo4j HTTP | 记忆统计（按类型） |
| `memos_list` | Neo4j HTTP | 浏览最近记忆 |
| `memos_get_all` | `POST /product/get_all` | 获取全部记忆 |
| `memos_get` | `POST /product/get_memory_by_ids` | 按 ID 批量获取 |
| `memos_delete` | `POST /product/delete_memory*` | 删除记忆 |
| `memos_recover` | `POST /product/recover_memory_by_record_id` | 恢复已删记忆 |
| `memos_feedback` | `POST /product/feedback` | 记忆修正反馈 |
| `memos_suggestions` | `POST /product/suggestions` | 上下文记忆建议 |
| `memos_chat` | `POST /product/chat/complete` | RAG 对话 |
| `memos_dashboard` | `POST /product/get_memory_dashboard` | 仪表盘统计 |
| `memos_scheduler` | `GET /product/scheduler/allstatus` | 任务调度状态 |
| `memos_exist_cube` | `POST /product/exist_mem_cube_id` | 检查 Cube 存在 |

覆盖 MemOS 24 个端点中实用的 15 个（~88%）。  
未覆盖的 `/chat/stream/*` 等 SSE 端点因 MCP stdio transport 不适用跳过了。

Claude Code 配置 (`~/.claude/mcp.json`)：
```json
{
  "mcpServers": {
    "memos": {
      "command": "python3",
      "args": ["/home/ayin/.hermes/mcp-servers/memos-mcp/server.py"]
    }
  }
}
```

---

## 五、当前不足

| 功能 | 状态 | 原因 |
|------|:--:|------|
| KB 知识库 | ❌ | MemOS v2.0.14 codebase 无此模块 |
| Image REST 端点 | ❌ | 图片解析管线（`image_parser.py`）存在但无对外路由 |
| 多 Cube 管理 | ⚠️ | 端点存在但无管理工具 |
| DeepSeek 余额 | ⚠️ | 偶尔 `402 Insufficient Balance`，仅影响记忆写入 |

---

## 六、总结

| 指标 | 数值 |
|------|------|
| 记忆总量 | 706 条（LongTermMemory 334 / UserMemory 210 / SkillMemory 161 / WorkingMemory 1） |
| 语义搜索延迟 | ~0.18s |
| 新增记忆时延 | ~15-50s（LLM 提取，异步） |
| 新增代码量 | `_HttpTransport` ~140 行 + MCP ~280 行 |
| 磁盘占用 | Neo4j + Qdrant + embedding 模型 ~3GB |
| 内存占用 | Neo4j ~1GB + Qdrant ~200MB + embedding ~400MB ≈ 1.6GB |

**关键设计决策**：
- 不新建 provider，在现有 `bridge_client.py` 中加 transport adapter —— 改动最小，上层 389 行 provider 逻辑零修改
- Embedding 本地化（`bge-large-zh-v1.5` via `llama-server`）—— 隐私好、零延迟、零费用
- LLM 与记忆系统分离 —— 主对话模型可随意切换，不影响记忆存储
