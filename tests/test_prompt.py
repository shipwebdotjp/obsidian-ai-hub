import pytest
from pathlib import Path
from obsidian_ai_hub.utils.prompt import render_prompt

def test_render_prompt(tmp_path):
    template_file = tmp_path / "test_prompt.md"
    template_file.write_text("Hello, ${name}! Welcome to ${place}.", encoding="utf-8")

    context = {"name": "Alice", "place": "Wonderland"}
    rendered = render_prompt(template_file, context)

    assert rendered == "Hello, Alice! Welcome to Wonderland."

def test_render_prompt_missing_file():
    with pytest.raises(FileNotFoundError):
        render_prompt(Path("non_existent_file.md"), {})

def test_render_prompt_missing_placeholder(tmp_path):
    template_file = tmp_path / "test_prompt.md"
    template_file.write_text("Hello, ${name}!", encoding="utf-8")

    with pytest.raises(KeyError):
        render_prompt(template_file, {})
