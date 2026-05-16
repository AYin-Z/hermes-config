#!/usr/bin/env bash
# ============================================================================
# MemOS-Hermes 服务端补丁应用脚本
# 在 `git pull` 升级 MemOS 后运行，恢复所有自定义改动
# ============================================================================
# 用法:
#   cd ~/memos-server
#   git pull origin main
#   bash ~/hermes-config/patches/apply-patches.sh
#
# 验证:
#   curl http://localhost:8000/product/health/detail
#   → 应返回包含 5 层 checks 的健康报告
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_DIR="$SCRIPT_DIR"
MEMOS_SRC=~/memos-server/src

echo "=== 应用 MemOS 服务端补丁 ==="
echo "源: $MEMOS_SRC"
echo "补丁: $PATCH_DIR"
echo ""

# 补丁 1: APIADDRequest.idempotency_key 字段
echo "[1/3] idempotency_key field..."
cd "$MEMOS_SRC"
if grep -q "idempotency_key" src/memos/api/product_models.py 2>/dev/null; then
    echo "  ✅ 已存在，跳过"
else
    patch -p1 < "$PATCH_DIR/001-idempotency-key.patch"
    echo "  ✅ 已应用"
fi

# 补丁 2: AddHandler 去重缓存
echo "[2/3] idempotency cache in AddHandler..."
cd "$MEMOS_SRC"
if grep -q "_idempotency_cache" src/memos/api/handlers/add_handler.py 2>/dev/null; then
    echo "  ✅ 已存在，跳过"
else
    patch -p1 < "$PATCH_DIR/001-add-idempotency-cache.patch"
    echo "  ✅ 已应用"
fi

# 补丁 3: GET /product/health/detail 端点
echo "[3/3] health detail endpoint..."
cd "$MEMOS_SRC"
if grep -q "def health_detail" src/memos/api/routers/server_router.py 2>/dev/null; then
    echo "  ✅ 已存在，跳过"
else
    patch -p1 < "$PATCH_DIR/002-health-detail.patch"
    echo "  ✅ 已应用"
fi

echo ""
echo "=== 验证 ==="
echo "运行: curl --noproxy '*' --max-time 10 http://localhost:8000/product/health/detail"
echo "预期: {\"status\":\"healthy\",\"checks\":{\"api_alive\":...,\"neo4j\":...,\"qdrant\":...,\"write_chain\":...,\"search_chain\":...}}"
echo ""
echo "全部补丁应用完成。"
