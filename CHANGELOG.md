# Changelog

> MemOS-Hermes 接入层的变更记录。每次升级后更新。
> 对应上游 Hermes 版本和 MemOS 版本参见各条记录。

## 2026-05-16 — 接入层硬化

**Hermes**: gateway-main @aecbd0d
**MemOS**: v2.0.14 (Docker)
**状态**: ✅ 可用（小忆 15 项验收，核心 5 项通过）

### 新增

| 改动 | 文件 | 说明 |
|------|------|------|
| Transport 日志 | `bridge_client.py` | `MemOS transport selected: http (rest_api) → url` |
| 标识字段注入 | `bridge_client.py` | 每个请求带 `agent_id/workspace_id/session_id` |
| 幂等键 (adapter) | `bridge_client.py` + `__init__.py` | `session_id:turn_id` 构造幂等键 |
| 幂等键 (服务端) | `product_models.py` + `add_handler.py` | 30s 内存去重缓存 |
| 深度健康检查 | `server_router.py` | `GET /product/health/detail`，5 层探测 |
| 结构化日志 | `bridge_client.py` + `__init__.py` | `[memtensor] search/ingest/recall/ping` 统一格式 |
| 验收脚本 | `scripts/acceptance-test.py` | 15 项全覆盖，支持 `--quick` 模式 |

### 已跳过

- 服务端当前轮排除 (SearchHandler 内部复杂，客户端 deferred ingest 已提供第一层保险)

### 已知限制

- `GET /product/get_all` 的 `memory_type` 枚举在 v2.0.14 有变动 (`text_mem`/`act_mem`/`param_mem`/`para_mem` 替代 `LongTermMemory`)
- Project 隔离 search 不支持 — `project_id` 可写入但 search 不按此过滤
- Pydantic `TextualMemoryItem.from_dict` 在处理 Neo4j JSON 字符串字段时需手动 patch（见 `references/pydantic-internal-info-fix.md`）

### 升级注意事项

`git pull` 后运行:

```bash
bash ~/hermes-config/patches/apply-patches.sh
```

三个服务端文件会被覆盖：`product_models.py`、`add_handler.py`、`server_router.py`

## 2026-05-13 — 初始 Hermes 定制化

参见 `CUSTOMIZATION.md`（独立文件，已归档系统级定制，非本 repo 范围）
