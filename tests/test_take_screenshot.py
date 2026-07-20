import subprocess
from unittest.mock import patch
from obsidian_ai_hub import take_screenshot


def test_get_unique_path(tmp_path):
    directory = tmp_path / "inbox"
    directory.mkdir()
    filename = "screen_20260528_183000.png"

    # Test non-existing path
    path = take_screenshot.get_unique_path(directory, filename)
    assert path == directory / filename

    # Test existing path
    (directory / filename).touch()
    path = take_screenshot.get_unique_path(directory, filename)
    assert path == directory / "screen_20260528_183000_1.png"

    # Test multiple existing paths
    (directory / "screen_20260528_183000_1.png").touch()
    path = take_screenshot.get_unique_path(directory, filename)
    assert path == directory / "screen_20260528_183000_2.png"


@patch("obsidian_ai_hub.take_screenshot.subprocess.run")
@patch("obsidian_ai_hub.take_screenshot.config")
def test_take_screenshot_main(mock_config, mock_run, tmp_path):
    inbox_dir = tmp_path / "inbox"
    mock_config.INBOX_PATH = inbox_dir

    # Run main
    take_screenshot.main(display=2)

    # Verify inbox directory creation
    assert inbox_dir.exists()

    # Verify subprocess call
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "screencapture"
    assert "-t" in cmd
    assert "png" in cmd
    assert "-x" in cmd
    assert "-D" in cmd
    assert "2" in cmd
    assert str(inbox_dir) in cmd[-1]
    assert "screen_" in cmd[-1]
    assert cmd[-1].endswith(".png")
    assert kwargs["shell"] is False
    assert kwargs["check"] is True


@patch("obsidian_ai_hub.take_screenshot.subprocess.run")
@patch("obsidian_ai_hub.take_screenshot.config")
def test_take_screenshot_window_id(mock_config, mock_run, tmp_path):
    inbox_dir = tmp_path / "inbox"
    mock_config.INBOX_PATH = inbox_dir

    # Run main with window_id
    take_screenshot.main(window_id=12345)

    # Verify subprocess call
    mock_run.assert_called_once()
    args, _ = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "screencapture"
    assert "-l" in cmd
    assert "12345" in cmd
    assert "-D" not in cmd
    assert cmd[-1].endswith(".png")


@patch("obsidian_ai_hub.take_screenshot.subprocess.run")
@patch("obsidian_ai_hub.take_screenshot.config")
def test_take_screenshot_failure(mock_config, mock_run, tmp_path):
    mock_config.INBOX_PATH = tmp_path / "inbox"
    mock_run.side_effect = subprocess.CalledProcessError(1, "screencapture")

    try:
        take_screenshot.main()
    except subprocess.CalledProcessError:
        pass
    else:
        assert False, "Should have raised CalledProcessError"
