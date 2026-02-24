from app.core.plan_parser import build_exec_prompt, parse_plan


def test_parse_plan_success():
    raw = '{"summary":"s","questions":[{"id":"q1","title":"t","question":"?","options":[{"key":"a","label":"A"}]}],"recommended_prompt":"rp"}'
    result = parse_plan(raw)
    assert result.valid_json is True
    assert result.summary == 's'
    assert result.questions[0].id == 'q1'


def test_parse_plan_fallback():
    result = parse_plan('just text without json')
    assert result.valid_json is False
    assert result.raw_text == 'just text without json'


def test_build_exec_prompt_contains_answers():
    result = parse_plan('{"summary":"sum","questions":[],"recommended_prompt":"go"}')
    prompt = build_exec_prompt('origin', result, {'q1': 'a'})
    assert 'sum' in prompt
    assert 'q1' in prompt
    assert 'origin' in prompt
