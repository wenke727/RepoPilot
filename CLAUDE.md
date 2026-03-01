# CLAUDE.md

> Claude Code 工作规范 & 多实例并行开发约定
> 目标：**稳定 / 可恢复 / 可并行 / 可沉淀经验**

本项目是 **Claude Code Web Manager** (RepoPilot)，一个用于管理多仓库 Claude Code 开发任务的单用户 Web 管理系统。

---

## 一、任务生命周期（Task Lifecycle）

### 1. 领取任务（原子操作）

* 从 `state/tasks.json` 获取任务
* 必须是 **原子领取**，防止并发重复执行
* 支持两种执行模式：`PLAN`（规划模式）和 `EXEC`（执行模式）

---

### 2. 创建工作区（Git Worktree）

```bash
git worktree add -b task/YYMMDD-NNN ../worktrees/repo-name/YYMMDD-NNN
```

**工作区约定：**

* **隔离目录结构**：`worktrees/<repo-name>/<task-id>/`
* 每个任务获得独立的 worktree，避免并发冲突
* 任务完成后自动清理 worktree

**共享文件（在 RepoPilot 管理下）：**

* `state/repos.json`（仓库配置）
* `state/tasks.json`（任务队列）
* `state/runs.json`（运行记录）
* `state/logs/`（日志目录）

---

### 3. 实现功能

* Claude Code **只在当前 worktree 内工作**
* 不允许跨 worktree 修改文件
* PLAN 模式：生成结构化执行计划（steps, risks, validation）
* EXEC 模式：执行实际的代码修改和 Git 操作

---

### 4. 提交代码（Task Branch）

```bash
git commit
```

* 只在 `task/YYMMDD-NNN` 分支提交
* 遵循项目的 commit message 规范

---

### 5. Merge + 测试

```bash
git fetch origin
git merge origin/main
# 根据项目类型运行测试
npm test    # 或 pytest, cargo test 等
```

* 必须测试通过
* 如有测试配置，按照项目的 `.github/workflows/` 或 `package.json` 执行

---

### 6. 自动合并到 main

```bash
git fetch origin main
git rebase origin/main
```

* 如 rebase 失败，进入【冲突处理流程】

成功后：

```bash
git checkout main
git merge task/YYMMDD-NNN
git push origin main
```

* 若失败，**回退到步骤 5**

---

### 7. 创建 Pull Request（可选）

```bash
gh pr create --title "Task YYMMDD-NNN: ..." --body "..."
# 或回退到 GitHub API（需要 GITHUB_TOKEN）
```

---

### 8. 标记完成（必须在清理前）

* 更新 `state/tasks.json`
* 更新 `state/runs.json`
* 防止进程被杀导致任务状态丢失

---

### 9. 清理

```bash
git worktree remove ../worktrees/repo-name/YYMMDD-NNN
git branch -d task/YYMMDD-NNN
```

* 删除 worktree 目录
* 删除本地 task 分支

---

## 二、多实例并行开发（Git Worktree）

### 架构说明

* RepoPilot 支持多个 Claude Code 实例并行工作
* **每个实例 = 独立 worktree + 独立任务 + 独立日志**

```txt
并行开发工作流（RepoPilot 管理）

┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ Task 260301-001 │   │ Task 260301-002 │   │ Task 260301-003 │
│ repo: voice-notes│   │ repo: guiagent  │   │ repo: RepoPilot │
│ worktree        │   │ worktree        │   │ worktree        │
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                     │
   state/logs/           state/logs/           state/logs/
   (独立日志文件)
```

### 状态管理

* **任务状态**：`TODO` → `PLAN_RUNNING` → `PLAN_REVIEW` → `READY` → `RUNNING` → `REVIEW` → `DONE` / `FAILED` / `CANCELLED`
* **看板列**：前端 Web UI 实时展示任务状态
* **事件流**：所有任务状态变更记录在 `state/runs.json`

---

## 三、冲突处理

### Rebase 失败处理流程

1. 如果是 `unstaged changes`
   * 先 `git commit` 或 `git stash`

2. 如果有 merge conflicts：

   ```bash
   git status
   ```

   * 阅读冲突内容，理解双方修改意图
   * 手动解决（保留正确逻辑）

   ```bash
   git add <resolved-files>
   git rebase --continue
   ```

3. 重复直到 rebase 完成

---

### 测试失败处理流程

1. 运行测试：

   ```bash
   # 根据项目类型
   npm test          # Node.js
   pytest            # Python
   cargo test        # Rust
   ```

2. 分析失败原因
3. 修复代码
4. 重新测试
5. 提交修复：

   ```bash
   git commit -m "fix: ..."
   ```

---

### 🚫 不要放弃

* rebase / test 失败 **必须修好**
* 不能因为失败就标记任务失败
* 失败的任务会保留在 `FAILED` 列，可手动重试

---

## 四、RepoPilot 特性

### PLAN 模式

* **结构化计划**：生成包含 steps, risks, validation, rollback 的执行计划
* **批量审核**：支持批量 confirm / revise 计划
* **回退机制**：EXEC 模式可回退到 PLAN 模式重新规划

### EXEC 模式

* **自动化流水线**：worktree → claude → commit → rebase → test → push → PR
* **产物快照**：失败/取消任务保留代码快照便于排障
* **通知中心**：实时推送任务状态变更

### 多仓库管理

* 自动发现 `repos/` 下的仓库
* 支持托管仓库和本地开发仓库
* 每个仓库独立的任务队列

---

## 五、开发规范

### ID 规则

- 格式：`YYMMDD-NNN`
- 示例：`260301-001`
- 同日同类型递增分配（task, run, notification 各自独立计数）
- 若超过 999，回退到 `YYMMDD_HHMMSS` 格式

### 日志记录

* 所有 Claude Code 会话日志保存在 `state/logs/`
* 格式：`<task-id>_<run-id>_<timestamp>.log`
* Web UI 提供日志查看和下载

---

> This file defines how Claude Code works in RepoPilot.
> Stability > Speed. Parallelism > Chaos.
