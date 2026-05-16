# Hermes Config — MemOS 自托管接入层

> **Hermes Agent ↔ MemOS Full Server 的自托管接入方案。**
>
> 只换 Transport，不动 Provider，对接 Neo4j + Qdrant 图谱+向量记忆。

[中文文档] · [Architecture](ARCHITECTURE.md) · [Changelog](CHANGELOG.md)

---

## 项目定位

这是一个**宿主无关、后端可替换**的接入层标准化方案。核心思路：

- **不改 Hermes 上层 Provider** — 所有变化收敛在 Transport 层（~140 行 `_HttpTransport`）
- **不依赖官方 Local Plugin** — 绕过 Node.js daemon + SQLite，直连 Docker REST API
- **三层回退** — REST 优先，TCP 备选，stdio 兜底

## 结构

```
hermes-config/
├── memos-plugin/adapters/hermes/  # 核心: Hermes ↔ MemOS adapter
│   ├── __init__.py                # MemTensorProvider (457行)
│   ├── bridge_client.py           # MemosCoreBridge + 3种 Transport (380行)
│   ├── config.py                  # 配置: OWNER, 端口, 路径
│   ├── daemon_manager.py          # Node daemon 生命周期
│   ├── plugin.yaml                # 插件清单
│   └── scripts/
│       └── acceptance-test.py      # 15项验收测试
├── systemd/                       # 部署配置
│   ├── hermes-gateway.service
│   └── hermes-gateway.service.d/
│       └── memos-url.conf          # MEMOS_API_URL 环境变量注入
├── patches/                       # MemOS 服务端补丁 (git pull后重补)
│   ├── apply-patches.sh           # 一键恢复脚本
│   ├── 001-idempotency-key.patch
│   ├── 001-add-idempotency-cache.patch
│   └── 002-health-detail.patch
├── references/                    # 参考文档
│   └── ...
├── plans/                         # 实施计划
│   ├── 2026-05-16_2215-memos-hardening-plan.md
│   └── ... (历史计划)
├── config.yaml                    # Hermes 配置 (已脱敏)
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
└── .gitignore
```

## 快速开始

### 前置条件

- MemOS Full Server v2.0.14+ 已部署 (Docker Compose: Neo4j + Qdrant + memos-api)
- Hermes Agent 已安装
- `MEMOS_API_URL=http://localhost:8000` 已注入 gateway 环境变量

### 部署 adapter

```bash
# 从本仓库复制 adapter 到 Hermes 插件目录
cp -r memos-plugin ~/.hermes/

# 配置 memory provider
echo 'memory.provider: memtensor' >> ~/.hermes/config.yaml

# 重启 gateway
systemctl --user restart hermes-gateway
```

### 应用服务端补丁

```bash
bash patches/apply-patches.sh
```

### 验收

```bash
cd memos-plugin/adapters/hermes/scripts
python3 acceptance-test.py --quick
```

## 升级说明

### MemOS 上游升级

```bash
cd ~/memos-server
git pull origin main
bash ~/hermes-config/patches/apply-patches.sh
sudo docker compose up -d --build
```

### Hermes 升级

Adapter 在独立 git repo 中，不受 Hermes 升级影响。升级后重新复制 plugin 目录即可。

## 核心设计

| 设计决策 | 说明 |
|---------|------|
| Transport 层隔离 | 所有变化在 `bridge_client.py` 内，上层 `MemTensorProvider` 零改动 |
| systemd drop-in | `MEMOS_API_URL` 通过 drop-in 注入，不由 config.yaml 管理 |
| Deferred Ingest | 客户端先搜后写，确保当前轮不自污染 |
| 幂等写入 | `session_id:turn_id` 幂等键，服务端 30s 内存去重 |
| 结构化日志 | `[memtensor] method \| key=val \| took=Nms` 统一格式 |
| 深度健康检查 | 5 层探测: api / Neo4j / Qdrant / 写链 / 查链 |
