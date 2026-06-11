# CodeReview

一个自托管的、AI 驱动的代码评审工具。可以粘贴代码片段、上传文件，
或直接粘贴 `git diff` 的输出；服务会实时地将结构化的评审结果流式
返回到前端界面。

内置两套评审引擎：

* **Anthropic Claude** —— 当环境变量中设置了 `ANTHROPIC_API_KEY` 时启用。
  通过一次结构化提示词调用生成评审结果。
* **Mock 规则引擎** —— 一套确定性的、感知语言的规则集，即使没有
  API Key 也能运行。适合开发、演示和编写测试。

两套引擎输出完全一致的结果结构，因此前端无需关心当前运行的是哪一套。

## 技术栈

| 层级    | 技术                                              |
|---------|---------------------------------------------------|
| 前端    | Vue 3、Vite、Tailwind 4、原生 `EventSource`        |
| 后端    | FastAPI、Pydantic v2、`sse-starlette`、httpx       |
| 存储    | SQLite（单文件，零配置）                            |
| AI      | Anthropic Messages API（或 Mock 兜底）              |

## 架构

一次评审的端到端时序：

```
┌────────┐  POST /api/review   ┌──────────┐
│  Vue   │ ──────────────────▶ │ FastAPI  │
│ (FE)   │ ◀──── {id} ──────── │ (main)   │
└────────┘                     └────┬─────┘
   ▲                                │ BackgroundTasks
   │                                ▼
   │                          ┌────────────┐  POST /v1/messages   ┌──────────┐
   │                          │  reviewer  │ ───────────────────▶ │ Anthropic│
   │                          │  (engine)  │ ◀─── text_delta ──── │  API     │
   │                          └─────┬──────┘   (stream: true)     └──────────┘
   │                                │ findings / summary
   │                                ▼
   │                          ┌────────────┐
   │                          │ persistence│  SQLite  ── reviews table
   │                          │   (SQLite) │  (total_findings denormalized)
   │                          └────────────┘
   │
   │   GET /api/reviews/{id}/events   (SSE)
   └─────────────────────────────────  status / findings / summary / done
```

要点：

* `BackgroundTasks` 跑评审主循环，`asyncio.Queue` 在评审 ID 维度上
  串起生产者和 SSE 消费者。`/events` 端点从中取出事件流回前端。
* 流式 JSON 解析：每个 `text_delta` 到达时，把累积文本里第一个已闭合
  的 finding 对象剥出来立即推送给前端，不必等模型整段写完。
* 1 MB 硬上限（`_MAX_STREAM_BUFFER`）：超过即 yield error 事件、丢弃
  后续字节，避免失控响应把内存打爆。
* SQLite PRAGMAs：`journal_mode=WAL` + `synchronous=NORMAL` +
  `temp_store=MEMORY`，单进程下读写都不阻塞事件循环。
* SSE 自动重连的去重：客户端用
  `(file_path, line_start, line_end, title, severity, category)` 合成
  稳定 key，重连后同一 finding 不会再 push 一遍。

## 快速开始

默认端口：后端 **8770**，前端 **5273**（为了避免与同工作区 QDII 基金
项目的 8000/5173 端口冲突）。

```bash
# 后端
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8770

# 前端（在另一个终端中）
cd frontend
npm install
npm run dev
```

Vite 开发服务器会把 `/api/*` 代理到后端的 8770 端口
（`strictPort: true` —— 端口被占用时立即失败，不会自动切换）。
如果后端运行在其他端口上，可以在 `npm run dev` 之前设置
`VITE_API_TARGET`：

```bash
VITE_API_TARGET=http://localhost:8765 npm run dev
```

生产构建如果后端不在同一域名下，可以直接指定 API 根：

```bash
VITE_API_BASE=https://reviews.example.com/api npm run build
```

## 配置

后端所有配置都在启动时从环境变量读取。

| 变量                     | 默认值                            | 说明                                     |
|--------------------------|-----------------------------------|------------------------------------------|
| `REVIEW_PORT`            | `8770`                            | FastAPI 服务端口                          |
| `REVIEW_HOST`            | `0.0.0.0`                         | 绑定地址                                  |
| `REVIEW_DATA_DIR`        | `backend/data`                    | SQLite 文件所在目录                        |
| `ANTHROPIC_API_KEY`      | （未设置）                         | 启用真实 Claude 评审路径                   |
| `REVIEW_MODEL`           | `claude-sonnet-4-6`               | 设置 Key 时使用的默认模型                  |
| `ANTHROPIC_BASE_URL`     | `https://api.anthropic.com`       | 代理 / 区域端点覆盖                        |
| `REVIEW_AI_TIMEOUT`      | `45`                              | AI 调用超时时间（秒）                       |
| `CORS_ALLOW_ORIGINS`     | `http://localhost:5273,http://127.0.0.1:5273` | 逗号分隔的允许来源      |
| `REPO_PATH`              | （未设置）                         | 启用 Git 分支对比功能，指向本地仓库路径     |
| `GIT_TIMEOUT`            | `30`                              | `git` 子命令的超时时间（秒）                |
| `REVIEW_GIT_REMOTE_ENABLED` | `true`                         | 启用「用户自助输入远程仓库 URL」功能         |
| `REMOTE_GIT_ALLOWED_HOSTS` | `github.com,gitlab.com,…`        | 逗号分隔的允许 host 白名单（带 `.` 前缀表示子域匹配） |
| `REMOTE_GIT_CLONE_TIMEOUT` | `300`                            | 克隆 / fetch 单次超时（秒）                  |
| `REMOTE_GIT_CACHE_MAX`    | `10`                              | 缓存远程仓库 LRU 上限                       |
| `REMOTE_GIT_CACHE_TTL`    | `3600`                            | 缓存有效时间（秒），过期下次请求自动 fetch   |
| `REMOTE_GIT_MAX_SIZE_MB`  | `500`                             | 单仓库目录大小硬上限（MB）                  |
| `REMOTE_GIT_CACHE_DIR`    | `backend/data/remotes`            | 远程仓库克隆根目录                          |

## API 接口

| 方法   | 路径                              | 用途                                       |
|--------|-----------------------------------|--------------------------------------------|
| GET    | `/api/health`                     | 健康检查 + 当前启用的引擎                   |
| GET    | `/api/config`                     | 公共配置（评审维度、限制、模型）             |
| POST   | `/api/diff/parse`                 | 解析 unified diff，按文件返回               |
| POST   | `/api/review`                     | 提交评审请求，返回评审 ID                   |
| GET    | `/api/reviews`                    | 列出历史评审（分页）                         |
| GET    | `/api/reviews/{id}`               | 获取单条评审及结果                           |
| DELETE | `/api/reviews/{id}`               | 删除一条评审                                |
| GET    | `/api/reviews/{id}/events`        | SSE 流：`status` / `findings` / `summary` / `done` |
| POST   | `/api/upload`                     | 上传单个文件（返回 `CodeFile`）             |
| GET    | `/api/git/status`                 | Git 仓库信息（HEAD、默认分支、是否有未提交改动）|
| GET    | `/api/git/branches`               | 列出本地分支                                 |
| GET    | `/api/git/tags`                   | 列出本地 Tag                                 |
| POST   | `/api/git/diff`                   | 对比两个分支 / 引用，返回解析后的文件列表     |
| POST   | `/api/git/remote/clone`           | 克隆或 fetch 一个用户提供的远程仓库          |
| GET    | `/api/git/remote`                 | 列出已缓存的远程仓库（按最近使用排序）       |
| GET    | `/api/git/remote/{id}`            | 查询某个远程仓库的 head / branches / tags    |
| POST   | `/api/git/remote/{id}/diff`       | 对远程仓库上的两个 ref 计算 diff              |
| DELETE | `/api/git/remote/{id}`            | 清理某个远程仓库缓存                          |

> 本地 Git 接口仅在设置了 `REPO_PATH` 时返回有效响应；远程 Git 接口仅在
> `REVIEW_GIT_REMOTE_ENABLED=true` 时启用，且全部走 `REVIEW_API_KEY` 鉴权。

### SSE 事件格式

```
event: status
data: {"status": "streaming"}

event: findings
data: [{"file_path": "...", "line_start": 3, "severity": "critical", "title": "...", ...}, ...]

event: summary
data: {"total_findings": 7, "by_severity": {...}, "by_category": {...}, "overall_assessment": "..."}

event: done
data: {"status": "completed", "error": null, "duration_ms": 1234}
```

## 评审结果结构

```jsonc
{
  "file_path": "src/auth.py",
  "line_start": 12,
  "line_end": 12,
  "severity": "critical",          // critical | high | medium | low | info
  "category": "security",          // bug | security | performance | style | best_practice | documentation
  "title": "subprocess with shell=True",
  "detail": "为什么这是危险的……",
  "suggestion": "subprocess.run([...], shell=False)",
  "code_snippet": "subprocess.call('ls ' + d, shell=True)"
}
```

## Mock 规则集

Mock 引擎内置了以下规则：`eval`、`exec`、`subprocess(shell=True)`、
`pickle.loads`、可变默认参数、裸 `except`、硬编码密钥、SQL 字符串拼接、
JS `eval` / `innerHTML` / `dangerouslySetInnerHTML`、`pdb.set_trace`、
`console.log` / `print`、TODO/FIXME 标记、超长行等。
添加新规则只需在 `backend/reviewer/rules.py` 的 `RULES` 列表中新增一条。

## 鉴权与限流

后端默认对写接口不做鉴权；如需对外暴露，可通过环境变量启用：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `REVIEW_API_KEY` | 空 | 留空则关闭鉴权。设置后，写接口（`/api/review`、`/api/upload`、`/api/reviews/{id}/cancel`、`/api/reviews/{id}/rerun`）需要 `Authorization: Bearer <key>`。读接口（`/api/reviews`、`/api/reviews/{id}`、`/api/reviews/{id}/events`）仍然公开。 |
| `REVIEW_RATE_LIMIT_PER_MIN` | `20` | 每个调用方（按 Bearer token 前 8 位或客户端 IP）在 60 秒内最多可发起的写请求数。设为 `0` 关闭限流。 |
| `REVIEW_ID_LENGTH` | `16` | 评审 ID 的十六进制长度（`uuid4().hex[:N]`），`12` 仍可工作但会随着提交数增加而撞库概率上升。 |

每个评审的 SSE 事件在每个 `text_delta` 到达时就尝试剥离一个完整的
finding 对象并立即推送给前端，不再等整段回复结束。

## Git 分支对比

设置 `REPO_PATH` 指向一个本地 Git 仓库后，前端会显示第三个标签页
"分支对比"。可以选择 base / head 引用（分支、Tag 或 commit-ish），
可选地添加路径过滤；点击"预览 diff"会调用 `/api/git/diff` 返回受
影响文件列表及 `--stat` 摘要，确认后即可直接发起评审。

实现细节：

* 使用 `git diff base...head` 三点形式，自动对齐到 merge-base，与
  实际合并时的 diff 一致。
* 通过 `-M -C` 启用重命名 / 复制检测，重命名的文件会作为单个文件、
  带有连贯的 diff 返回。
* 自动跳过二进制文件（`Binary files ... differ` 整块从输出中剥离）。
* 引用名通过白名单正则校验，禁止 `..`、`--`、前导 `-`、空白等，
  避免任何 shell 注入的可能。

## 远程 Git 仓库（自服务）

前端"远程"标签页让你粘贴任何 `https://…` 或 `git@host:…` URL，
后端在 `REMOTE_GIT_CACHE_DIR` 下缓存克隆结果，并在 `REMOTE_GIT_CACHE_TTL`
秒内复用结果（避免重复 fetch），超时后下次请求自动 `git fetch`。
可使用右上角"刷新"按钮强制立即拉取。

完整流程：

1. **输入 URL**（+ 可选的 HTTPS 私有仓库 token）。
2. **Connect** —— 后端执行 `git clone --depth 1 --filter=blob:none
   --no-tags --single-branch <url>`，克隆完成后列出分支与 HEAD。
3. **选 base / head** —— 直接复用 RefPicker，从 `refs/remotes/origin/*`
   拉出分支列表。
4. **预览 diff** —— 调 `POST /api/git/remote/{id}/diff`，复用与本地
   Git 模式相同的 `git_diff.diff_refs` 路径。
5. **Run review** —— 评审请求带 `source: "remote:<name>"` 标签，
   历史列表会显示 `remote` 徽章以便区分来源。

安全：

* **Host 白名单** —— 默认仅放行 `github.com / gitlab.com / bitbucket.{org,com}
  / gitea.com / gitee.com / codeberg.org / sourcehut.org`，可通过
  `REMOTE_GIT_ALLOWED_HOSTS` 自定义（前缀 `.` 表示子域匹配，例如
  `.github.com` 接受 `api.github.com`）。
* **解析后 IP 检查** —— 命中 RFC1918 / loopback / link-local 的 host
  一律拒绝，防止 DNS 绕过白名单。
* **Scheme 限制** —— 仅接受 `https://` 和 `git@host:path`；`file://`、
  `ssh://`、`git://` 都被拒绝。
* **Token 安全** —— 仅在当次 clone 命令中以 `https://oauth2:{token}@…`
  形式注入；从不写入 `state.json`，错误日志中不出现 token。
* **缓存隔离** —— 每个 URL 单独目录，按 `sha1(url)[:12]` 命名；
  路径校验禁止 `..`、前导 `-`、控制字符等。

生命周期：

* `REMOTE_GIT_CACHE_MAX` —— LRU 上限（默认 10），超出时下一次成功的
  `get_or_create` 会驱逐最久未用的仓库。
* `REMOTE_GIT_CACHE_TTL` —— 缓存新鲜度窗口（默认 1 小时），下次请求
  触发 `git fetch` 刷新。
* 后台 `_remote_sweep_loop` 每 5 分钟跑一次 `sweep_stale`（默认
  超过 24h 未用即清掉磁盘内容）+ `evict_lru`（保证总数 ≤ cap）。
* `REMOTE_GIT_MAX_SIZE_MB` —— 单仓库目录超过此值会被标记为
  `oversized` 并从内存索引中隐藏（磁盘保留供人工排查）。

### 远程克隆的网络 / 代理配置

`git` 子进程从后端进程继承网络栈。如果后端所在机器无法直接访问
`github.com` 等公网（如企业内网、沙箱环境、无 internet 出口的容器），
`/api/git/remote/clone` 会失败，错误类似：

```
fatal: unable to access 'https://github.com/.../':
GnuTLS recv error (-110): The TLS connection was non-properly terminated.
```

后端把这类错误归到 `RemoteGitNetworkError`（HTTP 502），UI 在错误下方
显示提示「可设置 `GIT_HTTPS_PROXY` 重启后端,或改用 SSH URL」。两个
常见修复：

1. **走 HTTP / SOCKS 代理** —— `git` 支持 `http.proxy` / `https.proxy`
   设置。最简单的方式是带 env 启动：

   ```bash
   GIT_HTTPS_PROXY=http://proxy.example.com:3128 \
     python3 -m uvicorn main:app --host 0.0.0.0 --port 8770
   ```

   （SOCKS 代理需先装 `git-remote-socks`，写法是
   `GIT_SOCKS5_PROXY=socks5://...`。）

2. **改用 SSH URL** —— `git@github.com:owner/repo.git` 走 22 端口，
   部分内网只封 443 不封 22。后端机器上需要有相应 SSH key（默认
   `~/.ssh/id_rsa` 或 `GIT_SSH_COMMAND` 指定）。URL 白名单已经允许
   `git@host:path` 形式。

如果只是临时想测功能、不想跑真实 git clone，pytest 自带 file:// 后门
（`backend/tests/test_git_remote.py` 用 `_parse_url` 注入）；e2e 脚本
`scripts/verify_remote.sh` 默认走 no-clone smoke check。

## 测试

```bash
# 后端（pytest, 129 测试）
cd backend
pytest -v
ruff check .

# 前端（vitest, 70 测试；ESLint）
cd ../frontend
npm test
npm run lint
npm run build      # 验证 defineAsyncComponent 的代码分割
```

后端测试覆盖 diff 解析器、规则引擎、FastAPI 接口（含 SSE 流）、Git
集成、流式评审 JSON 解析、鉴权与限流、SQLite 持久层（含 PRAGMA 配置
和列迁移回填）。前端测试覆盖 `useReviewSession` / `useReview` /
`useConfig` 组合式 API、`utils/format` / `utils/markdown` 工具函数，
以及轻量 i18n 表。

## 目录结构

```
codereview/
├── backend/
│   ├── config.py            # 环境变量驱动的配置
│   ├── models.py            # Pydantic 模型（带 OpenAPI description / example）
│   ├── diff_parser.py       # unified diff → CodeFile
│   ├── git_diff.py          # Git 分支对比（list / diff / 校验）
│   ├── reviewer/
│   │   ├── __init__.py      # Claude + Mock 评审引擎
│   │   └── rules.py         # Mock 规则表（含预编译正则）
│   ├── auth.py              # 可选 Bearer 鉴权
│   ├── rate_limit.py        # 滑动窗口限流器
│   ├── persistence.py       # SQLite 存储（PRAGMAs + 列迁移）
│   ├── main.py              # FastAPI 路由、SSE
│   ├── requirements.txt
│   └── tests/
│       ├── conftest.py
│       ├── test_api.py
│       ├── test_diff_parser.py
│       ├── test_reviewer.py
│       ├── test_streaming.py
│       ├── test_git_diff.py
│       ├── test_auth_and_rate.py
│       └── test_persistence.py
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    ├── vitest.config.js
    ├── public/favicon.svg
    └── src/
        ├── App.vue
        ├── main.js
        ├── style.css
        ├── components/
        │   ├── Header.vue
        │   ├── InputPanel.vue          # 粘贴代码 / diff / 上传 / 分支对比
        │   ├── RefPicker.vue           # 分支 / Tag 选择器（defineAsyncComponent 懒加载）
        │   ├── ReviewPanel.vue         # 评审结果 + 代码预览
        │   ├── SummaryCard.vue         # 严重程度统计、筛选、骨架占位
        │   ├── FindingCard.vue
        │   ├── CodeView.vue
        │   ├── SeverityBadge.vue
        │   ├── CategoryBadge.vue
        │   └── HistoryList.vue
        ├── composables/
        │   ├── useConfig.js
        │   ├── useReviewSession.js     # SSE 订阅（带重连去重 + hydrate）
        │   ├── useReview.js            # 当前评审状态 + 动作编排
        │   └── useReviewHistory.js
        ├── i18n/
        │   └── messages.js             # 轻量 t(key) composable + en/zh 表
        └── utils/
            ├── api.js                  # fetch + AbortSignal.timeout
            ├── format.js
            └── markdown.js
```
