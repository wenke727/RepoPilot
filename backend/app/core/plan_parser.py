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
    )


def plan_prompt(task_prompt: str) -> str:
    schema = {
        "summary": "执行前计划摘要",
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
        "请先分析用户需求，再返回一个 JSON 对象（必须可解析），字段严格包含："
        f"{json.dumps(schema, ensure_ascii=False)}\n"
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
