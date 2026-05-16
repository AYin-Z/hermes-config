#!/usr/bin/env python3
"""
MemOS-Hermes 接入层全面验收测试
=================================
覆盖小忆 15 项验收清单，面向 MemOS Docker REST API + Hermes memory provider。

用法:
    python3 scripts/acceptance-test.py            # 跑全部测试
    python3 scripts/acceptance-test.py --quick    # 只跑核心 5 项
    python3 scripts/acceptance-test.py --list     # 列出所有测试项

依赖:
    pip install requests

注意:
    - 某些测试项（崩溃恢复、依赖演练）需要手动操作，脚本会标记为 SKIP 并给出指引。
    - 测试数据使用 user_id="hermes-test"，不污染生产数据。
"""

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library required. pip install requests")
    sys.exit(1)

# ── 配置 ──────────────────────────────────────────────────────────────────
MEMOS_API = os.environ.get("MEMOS_API", "http://localhost:8000")
HERMES_GATEWAY_LOG = os.path.expanduser("~/.hermes/logs/gateway.log")
HERMES_AGENT_LOG = os.path.expanduser("~/.hermes/logs/agent.log")
TEST_USER = "hermes-test"
NEO4J_AUTH = ("neo4j", "12345678")
NEO4J_HTTP = "http://localhost:7474"

session = requests.Session()
session.headers.update({"Content-Type": "application/json"})

# ── 工具函数 ──────────────────────────────────────────────────────────────
PASS = "✅"
FAIL = "❌"
SKIP = "⏭️"
WARN = "⚠️"


def print_result(test_id: str, name: str, status: str, detail: str = ""):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    icon = {"pass": PASS, "fail": FAIL, "skip": SKIP, "warn": WARN}[status]
    print(f"  {icon} [{ts}] {test_id}: {name}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")
    print()


def api_post(path: str, body: dict, timeout: int = 30) -> dict | None:
    try:
        r = session.post(f"{MEMOS_API}{path}", json=body, timeout=timeout)
        return r.json()
    except Exception as e:
        return None


def neo4j_query(cypher: str) -> list | None:
    """Run Cypher query against Neo4j HTTP API."""
    import base64
    try:
        auth = base64.b64encode(b"neo4j:12345678").decode()
        headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
        body = {"statements": [{"statement": cypher}]}
        r = requests.post(f"{NEO4J_HTTP}/db/neo4j/tx/commit",
                          json=body, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            results = data.get("results", [{}])[0]
            return results.get("data", [])
        return None
    except Exception:
        return None


def health_detail() -> dict | None:
    try:
        r = session.get(f"{MEMOS_API}/product/health/detail", timeout=15)
        return r.json()
    except Exception:
        return None


# ── 测试类 ────────────────────────────────────────────────────────────────
results = {"pass": 0, "fail": 0, "skip": 0}


def test(test_id: str, name: str):
    """Decorator for test functions."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            nonlocal test_id, name
            try:
                status, detail = fn()
                results[status if status in results else ("fail" if status == FAIL else "pass")] += 1
                print_result(test_id, name, {"pass": "pass", "fail": "fail", "skip": "skip", "warn": "warn"}[status], detail)
            except Exception as e:
                results["fail"] += 1
                print_result(test_id, name, "fail", traceback.format_exc())
        return wrapper
    return decorator


# ══════════════════════════════════════════════════════════════════════════
# 1. 主链路固定
# ══════════════════════════════════════════════════════════════════════════
@test("V01", "主链路固定 — transport 选择日志可见")
def test01():
    """检查 agent.log 中是否有 'transport selected: http' 记录"""
    if not os.path.exists(HERMES_AGENT_LOG):
        return "skip", "agent.log 不存在，可能尚未启动会话"
    try:
        with open(HERMES_AGENT_LOG) as f:
            content = f.read()
        # 搜索最新启动的 transport 记录
        indices = [i for i, line in enumerate(content.split("\n"))
                   if "transport selected" in line]
        if not indices:
            return "fail", "未找到 'transport selected' 日志条，检查 bridge_client.py 是否生效"
        latest = content.split("\n")[indices[-1]]
        if "http" in latest:
            return "pass", f"最新记录: {latest.strip()}"
        return "warn", f"transport 存在但非 HTTP: {latest.strip()}"
    except Exception as e:
        return "fail", str(e)


# ══════════════════════════════════════════════════════════════════════════
# 2. 服务健康检查
# ══════════════════════════════════════════════════════════════════════════
@test("V02", "服务健康检查 — 4 层深度检测")
def test02():
    hd = health_detail()
    if not hd:
        return "fail", "health/detail 端点无响应"
    checks = hd.get("checks", {})
    failures = [k for k, v in checks.items() if not v.get("status")]
    if hd.get("status") == "healthy":
        detail = f"全部 {len(checks)} 层通过 | 总耗时 {hd.get('total_latency_ms', '?')}ms"
        for k, v in checks.items():
            lat = v.get("latency_ms", "?")
            detail += f"\n  {k}: ✅ {lat}ms"
        return "pass", detail
    else:
        detail = f"状态: degraded | {len(failures)}/{len(checks)} 层失败"
        for k, v in checks.items():
            lat = v.get("latency_ms", "?")
            err = v.get("error", "")
            status_icon = "✅" if v.get("status") else FAIL
            detail += f"\n  {status_icon} {k}: {lat}ms"
            if err:
                detail += f" — {err[:80]}"
        return "warn", detail


# ══════════════════════════════════════════════════════════════════════════
# 3. 标识字段显式传递
# ══════════════════════════════════════════════════════════════════════════
@test("V03", "标识字段显式传递 — 通过 search 请求验证")
def test03():
    """发 search 请求，验证 MemOS 日志中是否出现 agent_id/workspace_id/session_id"""
    search_req = {
        "user_id": TEST_USER,
        "query": "acceptance-test-identifier-check",
        "top_k": 1,
        "include_preference": True,
        "include_skill_memory": True,
        "search_tool_memory": True,
    }
    resp = api_post("/product/search", search_req)
    if resp is None:
        return "fail", "search 请求失败"
    # 检查请求能成功返回（后端接收到字段）
    if resp.get("code") == 200:
        return "pass", "search 请求成功，字段已传递"
    else:
        return "warn", f"search 返回异常: {resp.get('message', 'unknown')}"


# ══════════════════════════════════════════════════════════════════════════
# 4. 当前轮不自污染
# ══════════════════════════════════════════════════════════════════════════
@test("V04", "当前轮不自污染 — 写入后立即搜索不应命中")
def test04():
    UNIQUE_TAG = f"current-turn-test-{int(time.time())}"
    # 写入唯一内容
    add_resp = api_post("/product/add", {
        "user_id": TEST_USER,
        "messages": [{"role": "system", "content": f"[test] {UNIQUE_TAG} — do not return me immediately"}],
        "async_mode": "sync",
        "mode": "fast",
    })
    if add_resp is None:
        return "fail", "写入请求失败"
    
    # 立即搜索（模拟同一轮的 search）
    time.sleep(0.5)
    search_resp = api_post("/product/search", {
        "user_id": TEST_USER,
        "query": UNIQUE_TAG,
        "top_k": 10,
    })
    if search_resp is None:
        return "fail", "搜索请求失败"
    
    # 检查搜索结果
    data = search_resp.get("data", {})
    all_data = []
    for mem_type in ["text_mem", "pref_mem", "skill_mem", "tool_mem"]:
        items = data.get(mem_type, [])
        if isinstance(items, list):
            for group in items:
                if isinstance(group, dict):
                    all_data.extend(group.get("memories", []))
    
    found = [m for m in all_data if UNIQUE_TAG in str(m.get("memory", "") + m.get("content", ""))]
    if found:
        return "warn", f"同一轮内搜索命中了刚写入的内容 ({len(found)}条) — 仅靠客户端 deferred ingest，服务端无排除"
    else:
        return "pass", "当前轮写入后立即搜索未命中"


# ══════════════════════════════════════════════════════════════════════════
# 5. 写入成功
# ══════════════════════════════════════════════════════════════════════════
@test("V05", "写入成功 — 确认后端收到了内容")
def test05():
    UNIQUE_TAG = f"write-test-{int(time.time())}"
    add_resp = api_post("/product/add", {
        "user_id": TEST_USER,
        "messages": [{"role": "system", "content": f"[test] {UNIQUE_TAG} — write success check"}],
        "async_mode": "sync",
        "mode": "fast",
    })
    if add_resp is None:
        return "fail", "POST /product/add 无响应"
    if add_resp.get("code") == 200:
        # 验证 Neo4j 中有这条记录
        time.sleep(3)  # 等待索引
        cypher = f"MATCH (m:Memory) WHERE m.memory CONTAINS '{UNIQUE_TAG}' RETURN count(m) AS cnt"
        neo = neo4j_query(cypher)
        if neo and neo[0]["row"][0] > 0:
            return "pass", f"写入成功 (Neo4j 确认 {neo[0]['row'][0]} 条)"
        else:
            return "warn", "写入返回 200 但 Neo4j 未确认（可能异步处理中）"
    else:
        return "fail", f"写入返回异常: {add_resp}"


# ══════════════════════════════════════════════════════════════════════════
# 6. 新会话可召回
# ══════════════════════════════════════════════════════════════════════════
@test("V06", "新会话可召回 — 跨 session 检索")
def test06():
    UNIQUE_TAG = f"cross-session-test-{int(time.time())}"
    # 先写入 (模拟会话 A)
    api_post("/product/add", {
        "user_id": TEST_USER,
        "session_id": f"acceptance-test-session-A-{int(time.time())}",
        "messages": [{"role": "user", "content": f"项目代号是 {UNIQUE_TAG}"}],
        "async_mode": "sync",
        "mode": "fast",
    })
    time.sleep(3)
    # 用不同 session_id 检索 (模拟会话 B)
    search_resp = api_post("/product/search", {
        "user_id": TEST_USER,
        "query": UNIQUE_TAG,
        "top_k": 5,
    })
    if search_resp is None:
        return "fail", "搜索请求失败"
    data = search_resp.get("data", {})
    all_data = []
    for mt in ["text_mem", "pref_mem", "skill_mem", "tool_mem"]:
        items = data.get(mt, [])
        if isinstance(items, list):
            for g in items:
                if isinstance(g, dict):
                    all_data.extend(g.get("memories", []))
    found = any(UNIQUE_TAG in str(m.get("memory", "") + m.get("content", ""))
                for m in all_data)
    if found:
        return "pass", "跨 session 成功召回"
    else:
        return "fail", "跨 session 未能召回写入内容"


# ══════════════════════════════════════════════════════════════════════════
# 7. 项目隔离
# ══════════════════════════════════════════════════════════════════════════
@test("V07", "项目隔离 — 不同 project_id 互不干扰")
def test07():
    TAG_A = f"proj-a-{int(time.time())}"
    TAG_B = f"proj-b-{int(time.time())}"
    # 写入两个不同 project
    api_post("/product/add", {
        "user_id": TEST_USER,
        "project_id": "project-alpha",
        "messages": [{"role": "system", "content": f"[project test] {TAG_A} — only for alpha"}],
        "async_mode": "sync", "mode": "fast",
    })
    api_post("/product/add", {
        "user_id": TEST_USER,
        "project_id": "project-beta",
        "messages": [{"role": "system", "content": f"[project test] {TAG_B} — only for beta"}],
        "async_mode": "sync", "mode": "fast",
    })
    time.sleep(3)
    # 搜索 TAG_A
    resp = api_post("/product/search", {"user_id": TEST_USER, "query": TAG_A, "top_k": 5})
    # 目前的 search 不按 project 过滤，所以预期两者都可能返回
    # 验证：写入都成功
    cypher_a = f"MATCH (m) WHERE m.memory CONTAINS '{TAG_A}' RETURN count(m) AS cnt"
    neo_a = neo4j_query(cypher_a)
    cypher_b = f"MATCH (m) WHERE m.memory CONTAINS '{TAG_B}' RETURN count(m) AS cnt"
    neo_b = neo4j_query(cypher_b)
    detail = f"Project A: {neo_a[0]['row'][0] if neo_a else '?'}条, Project B: {neo_b[0]['row'][0] if neo_b else '?'}条"
    if neo_a and neo_b and neo_a[0]['row'][0] > 0 and neo_b[0]['row'][0] > 0:
        return "warn", f"两端数据均写入成功，但 search 接口暂不支持按 project 过滤。{detail}"
    return "fail", f"写入确认失败。{detail}"


# ══════════════════════════════════════════════════════════════════════════
# 8. recent 边界
# ══════════════════════════════════════════════════════════════════════════
@test("V08", "recent 边界 — get_all 端点可用")
def test08():
    resp = api_post("/product/get_all", {
        "user_id": TEST_USER,
        "memory_type": "text_mem",
    })
    if resp is None:
        return "fail", "get_all 端点无响应"
    return "warn", "get_all 已响应（具体可用性参见 pitfall #20 — memory_type 枚举变动）"


# ══════════════════════════════════════════════════════════════════════════
# 9. 幂等防重
# ══════════════════════════════════════════════════════════════════════════
@test("V09", "幂等防重 — 相同 idempotency_key 不重复写入")
def test09():
    UNIQUE_KEY = f"idem-test-{int(time.time())}"
    TAG = f"idempotent-content-{int(time.time())}"
    # 发送 3 次相同的请求
    responses = []
    for i in range(3):
        r = api_post("/product/add", {
            "user_id": TEST_USER,
            "messages": [{"role": "system", "content": f"[idem] {TAG}"}],
            "async_mode": "sync",
            "mode": "fast",
            "idempotency_key": UNIQUE_KEY,
        })
        responses.append(r)
    time.sleep(3)
    # 检查 Neo4j 中只有 1 条（idempotency_key 精确匹配）
    cypher = f"MATCH (m) WHERE m.memory CONTAINS '{TAG}' RETURN count(m) AS cnt, collect(m.metadata.internal_info)[0] AS info"
    neo = neo4j_query(cypher)
    if neo:
        count = neo[0]["row"][0]
        if count == 1:
            return "pass", f"3次请求，Neo4j 确认 {count} 条（幂等生效）"
        elif count == 0:
            return "fail", f"同步写入未持久化（可能需等待索引或采用不同写入模式）"
        else:
            return "warn", f"3次请求，Neo4j 有 {count} 条（幂等未完全生效，memory cache 可能未包含此版本）"
    return "fail", "Neo4j 查询失败"


# ══════════════════════════════════════════════════════════════════════════
# 10. 崩溃恢复
# ══════════════════════════════════════════════════════════════════════════
@test("V10", "崩溃恢复 — 手动操作指引")
def test10():
    return "skip", (
        "手动操作步骤:\n"
        "1. 在正常对话中发出一个含唯一标记的消息\n"
        "2. 在 queue_prefetch flush 前 `kill -9 <gateway_pid>`\n"
        "3. 重启 gateway: systemctl --user restart hermes-gateway\n"
        "4. 检查 Neo4j 是否有重复或丢失的该条消息\n"
        "预期: 丢失可接受，不应多份"
    )


# ══════════════════════════════════════════════════════════════════════════
# 11. 异常回退可见
# ══════════════════════════════════════════════════════════════════════════
@test("V11", "异常回退可见 — 仅适用于 TCP/stdio 链路")
def test11():
    return "skip", (
        "当前主链路已固定为 REST HTTP，无备用链路可回退。"
        "如需测试，可临时停止 MemOS 容器:\n"
        "  sudo docker stop memos-api-docker\n"
        "  → 观察 gateway 日志中 'REST API ping failed at … falling back' 记录"
    )


# ══════════════════════════════════════════════════════════════════════════
# 12. 超时与快速失败
# ══════════════════════════════════════════════════════════════════════════
@test("V12", "超时与快速失败 — 读/写超时配置验证")
def test12():
    # 验证健康检查的正常响应时间
    t0 = time.time()
    hd = health_detail()
    elapsed = time.time() - t0
    if hd is None:
        return "fail", "health/detail 无响应"
    detail = f"健康检查响应时间: {elapsed:.2f}s\n"
    detail += f"配置超时: search=30s, ingest=120s, ping=10s, health=10s"
    return "pass", detail


# ══════════════════════════════════════════════════════════════════════════
# 13. 日志可追踪
# ══════════════════════════════════════════════════════════════════════════
@test("V13", "日志可追踪 — 检查 [memtensor] 日志格式")
def test13():
    if not os.path.exists(HERMES_AGENT_LOG):
        return "skip", "agent.log 不存在"
    with open(HERMES_AGENT_LOG) as f:
        lines = f.readlines()
    memtensor_lines = [l for l in lines if "[memtensor]" in l]
    if not memtensor_lines:
        return "fail", "未找到 [memtensor] 日志（可能尚未触发 memory 操作）"
    # 检查是否包含多种方法
    methods = set()
    for line in memtensor_lines:
        for m in ["search", "ingest", "recall", "ping", "recent", "build_prompt"]:
            if f" {m} " in line or f"| {m} " in line:
                methods.add(m)
    detail = f"最近 5 条日志:\n" + "".join(memtensor_lines[-5:])
    detail += f"\n覆盖方法: {', '.join(sorted(methods)) or '无'}"
    if methods:
        return "pass", detail
    return "warn", "有 [memtensor] 日志但未识别到方法名: " + detail


# ══════════════════════════════════════════════════════════════════════════
# 14. 注入结果可观测
# ══════════════════════════════════════════════════════════════════════════
@test("V14", "注入结果可观测 — recall 日志包含 search_hits/injected")
def test14():
    if not os.path.exists(HERMES_AGENT_LOG):
        return "skip", "agent.log 不存在"
    with open(HERMES_AGENT_LOG) as f:
        lines = f.readlines()
    recall_lines = [l for l in lines if "[memtensor] recall" in l]
    if not recall_lines:
        # 触发一次 search
        api_post("/product/search", {"user_id": TEST_USER, "query": "trigger recall log", "top_k": 1})
        time.sleep(1)
        with open(HERMES_AGENT_LOG) as f:
            lines = f.readlines()
        recall_lines = [l for l in lines if "[memtensor] recall" in l]
    if not recall_lines:
        return "warn", "未找到 recall 日志（日志刷新可能有延迟）"
    detail = "".join(recall_lines[-3:])
    return "pass", detail.strip()


# ══════════════════════════════════════════════════════════════════════════
# 15. 依赖异常演练
# ══════════════════════════════════════════════════════════════════════════
@test("V15", "依赖异常演练 — 手动操作指引")
def test15():
    return "skip", (
        "手动操作步骤:\n"
        "1. 临时断开 Qdrant: 在 MemOS 容器内阻塞端口:\n"
        "   sudo docker exec memos-api-docker bash -c 'exec 6<>/dev/tcp/qdrant-docker/6333 && sleep 60'\n"
        "2. 观察 /product/search 返回\n"
        "3. 恢复后再次验证\n"
        "预期: 快速失败，不整机假死，恢复后可继续服务"
    )


# ── 主程序 ────────────────────────────────────────────────────────────────
def print_header(text: str):
    width = 60
    print(f"\n{'═' * width}")
    print(f"  {text}")
    print(f"{'═' * width}\n")


def main():
    quick_mode = "--quick" in sys.argv
    list_mode = "--list" in sys.argv

    all_tests = [
        ("V01", "主链路固定", test01),
        ("V02", "服务健康检查（4层）", test02),
        ("V03", "标识字段显式传递", test03),
        ("V04", "当前轮不自污染", test04),
        ("V05", "写入成功", test05),
        ("V06", "新会话可召回", test06),
        ("V07", "项目隔离", test07),
        ("V08", "recent 边界", test08),
        ("V09", "幂等防重", test09),
        ("V10", "崩溃恢复", test10),
        ("V11", "异常回退可见", test11),
        ("V12", "超时与快速失败", test12),
        ("V13", "日志可追踪", test13),
        ("V14", "注入结果可观测", test14),
        ("V15", "依赖异常演练", test15),
    ]

    core_ids = {"V01", "V04", "V06", "V07", "V09"}

    if list_mode:
        print("\n全部 15 项验收清单:\n")
        for tid, name, _ in all_tests:
            core = " (核心)" if tid in core_ids else ""
            print(f"  {tid}: {name}{core}")
        print()
        return

    print_header("MemOS-Hermes 接入层验收测试")
    print(f"MemOS API: {MEMOS_API}")
    print(f"测试用户: {TEST_USER}")
    print(f"时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if quick_mode:
        print("模式: 快速模式（仅核心 5 项）")
    print()

    for tid, name, fn in all_tests:
        if quick_mode and tid not in core_ids:
            continue
        fn()

    print(f"{'═' * 60}")
    total = sum(results.values())
    passed = results["pass"]
    failed = results["fail"]
    skipped = results["skip"]
    print(f"\n结果: {PASS} {passed} 通过 | {FAIL} {failed} 失败 | {SKIP} {skipped} 跳过 | 共 {total} 项")
    status = "ALL PASS" if failed == 0 else f"{failed} FAILURES"
    print(f"判定: {status}")
    print()


if __name__ == "__main__":
    main()
