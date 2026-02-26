# Plan 功能实现文档

> 对 PRD v1.1 的实现对照与技术细节
>
> 更新时间: 2026-02-26

---

## 一、功能概述

Plan 功能是 Claude Code Web Manager 的核心特性，实现 **Plan-first** 工作流：
1. 先创建 Plan Task，生成执行计划但不执行代码
2. 人工 Review 计划，回答决策问题
3. 批准后创建 Do Task 并执行

---

## 二、数据模型

### 2.1 PlanResult (后端)

**文件:** `backend/app/models.py`

```python
class PlanResult(BaseModel):
    # 基础字段
    summary: str = ""                    # 目标摘要
    questions: list[PlanQuestion] = ...   # 决策问题列表
    recommended_prompt: str = ""         # 建议的执行提示词
    raw_text: str = ""                   # 原始输出
    valid_json: bool = False             # JSON 是否可解析

    # 增强字段 (v1.1)
    steps: list[str] = ...               # 实施步骤
    risks: list[str] = ...               # 风险评估
    validation: str = ""                 # 验证方法
    rollback: str = ""                   # 回滚方式
    affected_files: list[str] = ...      # 涉及文件
    new_dependencies: list[str] = ...    # 新增依赖
    estimated_time: str = ""             # 预计执行时间
```

### 2.2 PlanResult (前端)

**文件:** `frontend/src/types/index.ts`

```typescript
export interface PlanResult {
  summary: string
  questions: PlanQuestion[]
  recommended_prompt: string
  raw_text: string
  valid_json: boolean
  // 增强字段
  steps: string[]
  risks: string[]
  validation: string
  rollback: string
  affected_files: string[]
  new_dependencies: string[]
  estimated_time: string
}
```

---

## 三、Plan 提示词工程

### 3.1 提示词模板

**文件:** `backend/app/core/plan_parser.py`

```python
def plan_prompt(task_prompt: str) -> str:
    schema = {
        "summary": "执行前计划摘要（1-2句话描述目标）",
        "steps": ["步骤1: 具体操作", "步骤2: 具体操作"],
        "risks": ["风险1: 描述", "风险2: 描述"],
        "affected_files": ["path/to/file1", "path/to/file2"],
        "new_dependencies": ["package1", "package2"],
        "estimated_time": "预计执行时间（如：5-10分钟）",
        "validation": "如何验证实现正确",
        "rollback": "如何回滚改动",
        "questions": [...],
        "recommended_prompt": "建议进入执行模式时使用的最终 Prompt",
    }
    return (
        "你现在在 Plan 模式。\n"
        "你的任务是分析需求并制定详细的执行计划，而不是直接修改代码。\n\n"
        "请返回一个 JSON 对象（必须可解析），包含以下字段：\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        # ... 字段说明
        "用户需求如下：\n"
        f"{task_prompt}"
    )
```

### 3.2 设计原则

1. **明确声明 Plan 模式** - 防止 Claude 直接执行代码
2. **结构化输出要求** - JSON schema 保证可解析性
3. **决策分离** - questions 字段将需要用户决策的内容显式化
4. **上下文传递** - recommended_prompt 保存 Claude 认为的最佳执行提示词

---

## 四、UI 交互设计

### 4.1 任务卡片 (TaskCard)

**文件:** `frontend/src/components/TaskCard.tsx`

| PRD 要求 | 实现方式 |
|---------|---------|
| 目标摘要 | 显示 `plan_result.summary` 而非原始 prompt |
| 风险等级 | 根据 `risks` 数组长度计算: >=3 高风险, >=2 中风险, 1 低风险 |
| Mode 标识 | `[Plan]` 紫色标签 |

```typescript
function getRiskLevel(task: Task): 'high' | 'medium' | 'low' | null {
  if (!task.plan_result?.risks || task.plan_result.risks.length === 0) return null
  const risks = task.plan_result.risks
  if (risks.length >= 3) return 'high'
  if (risks.length >= 2) return 'medium'
  return 'low'
}
```

### 4.2 Plan Review 面板 (TaskDetailPage)

**文件:** `frontend/src/pages/TaskDetailPage.tsx`

**面板结构:**

```
┌─────────────────────────────────────┐
│ Plan 审批                            │
│ [summary 摘要]                       │
├─────────────────────────────────────┤
│ 实施步骤:                            │
│ 1. 步骤一                            │
│ 2. 步骤二                            │
├─────────────────────────────────────┤
│ 风险评估:                            │
│ • 风险一                             │
│ • 风险二                             │
├─────────────────────────────────────┤
│ 涉及文件: [file1] [file2]            │
│ 新增依赖: [dep1] [dep2]              │
│ 预计执行时间: 5-10 分钟              │
│ 验证方法: ...                        │
│ 回滚方式: ...                        │
├─────────────────────────────────────┤
│ 决策问题:                            │
│ Q: 问题标题                          │
│   [选项A] [选项B] [选项C]            │
├─────────────────────────────────────┤
│ [确认并执行] [修改反馈] [放弃 Plan]  │
└─────────────────────────────────────┘
```

### 4.3 样式定义

**文件:** `frontend/src/styles.css`

```css
/* 风险等级标签 */
.status-risk-high { border-color: #f5c6c6; color: #c53b3b; }
.status-risk-medium { border-color: #f5dcc6; color: #c5753b; }
.status-risk-low { border-color: #e8f5c6; color: #7aa33b; }

/* Plan 详情区块 */
.plan-details-section { border-top: 1px solid #e1e8f1; }
.plan-detail-block { margin-bottom: 10px; }
.plan-file-item, .plan-dep-item { border-radius: 6px; font-family: monospace; }
```

---

## 五、API 端点

### 5.1 Plan 确认

**请求:**
```http
POST /api/tasks/{task_id}/plan/confirm
Content-Type: application/json

{
  "answers": {
    "q1": "a",
    "q2": "option_x"
  }
}
```

**响应:** Task (状态变为 `READY`)

### 5.2 Plan 修改

**请求:**
```http
POST /api/tasks/{task_id}/plan/revise
Content-Type: application/json

{
  "feedback": "请考虑使用不同的方案..."
}
```

**响应:** Task (状态变回 `PLAN_RUNNING`)

### 5.3 批量操作

```http
# 批量确认
POST /api/tasks/plan/batch-confirm
{"task_ids": ["id1", "id2"]}

# 批量退回
POST /api/tasks/plan/batch-revise
{"task_ids": ["id1", "id2"], "feedback": "..."}
```

---

## 六、状态流转

### 6.1 Plan Task 生命周期

```
TODO → PLAN_RUNNING → PLAN_REVIEW → READY → RUNNING → DONE/FAILED
                                ↓
                            (修改反馈)
                                ↓
                         PLAN_RUNNING
```

### 6.2 状态说明

| 状态 | 含义 | 所在列 |
|-----|------|-------|
| `TODO` | 待执行 | 待开发 |
| `PLAN_RUNNING` | Plan 生成中 | 开发中 |
| `PLAN_REVIEW` | 等待人工决策 | 待 Review |
| `READY` | 已批准，等待执行 | 待开发 |
| `RUNNING` | 执行中 | 开发中 |
| `DONE` | 完成 | 已完成 |
| `FAILED` | 失败 | 失败 |

---

## 七、默认行为变更

### 7.1 默认模式

**文件:** `backend/app/models.py`, `frontend/src/components/TaskComposer.tsx`

```python
# 后端默认
class TaskCreateInput(BaseModel):
    mode: TaskMode = TaskMode.PLAN  # 原为 EXEC
```

```typescript
// 前端默认
const [mode, setMode] = useState<TaskMode>('PLAN')  // 原为 'EXEC'
```

### 7.2 提示文案

**原:** `Enter 换行，Cmd/Ctrl+Enter 提交 | 点击麦克风语音输入`

**新:** `Plan 先行，确认后执行 | Cmd/Ctrl+Enter 提交`

---

## 八、PRD 对照表

| PRD 要求 | 实现状态 | 说明 |
|---------|---------|------|
| Plan Task 一等公民 | ✅ | 独立状态、独立流程 |
| Plan 卡片目标摘要 | ✅ | 显示 `plan_result.summary` |
| Plan 卡片风险等级 | ✅ | 高/中/低三级标签 |
| Plan Review 执行步骤 | ✅ | `plan_result.steps` 列表 |
| Plan Review 风险评估 | ✅ | `plan_result.risks` 列表 |
| Plan Review 涉及文件 | ✅ | `plan_result.affected_files` 列表 |
| Plan Review 新增依赖 | ✅ | `plan_result.new_dependencies` 列表 |
| Plan Review 预计时间 | ✅ | `plan_result.estimated_time` 字段 |
| Plan Review 验证方法 | ✅ | `plan_result.validation` 字段 |
| Plan Review 回滚方式 | ✅ | `plan_result.rollback` 字段 |
| 决策问题交互 | ✅ | Pill 按钮，推荐答案自动选中 |
| 批量 Review | ✅ | 批量确认/退回 |
| 放弃 Plan 按钮 | ✅ | 独立取消按钮 |
| Plan 默认模式 | ✅ | 创建任务默认 Plan 模式 |
| 断线重连 | ✅ | cursor 机制 |
| 日志可观测 | ✅ | 实时流式输出 |

---

## 九、关键文件索引

| 模块 | 后端文件 | 前端文件 |
|-----|---------|---------|
| 数据模型 | `backend/app/models.py` | `frontend/src/types/index.ts` |
| Plan 解析 | `backend/app/core/plan_parser.py` | - |
| Plan API | `backend/app/api/tasks.py` | - |
| 看板页面 | `backend/app/api/board.py` | `frontend/src/pages/BoardPage.tsx` |
| 任务详情 | `backend/app/api/tasks.py` | `frontend/src/pages/TaskDetailPage.tsx` |
| 任务卡片 | - | `frontend/src/components/TaskCard.tsx` |
| 任务创建 | - | `frontend/src/components/TaskComposer.tsx` |
| 样式 | - | `frontend/src/styles.css` |
