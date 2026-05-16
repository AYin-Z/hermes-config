# Hermes Config — MemOS 自托管记忆接入

> 这是我的 Hermes Agent 完整配置文件仓库。  
> 同时包含一个可独立使用的 **MemOS-Hermes 接入层**，面向社区开源。

---

## 这个仓库是什么

本仓库服务于两个目的：

### 1. 我的 Hermes 配置备份（主用途）

`config.yaml` 和 `systemd/` 下的文件是我个人服务器的运行时配置，通过 git 做版本管理和回滚。个人定制记录在 `CUSTOMIZATION.md`。

### 2. MemOS-Hermes 接入方案（社区用途）

`memos-plugin/adapters/hermes/` 下的 adapter 代码，加上 `patches/` 里的服务端补丁，构成一个可复用的 **Hermes ↔ MemOS 自托管记忆接入层**。

这套方案的核心思路：

- **只换 Transport**，不动 Hermes 上层的 `MemoryProvider` 接口
- **REST 优先**，TCP 备选，stdio 兜底的三层回退
- **幂等写入**、**深度健康检查**、**结构化日志**等硬化特性

## 社区发布

```bash
bash scripts/package-community.sh v1.0.0
```

生成 `/tmp/hermes-memos-integration-v1.0.0.tar.gz`，不包含个人配置，可直接发布。

### 发布到 GitHub Releases

```bash
gh release create v1.0.0 /tmp/hermes-memos-integration-v1.0.0.tar.gz \
  --title "v1.0.0" \
  --notes "Initial community release: HTTP transport adapter for MemOS Full Server"
```

## 仓库结构

```
hermes-config/
├── config.yaml                    # 我的 Hermes 运行时配置（已脱敏）
├── CUSTOMIZATION.md               # 个人定制记录
├── memos-plugin/adapters/hermes/  # 核心 adapter 代码
│   ├── __init__.py                # MemTensorProvider
│   ├── bridge_client.py           # MemosCoreBridge + 3种 Transport
│   ├── config.py / daemon_manager.py
│   └── scripts/
│       ├── acceptance-test.py     # 15项验收测试
│       └── package-community.sh   # 社区发布包生成
├── patches/                       # MemOS 服务端补丁
│   ├── apply-patches.sh
│   └── *.patch
├── references/                    # 参考文档
├── systemd/                       # 部署配置 (drop-in)
├── LICENSE / CONTRIBUTING.md      # 社区项目文件
├── README.md / ARCHITECTURE.md    # 本文档
└── CHANGELOG.md                   # 变更记录
```

## 核心设计

| 设计决策 | 说明 |
|---------|------|
| Transport 层隔离 | 所有变化在 `bridge_client.py` 内，上层零改动 |
| systemd drop-in | `MEMOS_API_URL` 通过 drop-in 注入，不被 gateway 自动更新覆盖 |
| Deferred Ingest | 客户端先搜后写，确保当前轮不自污染 |
| 幂等写入 | `session_id:turn_id` 幂等键，服务端 30s 内存去重 |
| 结构化日志 | `[memtensor] method | key=val | took=Nms` |
| 深度健康 | `/product/health/detail` 探测全部 5 层 |
