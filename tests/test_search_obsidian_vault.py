import json
from unittest.mock import patch
import io
from contextlib import redirect_stdout, redirect_stderr
from obsidian_ai_hub import search_obsidian_vault

def test_search_obsidian_vault_json_output():
    mock_results = [
        {"content": "test content", "metadata": {"file_path": "test.md"}, "score": 0.9}
    ]
    with patch("obsidian_ai_hub.search_obsidian_vault.retriever.func", return_value=json.dumps(mock_results)) as mock_search:
        f = io.StringIO()
        with redirect_stdout(f):
            search_obsidian_vault.main(query="test", json_output=True)

        output = f.getvalue().strip()
        assert output == json.dumps(mock_results)
        mock_search.assert_called_once_with(query="test", k=10, search_mode="hybrid")

def test_search_obsidian_vault_human_output():
    mock_results = [
        {"content": "test content", "metadata": {"file_path": "test.md"}, "score": 0.9}
    ]
    with patch("obsidian_ai_hub.search_obsidian_vault.retriever.func", return_value=json.dumps(mock_results)) as mock_search:
        f = io.StringIO()
        with redirect_stdout(f):
            search_obsidian_vault.main(query="test", json_output=False)

        output = f.getvalue()
        assert "1. [0.9000] test.md" in output
        assert "test content" in output
        mock_search.assert_called_once_with(query="test", k=10, search_mode="hybrid")

def test_search_obsidian_vault_no_results():
    mock_results = []
    with patch("obsidian_ai_hub.search_obsidian_vault.retriever.func", return_value=json.dumps(mock_results)):
        f = io.StringIO()
        with redirect_stdout(f):
            search_obsidian_vault.main(query="test", json_output=False)

        output = f.getvalue().strip()
        assert "No results found." in output

def test_search_obsidian_vault_error_handling():
    mock_error = {"error": "Something went wrong"}
    with patch("obsidian_ai_hub.search_obsidian_vault.retriever.func", return_value=json.dumps(mock_error)):
        f = io.StringIO()
        with redirect_stderr(f):
            try:
                search_obsidian_vault.main(query="test", json_output=False)
            except SystemExit:
                pass

        output = f.getvalue().strip()
        assert "Error: Something went wrong" in output
