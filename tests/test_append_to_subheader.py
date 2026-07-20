import pytest
from obsidian_ai_hub.utils.extracter import append_to_subheader


# --- フィクスチャ ---


@pytest.fixture
def basic_md():
    return "# Main Header\n\n## subheader1\n- line1\n\n## subheader2\n- itemA\n"


@pytest.fixture
def 末尾セクションmd():
    """対象セクションがファイル末尾にある場合"""
    return (
        "# Main Header\n\n## subheader1\n- line1\n\n## subheader2\n- itemA\n- itemB\n"
    )


# --- 既存ヘッダーへの追記 ---


class TestAppendToExistingHeader:
    def test_追記された行が含まれる(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader1", ["- line2"])
        assert "- line2" in result

    def test_追記位置が正しい(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader1", ["- line2"])
        lines = result.splitlines()
        idx_header = lines.index("## subheader1")
        idx_line1 = lines.index("- line1")
        idx_line2 = lines.index("- line2")
        assert idx_header < idx_line1 < idx_line2

    def test_次のヘッダーより前に挿入される(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader1", ["- line2"])
        lines = result.splitlines()
        assert lines.index("- line2") < lines.index("## subheader2")

    def test_他のセクションが変化しない(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader1", ["- line2"])
        assert "## subheader2" in result
        assert "- itemA" in result

    def test_複数行追記(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader1", ["- line2", "- line3"])
        assert "- line2" in result
        assert "- line3" in result

    def test_末尾セクションへの追記(self, 末尾セクションmd):
        result = append_to_subheader(末尾セクションmd, "## subheader2", ["- itemC"])
        assert "- itemC" in result
        lines = result.splitlines()
        assert lines.index("- itemC") > lines.index("- itemB")


# --- ヘッダーが存在しない場合（末尾に新規追加）---


class TestAppendNewHeader:
    def test_新規ヘッダーが末尾に追加される(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader3", ["- newItem"])
        assert "## subheader3" in result
        assert "- newItem" in result

    def test_新規ヘッダーが既存ヘッダーより後にある(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader3", ["- newItem"])
        lines = result.splitlines()
        assert lines.index("## subheader3") > lines.index("## subheader2")

    def test_新規ヘッダーの直後にコンテンツがある(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader3", ["- newItem"])
        lines = result.splitlines()
        idx = lines.index("## subheader3")
        assert lines[idx + 1] == "- newItem"

    def test_新規追加時に空行で区切られる(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader3", ["- newItem"])
        lines = result.splitlines()
        idx = lines.index("## subheader3")
        assert lines[idx - 1] == ""

    def test_既存コンテンツが変化しない(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader3", ["- newItem"])
        assert "## subheader1" in result
        assert "- line1" in result
        assert "## subheader2" in result
        assert "- itemA" in result


# --- 末尾改行 ---


class TestTrailingNewline:
    def test_既存ヘッダー追記後も末尾改行あり(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader1", ["- line2"])
        assert result.endswith("\n")

    def test_新規ヘッダー追加後も末尾改行あり(self, basic_md):
        result = append_to_subheader(basic_md, "## subheader3", ["- newItem"])
        assert result.endswith("\n")
