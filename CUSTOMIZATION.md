# Hermes 定制化记录

> 从零部署 Hermes Agent 以来，对基础系统的所有定制修改。
> 最后更新：2026-05-13

---

## 1. 核心代码修改（`hermes-agent/` 仓库内）

### 1.1 `tools/session_query.py` — 全新工具

- **日期**: 2026-05-13
- **动机**: Anthropic Managed Agents 的 `getEvents()` 启发 — 让 LLM 能主动查询 session 事件日志
- **功能**: 
  - 位置切片：`query="", offset=0, limit=50` 按插入顺序返回消息
  - 关键词搜索：`query="活期"` 在 content/tool_name/tool_calls 中 substring 匹配
  - 角色过滤：`role="user"`
  - 跨 session 查询：显式传 `session_id` 参数可查历史 session
- **注册**: `memory` toolset，与 `session_search` 同级
- **文件**: `tools/session_query.py`（196 行）

### 1.2 `model_tools.py` — session_id 透传

- **日期**: 2026-05-13
- **动机**: `handle_function_call()` 接收 `session_id` 但未传给 `registry.dispatch()`，导致工具 handler 无法获取当前 session ID
- **修改**: 两处 `registry.dispatch()` 调用各加一行 `session_id=session_id or ""`
- **影响**: 所有工具的 handler 现在可通过 `kwargs.get("session_id")` 获取当前会话 ID

### 1.3 `gateway/run.py` — NapCat 平台适配器注入

- **日期**: ~2026-05-10
- **修改**: 注册 NapCat OneBot v11 平台适配器（具体注入方式见插件部分）

---

## 2. 自定义工具

| 工具 | 文件 | 功能 | 触发条件 |
|------|------|------|----------|
| `session_query` | `tools/session_query.py` | Session 事件日志查询 | LLM 需要翻看历史 context 时调用 |

---

## 3. 自定义平台适配器

### 3.1 NapCat OneBot v11 适配器

- **插件目录**: `~/.hermes/plugins/napcat/`
- **核心文件**: `adapter.py`（25KB）
- **功能**: 通过 NapCat（QQ Bot）的 OneBot v11 WebSocket 协议接入 Hermes
- **NapCat 配置**:
  - QQ Bot: 3130045170
  - HTTP API: `:3000`
  - WebSocket 正向连接: `127.0.0.1:18801`
- **已知联系人**: 政(2792715318), 安淇(3559500335), 杨斯涵(3958231024), 王恒(526385210)
- **禁区**: `reload` 会导致 drain crash；`docker restart napcat` 会丢 session

### 3.2 其他平台

| 平台 | 状态 | 配置要点 |
|------|------|----------|
| **微信 (WeChat)** | ✅ 原生 4.1.1 / Xvfb :99 | iLink 协议，连续发送会 rate limited |
| **飞书 (Feishu)** | ✅ | Bot `Ayin-Hermes`, 需 @ 才响应；不推送 bot 消息到 WS |
| **Telegram** | ✅ | GFW 阻断 `api.telegram.org`，需代理路由 |
| **企业微信 (WeCom)** | ❌ 已禁用 | |
| **API Server** | ✅ | 默认监听 |

---

## 4. 插件

| 插件 | 位置 | 说明 |
|------|------|------|
| NapCat QQ | `~/.hermes/plugins/napcat/` | QQ OneBot 适配器 |
| herrmes-onebot | `~/.hermes/plugins/herrmes-onebot/` | 另一个 OneBot 实现（TypeScript，待定） |
| MemTensor | `plugins/memory/memtensor/` | 长期记忆插件（待评估） |
| Web Search Plus | `~/.hermes/plugins/web-search-plus/` | 增强搜索 |

---

## 5. 配置

### 5.1 自定义模型提供商

**DeepSeek 官方 API**（替代 ofox.ai 代理）:
```yaml
custom_providers:
  - name: deepseek-official
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY
    context_length: 1048576  # 1M
```
- 模型: `deepseek-v4-pro`
- ⚠️ 教训：`hermes config set custom_providers '[{...}]'` 会整个覆盖数组，曾冲掉所有 provider。改用 `hermes config edit` 手动编辑。

### 5.2 MCP 服务器

| 服务器 | 传输方式 | API Key 来源 | 说明 |
|--------|---------|-------------|------|
| **Tavily** | HTTP | `TAVILY_API_KEY` | Web 搜索，1000次/月 |
| **Exa** | HTTP | `EXA_API_KEY` | 高级搜索，100次/月 |
| **高德地图** | HTTP | `AMAP_API_KEY` | 地理编码/路径规划/天气 |
| **12306** | HTTP | — | 火车票查询 |
| **Playwright** | stdio | — | 浏览器自动化；Chromium 需 patch registry |

### 5.3 Vision

- **问题**: Hermes 的 `auxiliary.vision.provider` 不支持 DashScope/Alibaba
- **方案**: 绕过内置 `vision_analyze`，使用独立脚本 `~/.hermes/scripts/vision.py`
- **原理**: 直接调用 DashScope `qwen-vl-max` API，base64 编码图片
- **容量**: 100万 token/月免费，国内直连

### 5.4 代理

- **mihomo**: HTTP `127.0.0.1:7890`
- **路由规则**: `hf-mirror.com→DIRECT, hf.co→PROXY, pypi.org→PROXY`
- **Tailscale DNS**: 已修复 systemd-resolved 残留污染

---

## 6. Systemd 服务调优

### 6.1 Gateway 服务

```
RestartSec=10（原 60）→ gateway 重启从 ~3分钟 降到 ~50秒
TimeoutStopSec=30（原 90）
```
- 安全重启流程: `stop` → 等 `inactive` → `start`（避免 `restart` 导致的 deactivating 死锁）

### 6.2 其他服务

| 服务 | 说明 |
|------|------|
| `hermes-webui` | Web UI（:8648），Cloudflare Tunnel 对外 |
| `memos-api` | MemOS 存储后端（Docker, :8000） |
| `cloudflared` | Cloudflare Tunnel（系统服务 `/etc/cloudflared/config.yml`） |
| `ayin-ttyd` | ttyd 终端代理（:8084，systemd user） |

---

## 7. 自定义脚本

| 脚本 | 用途 |
|------|------|
| `~/.hermes/scripts/vision.py` | Qwen-VL 视觉分析（绕过 Hermes 内置限制） |
| `~/.hermes/scripts/fetch_163_pop3.py` | 拉取 163 邮箱（POP3，定时 5 分钟） |
| `~/.hermes/scripts/healthcheck.py` | 系统健康检查 |
| `~/.hermes/scripts/sync-to-site02.sh` | 外接硬盘同步 |
| `~/.hermes/scripts/check-hermes-update.sh` | Hermes 更新检查 |
| `~/.hermes/scripts/cx_auto_study.py` | 超星自动刷课 |

---

## 8. 自建 Skills

以下技能为针对本地环境/用户偏好专门编写，非从 Hub 安装：

| Skill | 用途 |
|-------|------|
| `hledger-accounting` | 复式记账，集成工行活期/饭卡/微信等账户体系 |
| `chinese-official-documents` | 党政公文格式 Word 生成（征文/思想汇报/评审方案） |
| `creative-writing` | 中文文学创作工作流（含情色/SM 创作偏好） |
| `competition-defense-prep` | 学术竞赛答辩准备（PPT 诊断→分镜脚本→Q&A） |
| `web-redesign-workflow` | 网页改造工作流 |
| `scientific-computing` | 科学计算与函数绘图（SymPy+matplotlib） |
| `academic-literature-review` | 中文文献综述写作规范 |
| `avoid-ai-writing` | AI 写作痕迹检测与润色 |

---

## 9. 基础设施

### 9.1 MemOS（长期记忆）

- **版本**: v2.0.14
- **部署**: Docker Compose（`memos-api:8000` + `neo4j:7474` + `qdrant:6333`）
- **接入**: Hermes `_HttpTransport→REST`
- **数据**: ~706 条记忆（截至 2026-05-09）

### 9.2 本地模型推理

- **Carnice-MoE-35B**: `llama-server :8081`（GPU 14G），常驻
- **bge-large-zh**: `:8082`，embedding
- **备用**: Qwopus3.5-9B-Q8_0，ctx=262144

### 9.3 图片生成

- **ComfyUI**: FLUX fp8 优先，SDXL 备选
- **ComfyUI Path**: `/home/ayin/comfy/`

### 9.4 Cloudflare Tunnel

- **Token**: `cfut_ylRBC...` / `cfut_UIme...`
- **Zone**: `e05b6562cf26162c5202e04282642e50`
- ⚠️ Funnel GFW 阻断不可用，仅 Tunnel 正常

### 9.5 AutoDL 远程 GPU

- SSH: `root@connect.bjb1.seetacloud.com -p 25822`
- GPU: RTX PRO 6000 96GB
- 项目: `/root/autodl-tmp/crowd_analysis/`

---

## 10. 重要 Cron 任务

| 任务 | 调度 | 交付 | 说明 |
|------|------|------|------|
| 素材日报（骨头） | 每天 20:00 | QQ `3958231024` | 议论文素材，含真人实例 |
| 周三合唱课 | 周二 18:05 | 微信 | 战训馆，提前通知 |
| Hermes 更新检查 | 每周 | 本地 | `check-hermes-update.sh` |
| 163 邮箱轮询 | 每 5 分钟 | 本地 | POP3 拉取 |
| 梦境回顾 | 每天 03:00 | 本地 | 跨 session 记忆固化 |

---

## 11. Git 备份

- **Hermes 配置**: `https://github.com/AYin-Z/hermes-config` — config.yaml/插件/systemd，已脱敏
- **hledger 账本**: `/home/ayin/accounting/2026.journal`，每次修改后 commit

---

## 附录：踩坑记录

| 坑 | 根因 | 修复 |
|----|------|------|
| DeepSeek provider 消失 | `hermes config set custom_providers` 覆盖数组 | 锁定 provider 行，用 `hermes config edit` 手动加 |
| 账本被清空 | `write_file` 覆盖 journal | 强制只用 `patch` 追加，journal 入 git |
| Gateway deactivating 死锁 | `systemctl restart` 与 Feishu WS 90s graceful shutdown 冲突 | 改用 `stop → 等 inactive → start` |
| Playwright Chromium 缺失 | MCP server 版本不匹配（需 chromium-1200，装的是 1217）| symlink `chromium-1217 → chromium-1200` |
| Qwen-VL 视觉不可用 | Hermes 不支持 DashScope provider | 独立脚本 `vision.py` 直调 API |
| WeChat iLink rate limit | 平台限制连续发送 | 关键提醒双通道（微信+飞书） |
| HF 下载慢 | 国内无代理直连 | `hf-mirror.com→DIRECT, hf.co→PROXY` |
