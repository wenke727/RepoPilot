export type TaskStatus =
  | 'TODO'
  | 'PLAN_RUNNING'
  | 'PLAN_REVIEW'
  | 'READY'
  | 'RUNNING'
  | 'REVIEW'
  | 'DONE'
  | 'FAILED'
  | 'CANCELLED'

export type TaskMode = 'PLAN' | 'EXEC'
export type PermissionMode = 'BYPASS' | 'DEFAULT'

export type ExecMode = "AGENTIC" | "FIXED"
export type StrategyStepType =
  | "CODING"
  | "COMMIT"
  | "REBASE"
  | "TEST"
  | "PUSH"
  | "CREATE_PR"

export type StrategyStepStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "skipped"

export interface StrategyStep {
  type: StrategyStepType
  label: string
  params: Record<string, unknown>
  skip: boolean
  reason: string
  status: StrategyStepStatus
}

export interface StrategyDecision {
  key: string
  question: string
  choice: string
  reason: string
}

export interface ExecStrategy {
  template: string
  steps: StrategyStep[]
  decisions: StrategyDecision[]
  rationale: string
  raw_text: string
  valid: boolean
}

export interface RepoConfig {
  id: string
  name: string
  root_path: string
  main_branch: string
  test_command: string
  github_repo: string
  enabled: boolean
}

export interface PlanQuestionOption {
  key: string
  label: string
  description: string
}

export interface PlanQuestion {
  id: string
  title: string
  question: string
  options: PlanQuestionOption[]
  recommended_option_key?: string
}

export interface PlanResult {
  summary: string
  questions: PlanQuestion[]
  recommended_prompt: string
  raw_text: string
  valid_json: boolean
  // Enhanced plan details
  steps: string[]
  risks: string[]
  validation: string
  rollback: string
  affected_files: string[]
  new_dependencies: string[]
  estimated_time: string
}

export interface Task {
  id: string
  repo_id: string
  title: string
  prompt: string
  mode: TaskMode
  status: TaskStatus
  permission_mode: PermissionMode
  priority: number
  created_at: string
  updated_at: string
  current_run_id?: string
  claude_session_id?: string
  plan_result?: PlanResult
  plan_answers: Record<string, string>
  exec_strategy?: ExecStrategy
  pr_url: string
  error_code: string
  error_message: string
  cancel_requested: boolean
}

export interface BoardResponse {
  columns: Record<string, Task[]>
  counts: Record<string, number>
}

export interface NotificationItem {
  id: string
  task_id: string
  type: 'INFO' | 'SUCCESS' | 'ERROR'
  title: string
  body: string
  created_at: string
  read: boolean
}

export type TaskEventDisplayGroup = 'command' | 'output' | 'result' | 'timeout' | 'artifact' | 'protocol'

export interface TaskEventDisplay {
  group: TaskEventDisplayGroup
  label: string
  text: string
  merge_key: string
  raw: string
}

export interface TaskEvent {
  seq?: number | string
  ts?: string
  type?: string
  line?: string
  display?: TaskEventDisplay | Record<string, unknown>
  [key: string]: unknown
}

export interface EventBatch {
  next_cursor: number
  events: TaskEvent[]
}

export interface BatchTaskFailure {
  task_id: string
  error_code: 'TASK_NOT_FOUND' | 'INVALID_STATUS' | 'PLAN_RESULT_MISSING' | 'UPDATE_FAILED'
  error_message: string
}

export interface PlanBatchActionCounts {
  requested: number
  updated: number
  failed: number
}

export interface PlanBatchActionResult {
  updated: Task[]
  failed: BatchTaskFailure[]
  counts: PlanBatchActionCounts
}
