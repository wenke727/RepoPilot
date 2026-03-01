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
- EXEC Git 流水线：`worktree -> claude -> commit -> rebase -> test -> push -> PR`
- PR 优先用 `gh` 创建，失败时回退 GitHub API（需 `GITHUB_TOKEN`）
- 事件流与通知中心
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
- `claude` CLI
- 可选：`gh` CLI、`conda`

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

## API 概览

- `GET /api/health`
- `GET /api/repos`
- `POST /api/repos/rescan`
- `PATCH /api/repos/{id}`
- `GET /api/tasks`
- `POST /api/tasks`
- `GET /api/tasks/{id}`
- `GET /api/tasks/{id}/events`
- `POST /api/tasks/{id}/cancel`
- `POST /api/tasks/{id}/retry`
- `POST /api/tasks/{id}/done`
- `POST /api/tasks/{id}/plan/confirm`
- `POST /api/tasks/{id}/plan/revise`
- `POST /api/tasks/plan/batch/confirm`
- `POST /api/tasks/plan/batch/revise`
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

- 后端 systemd 模板：`ops/systemd/ccwm-backend.service`
- 前端 systemd 模板：`ops/systemd/ccwm-frontend.service`
- Nginx 反向代理示例：`ops/nginx.conf.example`

## 说明

- 本项目按单用户场景设计。
- 运行状态采用文件存储（`state/*.json`），便于移植与排查。
