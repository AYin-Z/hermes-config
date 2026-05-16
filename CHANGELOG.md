# Changelog

> Hermes 配置仓库 + MemOS 接入层的变更记录。

## 2026-05-16 — v1 hardening + 社区打包

**状态**: ✅ 可用（小忆 15 项验收，核心 5 项通过）

### 接入层硬化

| 改动 | 文件 | 说明 |
|------|------|------|
| Transport 日志 | `bridge_client.py` | `MemOS transport selected: http (rest_api) → url` |
| 标识字段注入 | `bridge_client.py` | 每个请求带 `agent_id/workspace_id/session_id` |
| 幂等键 (adapter) | `bridge_client.py` + `__init__.py` | `session_id:turn_id` 构造幂等键 |
| 幂等键 (服务端) | `product_models.py` + `add_handler.py` | 30s 内存去重缓存 |
| 深度健康检查 | `server_router.py` | `GET /product/health/detail`，5 层探测 |
| 结构化日志 | `bridge_client.py` + `__init__.py` | `[memtensor] search/ingest/recall/ping` |
| 验收脚本 | `scripts/acceptance-test.py` | 15 项全覆盖 |

### 社区发布准备

- 新增 `LICENSE` (MIT), `CONTRIBUTING.md`
- 新增 `scripts/package-community.sh` — 一键生成纯净发布包
- `README.md` 双用途: 个人配置说明 + 社区项目入口
- `ARCHITECTURE.md` 统架构文档

### 已跳过

- 服务端当前轮排除 (SearchHandler 内部复杂，客户端 deferred ingest 已提供第一层保险)

## 初始版本 (2026-05-13 前)

- 初始 Hermes 配置 + MemOS HTTP adapter
- 系统定制记录见 `CUSTOMIZATION.md`
