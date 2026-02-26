from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any

from app.models import PlanQuestion, PlanQuestionOption, PlanResult


def _extract_json_candidate(text: str) -> dict[str, Any] | None:
    start_positions = [idx for idx, ch in enumerate(text) if ch == "{"]
    for start in start_positions:
        depth = 0
        for end in range(start, len(text)):
            ch = text[end]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : end + 1]
                    try:
                        value = json.loads(candidate)
                    except JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        return value
                    break
    return None


def parse_plan(raw_text: str) -> PlanResult:
    candidate = _extract_json_candidate(raw_text)
    if not candidate:
        return PlanResult(summary="", questions=[], recommended_prompt="", raw_text=raw_text, valid_json=False)

    summary = str(candidate.get("summary", "")).strip()
    recommended_prompt = str(candidate.get("recommended_prompt", "")).strip()

    # Parse new enhanced fields
    steps_raw = candidate.get("steps", [])
    steps = [str(s).strip() for s in steps_raw if str(s).strip()] if isinstance(steps_raw, list) else []

    risks_raw = candidate.get("risks", [])
    risks = [str(r).strip() for r in risks_raw if str(r).strip()] if isinstance(risks_raw, list) else []

    validation = str(candidate.get("validation", "")).strip()
    rollback = str(candidate.get("rollback", "")).strip()
    estimated_time = str(candidate.get("estimated_time", "")).strip()

    affected_files_raw = candidate.get("affected_files", [])
    affected_files = [str(f).strip() for f in affected_files_raw if str(f).strip()] if isinstance(affected_files_raw, list) else []

    new_dependencies_raw = candidate.get("new_dependencies", [])
    new_dependencies = [str(d).strip() for d in new_dependencies_raw if str(d).strip()] if isinstance(new_dependencies_raw, list) else []

    # Parse questions
    questions_raw = candidate.get("questions", [])
    questions: list[PlanQuestion] = []

    if isinstance(questions_raw, list):
        for idx, q in enumerate(questions_raw):
            if not isinstance(q, dict):
                continue
            options: list[PlanQuestionOption] = []
            for opt in q.get("options", []):
                if not isinstance(opt, dict):
                    continue
                key = str(opt.get("key", "")).strip() or f"o{len(options) + 1}"
                options.append(
                    PlanQuestionOption(
                        key=key,
                        label=str(opt.get("label", key)),
                        description=str(opt.get("description", "")),
                    )
                )

            qid = str(q.get("id", "")).strip() or f"q{idx + 1}"
            questions.append(
                PlanQuestion(
                    id=qid,
                    title=str(q.get("title", qid)),
                    question=str(q.get("question", "")).strip(),
                    options=options,
                    recommended_option_key=q.get("recommended_option_key"),
                )
            )

    return PlanResult(
        summary=summary,
        questions=questions,
        recommended_prompt=recommended_prompt,
        raw_text=raw_text,
        valid_json=True,
        steps=steps,
        risks=risks,
        validation=validation,
        rollback=rollback,
        affected_files=affected_files,
        new_dependencies=new_dependencies,
        estimated_time=estimated_time,
    )


def plan_prompt(task_prompt: str) -> str:
    schema = {
        "summary": "执行前计划摘要（1-2句话描述目标）",
        "steps": ["步骤1: 具体操作", "步骤2: 具体操作"],
        "risks": ["风险1: 描述", "风险2: 描述"],
        "affected_files": ["path/to/file1", "path/to/file2"],
        "new_dependencies": ["package1", "package2"],
        "estimated_time": "预计执行时间（如：5-10分钟）",
        "validation": "如何验证实现正确（如：运行哪些测试，检查什么行为）",
        "rollback": "如何回滚改动（如：删除哪些文件，恢复哪些配置）",
        "questions": [
            {
                "id": "q1",
                "title": "决策项标题",
                "question": "你要确认的关键问题",
                "options": [
                    {"key": "a", "label": "选项A", "description": "影响"},
                    {"key": "b", "label": "选项B", "description": "影响"},
                ],
                "recommended_option_key": "a",
            }
        ],
        "recommended_prompt": "建议进入执行模式时使用的最终 Prompt",
    }
    return (
        "你现在在 Plan 模式。\n"
        "你的任务是分析需求并制定详细的执行计划，而不是直接修改代码。\n\n"
        "请返回一个 JSON 对象（必须可解析），包含以下字段：\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        "字段说明：\n"
        "- summary: 目标摘要\n"
        "- steps: 实现步骤列表\n"
        "- risks: 潜在风险列表（如性能影响、兼容性问题）\n"
        "- affected_files: 将要修改的文件路径列表\n"
        "- new_dependencies: 需要安装的新依赖包列表（如无则空数组）\n"
        "- estimated_time: 预计执行时间\n"
        "- validation: 验证方法\n"
        "- rollback: 回滚方法\n"
        "- questions: 需要用户确认的决策项\n"
        "- recommended_prompt: 建议的执行提示词\n\n"
        "JSON 后面可以追加简短说明。\n"
        "用户需求如下：\n"
        f"{task_prompt}"
    )


def build_exec_prompt(original_prompt: str, plan: PlanResult | None, answers: dict[str, str]) -> str:
    if not plan:
        return original_prompt

    lines = ["以下是已确认的执行上下文："]
    if plan.summary:
        lines.append(f"- 计划摘要: {plan.summary}")

    if answers:
        lines.append("- 用户确认:")
        for key, value in answers.items():
            lines.append(f"  - {key}: {value}")

    if plan.recommended_prompt:
        lines.append("- 建议执行 Prompt:")
        lines.append(plan.recommended_prompt)

    lines.append("- 原始需求:")
    lines.append(original_prompt)
    return "\n".join(lines)
