# Claude Code Web Manager

一个面向单用户的 Claude 任务管理器，基于 FastAPI + React。

## 项目背景

本项目受文章 [胡渊鸣 | 我给 10 个 Claude Code 打工](https://zhuanlan.zhihu.com/p/2007147036185744607) 启发，做了一个可运行的复现。

## 项目概览

这个仓库提供了一个本地 Web 控制面板，用于管理 Claude 驱动的开发任务：

- 自动发现并管理 `repos/` 下的仓库
- 以优先级排队 `PLAN/EXEC` 任务
- 基于隔离的 Git worktree 执行任务
- 在统一看板中查看日志、PR 链接和任务结果

## 目录结构

- `backend/`：FastAPI 服务、调度器、执行器、Git 流水线、JSON 存储
- `frontend/`：React + Vite 看板界面
- `ops/`：启动脚本、systemd 模板、Nginx 示例配置
- `repos/`：托管仓库目录（单层）
- `worktrees/`：按任务创建的 worktree
- `state/`：运行时数据（`repos.json`、`tasks.json`、`runs.json`、日志、产物）

## 核心功能

- 多仓库自动纳管（`/repos/*`，支持 GitHub 来源仓库）
- 任务看板列：`TODO`、`RUNNING`、`REVIEW`、`DONE`、`FAILED`、`CANCELLED`
- PLAN 模式（`PLAN_RUNNING`/`PLAN_REVIEW`），支持结构化解析与回退
- PLAN 批量审核接口：
  - `POST /api/tasks/plan/batch/confirm`
  - `POST /api/tasks/plan/batch/revise`
- Claude 驱动主链路：`TODO -> PLAN_RUNNING -> PLAN_REVIEW -> READY -> RUNNING -> REVIEW -> DONE`
- EXEC Git 流水线：`worktree -> agent-cli -> commit -> rebase -> test -> push -> PR`
- PR 优先用 `gh` 创建，失败时回退 GitHub API（需 `GITHUB_TOKEN`）
- 事件流与通知中心
- 任务创建支持语音输入（前端录音 + OpenAI 转录）
- 失败/取消任务的产物快照（便于排障）

详细流程文档：[`docs/agentic_coding_flow_draft.md`](docs/agentic_coding_flow_draft.md)

设计对齐提案：[`docs/claude_driven_alignment_plan.md`](docs/claude_driven_alignment_plan.md)

## ID 规则

- 新的 `task.id`、`run.id`、`notification.id` 使用格式：`YYMMDD-NNN`
- 示例：`260210-001`
- 同日同类型递增分配（`task`、`run`、`notification` 各自独立计数）
- 若同日同类型超过 `999`，回退到 `YYMMDD_HHMMSS` 格式并按秒去重
- 旧的长 ID 仍可读取（无需迁移）

## 运行要求

- Python 3.10+
- Node.js 18+
- `git`
- `claude-kimi` CLI（默认）或 `claude-glm` CLI，或 `claude` CLI
- 语音输入可选依赖：`OPENAI_API_KEY`（用于 `/api/audio/transcribe`）
- 可选：`gh` CLI、`conda`、`cursor` CLI（预留驱动）

## 配置与 .env

后端默认从**项目根目录**的 `.env` 文件加载环境变量（若存在），无需在 shell 里导出。

- 首次使用：复制 `cp .env.example .env`，按需编辑。
- 可用变量见 `.env.example`；与鉴权相关的说明见下方「可选鉴权」。
- `.env` 已加入 `.gitignore`，本地账号密码不会进仓库。
- 驱动相关变量：
  - `REPOPILOT_AGENT_DRIVER`：`CLAUDE` / `CLAUDE_KIMI`（默认）/ `CLAUDE_GLM` / `CURSOR_CLI`（预留，不可切换使用）
  - `REPOPILOT_AGENT_SHELL`：KIMI/GLM 模板执行所用 shell（默认 `zsh`）
  - `REPOPILOT_CLAUDE_KIMI_SHELL_TEMPLATE`、`REPOPILOT_CLAUDE_GLM_SHELL_TEMPLATE`：KIMI/GLM shell 模板（默认 `claude-kimi` / `claude-glm`，用于兼容 alias/function）
  - `REPOPILOT_CLAUDE_CMD`、`REPOPILOT_CLAUDE_KIMI_CMD`、`REPOPILOT_CLAUDE_GLM_CMD`、`REPOPILOT_CURSOR_CLI_CMD`：直连命令映射（当模板为空时 KIMI/GLM 回退到对应命令）

## 快速开始

### 1. 安装后端依赖

```bash
cd backend
conda run -n dl2 pip install -r requirements.txt || conda run -n base pip install -r requirements.txt
```

### 2. 启动后端

```bash
./ops/run_backend.sh
# 代码变更自动重载
./ops/run_backend.sh --reload
```

### 3. 安装并启动前端

```bash
cd frontend
npm install
npm run dev
# 或用包装脚本（Vite 默认已开启 HMR）
./ops/run_frontend.sh
# 强制重建依赖并刷新（等价于 vite --force）
./ops/run_frontend.sh --reload
```

### 4. 手机/其他设备访问与「打不开」排查

要在 iPhone 或同一局域网内另一台设备打开看板，请用 **`./ops/run_frontend.sh`** 启动前端（会监听 `0.0.0.0:5173`），不要只用 `npm run dev` 且不传 `--host`。

- **访问地址**：在手机浏览器输入 `http://<本机 IP>:5173`，例如 `http://192.168.1.10:5173`。本机 IP 可用 `ipconfig getifaddr en0`（macOS）查看。
- **打不开时逐项检查**：
  1. 前端是否已用 `./ops/run_frontend.sh` 启动，终端有无报错。
  2. 手机与电脑是否在同一 WiFi（或同一网段）。
  3. macOS 防火墙：**系统设置 → 网络 → 防火墙** 中，若开启了防火墙，需允许「Node」或对应开发工具的传入连接，或临时关闭防火墙测试。
  4. 公司/公共 WiFi 若有「客户端隔离」，同一 WiFi 下设备无法互访，可改用手机热点让电脑连上后再用手机访问。
## 可选鉴权（暴露于 Tailscale/公网时建议开启）

若将前端暴露在 Tailscale 或公网，建议开启账号密码鉴权，避免未授权访问。

- **配置方式**：在 `.env` 中设置 `REPOPILOT_AUTH_USERNAME`、`REPOPILOT_AUTH_PASSWORD`（**两者都设置**后鉴权才生效）；也可用系统环境变量，`.env` 会先被加载。
- **使用方式**：启动后端后，访问页面会先进入登录页，输入上述账号密码即可；登录态保存在当前会话（sessionStorage），关闭标签页后需重新登录。顶栏提供「退出」可清除登录态。
- **不开启时**：不设置或留空上述两项时，行为与之前一致，无鉴权。

## API 概览

- `GET /api/health`
- `POST /api/auth/login`（鉴权开启时用于登录，返回 JWT）
- `GET /api/settings/exec-mode`
- `PUT /api/settings/exec-mode`
- `GET /api/settings/agent-driver`
- `PUT /api/settings/agent-driver`
- `GET /api/repos`
- `POST /api/repos/rescan`
- `PATCH /api/repos/{id}`
- `GET /api/tasks`
- `POST /api/tasks`
- `GET /api/tasks/{id}`
- `DELETE /api/tasks/{id}`
- `GET /api/tasks/{id}/events`
- `POST /api/tasks/{id}/cancel`
- `POST /api/tasks/{id}/retry`
- `POST /api/tasks/{id}/done`
- `POST /api/tasks/{id}/plan/confirm`
- `POST /api/tasks/{id}/plan/revise`
- `POST /api/tasks/plan/batch/confirm`
- `POST /api/tasks/plan/batch/revise`
- `POST /api/audio/transcribe`
- `GET /api/board`
- `GET /api/logs/backend`
- `GET /api/notifications`
- `POST /api/notifications/{id}/read`

## 日志与产物

- 后端日志：`state/logs/backend.log`
- 任务事件日志：`state/logs/<task_id>.ndjson`
- 失败/取消任务快照：`state/artifacts/<task_id>/<run_id>/`
- 快速查看后端日志：

```bash
./ops/tail_backend_log.sh
```

## 部署

- 后端 systemd 模板：`ops/systemd/ccwm-backend.service`。若需鉴权，在 unit 的 `Environment` 中设置 `REPOPILOT_AUTH_USERNAME`、`REPOPILOT_AUTH_PASSWORD`，或将 `.env` 放在项目根目录（后端启动时会自动加载）。
- 前端 systemd 模板：`ops/systemd/ccwm-frontend.service`
- Nginx 反向代理示例：`ops/nginx.conf.example`

## 说明

- 本项目按单用户场景设计。
- 运行状态采用文件存储（`state/*.json`），便于移植与排查。
