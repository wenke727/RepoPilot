# 6 周三阶段迭代优化计划（目标：提升任务成功率）

## 摘要

1. 目标定位：沿用“任务编排平台”主线，不做 Happy 技术接入；借鉴其移动端交互与通知机制。
2. 成功指标：`exec_success_rate` 在 6 周内达到 `>=85%` 且较基线提升 `>=15pp`；`NO_CHANGES` 与 `GIT_PIPELINE_FAILED` 占比各下降 `>=30%`。
3. 节奏：每 2 周一个阶段，共 3 个阶段；每阶段末固定做一次回归测试与指标复盘。
4. 范围边界：语音只做 Web 轻量接入（浏览器语音转文字）；不做原生 App、不做 Happy 协议互通。

## Workflow 借鉴映射（Step -> 本项目动作）

| Workflow Step | 借鉴点 | 当前状态 | 本计划动作 |
|---|---|---|---|
| Step 3 Ralph loop | 队列持续派活 | 已有调度器 | 加入失败分类 + 瞬态自动重试 |
| Step 4 worktree 并行 | 隔离并行执行 | 已有 | 增加 repo 级并行上限与可观测性 |
| Step 5 CLAUDE/PROGRESS 记忆 | 经验沉淀 | 缺失 | 新增 repo memory，并注入后续 prompt |
| Step 6 手机网页操作 | 移动端可操作 | 已有基础 | 优化移动端快捷操作与状态反馈 |
| Step 7 stream-json 闭环 | 过程可诊断 | 部分已有 | 增加结构化阶段指标与失败诊断 |
| Step 8 语音输入 | 提高派活速度 | UI 占位 | 接入 Web Speech API |
| Step 9 Plan Mode 批审 | 计划先行 | 已有 | 增加 Plan 风险门禁与模板化批审 |
| Step 10 Context not control | 少微管控 | 部分 | 增加任务模板与自动复盘摘要 |

## 阶段计划（6 周）

## 阶段 1（第 1-2 周）：稳定性与可观测性基线

1. 后端实现：在 `runner` 中为 `plan/exec/rebase/test/push/pr` 记录统一 `stage_metrics`；新增失败分类器（`TRANSIENT`/`PROMPT_QUALITY`/`GIT_CONFLICT`/`TEST_FAILURE`/`NO_CHANGES`）；对瞬态错误启用“仅一次自动重试”。
2. 数据模型改动：
   - `Task` 新增 `retry_count`、`failure_category`、`last_failure_stage`。
   - `TaskRun.metrics` 规范化为 `{"stage_metrics":[...], "diagnosis":{...}}`。
3. API 新增：
   - `GET /api/tasks/{task_id}/runs`：返回运行历史与每次诊断。
   - `GET /api/insights/overview?hours=24`：返回成功率、时延、Plan 转化率。
   - `GET /api/insights/failures?hours=24&limit=10`：返回失败 TopN。
4. 前端实现：看板顶部新增 KPI 条；任务详情页新增“阶段耗时+失败诊断”面板。
5. 阶段验收：同一窗口内可明确回答“失败发生在哪个阶段、占比多少、是否值得自动重试”，并输出可视化数据。

## 阶段 2（第 3-4 周）：闭环提效（Plan + Memory）

1. 记忆系统：新增 `state/memory/<repo_id>.jsonl`；任务结束后自动沉淀“问题-修复-验证”三段式条目。
2. Prompt 组装：创建任务时自动拼接“最近 5 条高相关 memory”（按 repo + failure_category 过滤）；Plan/Exec 都使用同一组装器。
3. Plan 门禁：对高风险 Plan（`risks>=3` 或变更文件数超阈值）强制二次确认；批量确认时默认采用推荐选项并写入审计事件。
4. API 新增：
   - `GET /api/repos/{repo_id}/memory?limit=20`
   - `POST /api/repos/{repo_id}/memory`（人工补充经验）
5. 阶段验收：`NO_CHANGES` 失败率较阶段 1 下降 `>=20%`；Plan 到 EXEC 的确认后返工率下降 `>=20%`。

## 阶段 3（第 5-6 周）：移动端效率与交付治理

1. 语音输入：`TaskComposer` 接入 `SpeechRecognition/webkitSpeechRecognition`；不支持浏览器自动降级为文本输入。
2. 移动端交互：新增“快速派活模板”（Bugfix/Refactor/Test-only/Docs）；新增移动端固定底栏（刷新、重试、取消、标记完成）。
3. PR 交付质量：
   - commit message 从固定模板升级为规则化模板（`type(scope): summary`）。
   - PR body 自动填充 `变更摘要/风险/验证结果/回滚方式`（来自 Plan + run metrics）。
4. API/类型改动：
   - `RepoConfig` 新增 `quality_gate`（`require_tests_passed`, `max_changed_files`, `require_plan_for_high_risk`）。
   - `PATCH /api/repos/{id}` 支持更新 `quality_gate`。
5. 阶段验收：移动端派活平均耗时下降 `>=30%`；进入 REVIEW 的任务 PR 描述完整率达到 `100%`。

## 公共 API / 接口 / 类型变更清单（实现时必须同步）

1. 后端 `models.py`：新增 `RunStageMetric`、`RunDiagnosis`、`RepoQualityGate`；扩展 `Task`、`TaskRun`、`RepoConfig`。
2. 后端路由：`tasks.py` 增加 `GET /api/tasks/{task_id}/runs`；新增 `insights.py`、`memory.py` 两组路由并在 `main.py` 注册。
3. 前端 `types/index.ts`：同步新增 `TaskRunView`、`InsightOverview`、`FailureBucket`、`MemoryEntry`、`RepoQualityGate`。
4. 前端 `api/client.ts`：新增 `listTaskRuns`、`getInsightsOverview`、`getFailureBuckets`、`listRepoMemory`、`createRepoMemory`。

## 测试与验收场景（必须覆盖）

1. 单元测试：失败分类器映射、自动重试边界（最多一次）、memory 检索排序、quality gate 判定。
2. API 测试：新增 5 个端点的参数校验、空数据返回、异常路径。
3. 流水线回归：`PLAN -> PLAN_REVIEW -> READY -> RUNNING -> REVIEW` 主链路；`FAILED/CANCELLED` 清理与产物快照不回归。
4. 前端测试：KPI 展示、失败面板渲染、语音权限拒绝降级、移动端快捷操作。
5. 手工冒烟：iPhone Safari 与桌面 Chrome 各跑一轮“创建任务-确认 Plan-执行-Review”。

## 发布与风险控制

1. 开关策略：`FEATURE_INSIGHTS`（第 2 周开）、`FEATURE_MEMORY`（第 4 周开）、`FEATURE_VOICE_INPUT`（第 6 周开）。
2. 回滚策略：新字段全部可选并提供默认值；关闭 feature flag 后系统回到旧行为。
3. 运维观察：每天固定查看 `insights/overview` 与 `insights/failures`，连续两天异常即冻结新功能只做修复。

## 明确假设与默认值

1. 维持单用户部署与 JSON 存储，不引入数据库迁移。
2. 默认 worker 数保持 3，不在本轮做分布式调度。
3. Happy 仅做产品借鉴，不做协议/服务端接入。
4. 语音输入仅限浏览器 Web Speech 能力，服务端不接入 ASR。
5. 若第 2 周基线显示成功率已超过 85%，目标改为“再提升 8pp 并降低失败波动性”。
