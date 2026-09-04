import pytest
from pydantic import ValidationError
from obsidian_ai_hub.agents.ask_user import (
    ask_user,
    AskUserInput,
    AskUserQuestionItem,
    ChoiceOption,
    normalize_question_choices,
    RESERVED_CHOICE_VALUE,
)

def test_ask_user_reserved_choice_value_validation():
    with pytest.raises(ValidationError) as excinfo:
        ChoiceOption(value="other", label="その他")
    assert "reserved" in str(excinfo.value)

def test_ask_user_valid_choice_option():
    opt = ChoiceOption(value="option1", label="Option 1", description="First option")
    assert opt.value == "option1"
    assert opt.label == "Option 1"

def test_normalize_question_choices_appends_other():
    raw = [{"value": "opt1", "label": "Option 1"}]
    normalized = normalize_question_choices(raw)
    assert len(normalized) == 2
    assert normalized[1]["value"] == RESERVED_CHOICE_VALUE
    assert normalized[1]["label"] == "その他（自由入力）"

def test_ask_user_tool_invocation():
    input_data = AskUserInput(
        questions=[
            AskUserQuestionItem(
                question_id="q1",
                question="Proceed?",
                choices=[ChoiceOption(value="yes", label="Yes")],
            )
        ]
    )
    res = ask_user.invoke(input_data.model_dump())
    assert "waiting_user" in res
