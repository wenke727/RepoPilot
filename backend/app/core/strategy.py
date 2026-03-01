from __future__ import annotations

from app.models import (
    ExecStrategy,
    RepoConfig,
    StrategyDecision,
    StrategyStep,
    StrategyStepStatus,
    StrategyStepType,
)


def build_default_strategy(repo: RepoConfig) -> ExecStrategy:
    has_tests = bool(repo.test_command and repo.test_command.strip())
    has_github = bool(repo.github_repo and "/" in repo.github_repo.strip())

    steps = [
        StrategyStep(
            type=StrategyStepType.CODING,
            label="执行编码任务",
            reason="根据需求修改代码",
            status=StrategyStepStatus.PENDING,
        ),
        StrategyStep(
            type=StrategyStepType.COMMIT,
            label="提交变更",
            params={"message": "task({id}): apply changes"},
            reason="保存工作区变更",
            status=StrategyStepStatus.PENDING,
        ),
        StrategyStep(
            type=StrategyStepType.REBASE,
            label="变基到主分支",
            reason="保持线性历史",
            status=StrategyStepStatus.PENDING,
        ),
        StrategyStep(
            type=StrategyStepType.TEST,
            label="运行测试",
            skip=not has_tests,
            reason="仓库已配置测试命令" if has_tests else "未配置测试命令，跳过",
            status=StrategyStepStatus.PENDING,
        ),
        StrategyStep(
            type=StrategyStepType.PUSH,
            label="推送分支",
            reason="推送到远程",
            status=StrategyStepStatus.PENDING,
        ),
        StrategyStep(
            type=StrategyStepType.CREATE_PR,
            label="创建 PR",
            skip=not has_github,
            reason="仓库配置了 GitHub 远程" if has_github else "未配置 GitHub 远程，跳过",
            status=StrategyStepStatus.PENDING,
        ),
    ]
    decisions = [
        StrategyDecision(
            key="test_strategy",
            question="是否运行测试",
            choice="是" if has_tests else "否",
            reason="仓库有配置 test_command" if has_tests else "未配置 test_command",
        ),
        StrategyDecision(
            key="pr_strategy",
            question="是否创建 PR",
            choice="是" if has_github else "否",
            reason="仓库配置了 github_repo" if has_github else "未配置 github_repo",
        ),
    ]
    return ExecStrategy(
        template="AGENTIC",
        steps=steps,
        decisions=decisions,
        rationale="Claude 全权执行：编码后自行完成提交、变基、测试、推送并创建 PR（按仓库配置）",
        raw_text="",
        valid=True,
    )
