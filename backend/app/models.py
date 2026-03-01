from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

DEFAULT_TEST_COMMAND = "npm run test:ci --if-present || echo skip-tests"


class TaskStatus(str, Enum):
    TODO = "TODO"
    PLAN_RUNNING = "PLAN_RUNNING"
    PLAN_REVIEW = "PLAN_REVIEW"
    READY = "READY"
    RUNNING = "RUNNING"
    REVIEW = "REVIEW"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskMode(str, Enum):
    PLAN = "PLAN"
    EXEC = "EXEC"


class PermissionMode(str, Enum):
    BYPASS = "BYPASS"
    DEFAULT = "DEFAULT"


class ExecMode(str, Enum):
    AGENTIC = "AGENTIC"
    FIXED = "FIXED"


class StrategyStepType(str, Enum):
    CODING = "CODING"
    COMMIT = "COMMIT"
    REBASE = "REBASE"
    TEST = "TEST"
    PUSH = "PUSH"
    CREATE_PR = "CREATE_PR"


class StrategyStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class StrategyDecision(BaseModel):
    key: str
    question: str = ""
    choice: str = ""
    reason: str = ""


class StrategyStep(BaseModel):
    type: StrategyStepType
    label: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    skip: bool = False
    reason: str = ""
    status: StrategyStepStatus = StrategyStepStatus.PENDING


class ExecStrategy(BaseModel):
    template: str = ""
    steps: list[StrategyStep] = Field(default_factory=list)
    decisions: list[StrategyDecision] = Field(default_factory=list)
    rationale: str = ""
    raw_text: str = ""
    valid: bool = False


class RepoConfig(BaseModel):
    id: str
    name: str
    root_path: str
    main_branch: str = "main"
    test_command: str = DEFAULT_TEST_COMMAND
    github_repo: str = ""
    shared_symlink_paths: list[str] = Field(default_factory=list)
    forbidden_symlink_paths: list[str] = Field(default_factory=lambda: ["PROGRESS.md"])
    enabled: bool = True


class PlanQuestionOption(BaseModel):
    key: str
    label: str
    description: str = ""


class PlanQuestion(BaseModel):
    id: str
    title: str
    question: str
    options: list[PlanQuestionOption] = Field(default_factory=list)
    recommended_option_key: str | None = None


class PlanResult(BaseModel):
    summary: str = ""
    questions: list[PlanQuestion] = Field(default_factory=list)
    recommended_prompt: str = ""
    raw_text: str = ""
    valid_json: bool = False
    # New fields for enhanced plan details
    steps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    validation: str = ""
    rollback: str = ""
    affected_files: list[str] = Field(default_factory=list)
    new_dependencies: list[str] = Field(default_factory=list)
    estimated_time: str = ""


class Task(BaseModel):
    id: str
    repo_id: str
    title: str
    prompt: str
    mode: TaskMode
    status: TaskStatus = TaskStatus.TODO
    permission_mode: PermissionMode = PermissionMode.BYPASS
    priority: int = 0
    created_at: str
    updated_at: str
    current_run_id: str | None = None
    claude_session_id: str | None = None
    plan_result: PlanResult | None = None
    plan_answers: dict[str, str] = Field(default_factory=dict)
    exec_strategy: ExecStrategy | None = None
    pr_url: str = ""
    error_code: str = ""
    error_message: str = ""
    cancel_requested: bool = False


class TaskRun(BaseModel):
    id: str
    task_id: str
    worker_id: str
    attempt: int
    started_at: str
    ended_at: str | None = None
    exit_code: int | None = None
    worktree_path: str = ""
    branch_name: str = ""
    commit_sha: str = ""
    python_env_used: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


class Notification(BaseModel):
    id: str
    task_id: str
    type: Literal["INFO", "SUCCESS", "ERROR"] = "INFO"
    title: str
    body: str
    created_at: str
    read: bool = False


class TaskCreateInput(BaseModel):
    repo_id: str
    title: str
    prompt: str
    mode: TaskMode = TaskMode.PLAN
    permission_mode: PermissionMode = PermissionMode.BYPASS
    priority: int = 0


class TaskRetryInput(BaseModel):
    reset_mode: TaskMode | None = None


class PlanConfirmInput(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class PlanReviseInput(BaseModel):
    feedback: str


class PlanBatchConfirmInput(BaseModel):
    task_ids: list[str] = Field(default_factory=list)


class PlanBatchReviseInput(BaseModel):
    task_ids: list[str] = Field(default_factory=list)
    feedback: str


class BatchTaskFailure(BaseModel):
    task_id: str
    error_code: str
    error_message: str


class PlanBatchActionResult(BaseModel):
    updated: list[Task] = Field(default_factory=list)
    failed: list[BatchTaskFailure] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class RepoPatchInput(BaseModel):
    enabled: bool | None = None
    test_command: str | None = None
    main_branch: str | None = None


class EventBatch(BaseModel):
    next_cursor: int
    events: list[dict[str, Any]]


class BoardResponse(BaseModel):
    columns: dict[str, list[Task]]
    counts: dict[str, int]


class HealthResponse(BaseModel):
    status: str
    python_env_selected: str
    dependencies: dict[str, bool]
    paths: dict[str, str]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
