#!/usr/bin/env bash
# ============================================================================
# 社区发布包生成脚本
# ============================================================================
# 将当前仓库打包为社区可用的纯净版本，去掉个人配置和系统特定信息。
#
# 用法:
#   bash scripts/package-community.sh [version]
#
# 示例:
#   bash scripts/package-community.sh v1.0.0
#   → 输出: /tmp/hermes-memos-integration-v1.0.0.tar.gz
# ============================================================================

set -euo pipefail

PROJECT="hermes-memos-integration"
VERSION="${1:-v1.0.0-$(date +%Y%m%d)}"
OUTDIR="/tmp/${PROJECT}-${VERSION}"
TARBALL="/tmp/${PROJECT}-${VERSION}.tar.gz"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== 生成社区发布包 ${VERSION} ==="
echo "源: $REPO_DIR"
echo "输出: $TARBALL"
echo ""

# 清理上次产物
rm -rf "$OUTDIR" "$TARBALL"

# 1. 复制核心内容
mkdir -p "$OUTDIR"

# adapter 核心
cp -r "$REPO_DIR/memos-plugin" "$OUTDIR/"
rm -f "$OUTDIR/memos-plugin/adapters/hermes/scripts/acceptance-test.py"

# patches
cp -r "$REPO_DIR/patches" "$OUTDIR/"

# 文档
cp "$REPO_DIR/LICENSE" "$OUTDIR/"
cp "$REPO_DIR/CONTRIBUTING.md" "$OUTDIR/"
cp "$REPO_DIR/ARCHITECTURE.md" "$OUTDIR/"

# 2. 写入社区版 README
cat > "$OUTDIR/README.md" << 'README_EOF'
# MemOS-Hermes Integration

> Self-hosted semantic memory for Hermes Agent — powered by MemOS (Neo4j + Qdrant).

Replace Hermes' default SQLite memory backend with a full graph+vector memory system,
via a thin HTTP transport adapter. No plugin modifications needed.

## Architecture

```
Hermes Agent
  └─ MemTensorProvider (unchanged)
       └─ MemosCoreBridge
            ├─ _HttpTransport → MemOS REST API  ← primary
            ├─ _TcpTransport  → Node daemon     ← fallback
            └─ _StdioTransport→ bridge.cts      ← last resort
```

## Quick Start

```bash
# 1. Copy plugin to Hermes
cp -r memos-plugin ~/.hermes/hermes-agent/plugins/memory/memtensor

# 2. Configure environment variable
mkdir -p ~/.config/systemd/user/hermes-gateway.service.d
cat > ~/.config/systemd/user/hermes-gateway.service.d/memos.conf << 'EOF'
[Service]
Environment="MEMOS_API_URL=http://localhost:8000"
EOF

# 3. Apply MemOS server-side patches
bash patches/apply-patches.sh

# 4. Restart gateway
systemctl --user daemon-reload
systemctl --user restart hermes-gateway
```

## Features

- **Transport auto-selection** — REST API preferred, TCP fallback, stdio last resort
- **Idempotent writes** — `session_id:turn_id` dedup key prevents duplicate memory
- **Deep health checks** — `GET /product/health/detail` probes all 5 dependency layers
- **Structured observability** — `[memtensor]` prefixed logs with timing

## Upgrading MemOS

```bash
cd ~/memos-server && git pull && bash patches/apply-patches.sh
```

## License

MIT
README_EOF

# 3. 写入纯净的 config.yaml.template
cat > "$OUTDIR/config.yaml.template" << 'CONFIG_EOF'
# Hermes Agent Configuration — MemOS Memory Provider
# Copy to config.yaml and fill in your own values.
memory:
  provider: memtensor
  mode: auto
  tool_name: memory_search
CONFIG_EOF

# 4. 写入 CHANGELOG (社区版)
cat > "$OUTDIR/CHANGELOG.md" << 'CHLOG_EOF'
# Changelog

## v1.0.0 — Initial community release

- HTTP transport adapter for MemOS Full Server (Docker: Neo4j + Qdrant)
- Idempotent writes with 30s dedup cache
- Deep health check endpoint (`GET /product/health/detail`)
- Structured `[memtensor]` logging across all memory operations
- 15-item acceptance test suite
- MemOS server-side patch management (`patches/apply-patches.sh`)
CHLOG_EOF

# 5. 打包
cd /tmp
tar czf "$TARBALL" "${PROJECT}-${VERSION}"

echo "=== 完成 ==="
echo "发布包: $TARBALL"
echo "大小: $(du -h "$TARBALL" | cut -f1)"
echo ""
echo "发布到 GitHub:"
echo "  gh release create ${VERSION} ${TARBALL} --title \"${VERSION}\" --notes \"See CHANGELOG.md for details\""
