import logging
import subprocess
from datetime import datetime
from pathlib import Path
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

def get_unique_path(directory: Path, base_filename: str) -> Path:
    """
    If the target filename already exists, append a numeric suffix rather than overwriting.
    """
    path = directory / base_filename
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        new_path = directory / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1

def capture_screen(target_path: Path, display: int = 1):
    """
    Captures a macOS screenshot for a specific display and saves it to the target_path.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Run screencapture -t png -x -D <display> <path> via subprocess.run, not through a shell.
    cmd = [
        "screencapture",
        "-t", "png",
        "-x",
        "-D", str(display),
        str(target_path)
    ]

    logger.info(f"Taking screenshot on display {display} to {target_path}")
    try:
        subprocess.run(cmd, check=True, shell=False)
        logger.info("Screenshot captured successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to capture screenshot: {e}")
        raise
    return str(target_path)

def main(display: int = 1):
    """
    Captures a macOS screenshot and saves it into the Obsidian inbox.
    """
    inbox_path = config.INBOX_PATH
    if not inbox_path.exists():
        logger.info(f"Creating inbox directory: {inbox_path}")
        inbox_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screen_{timestamp}.png"
    target_path = get_unique_path(inbox_path, filename)

    return capture_screen(target_path, display)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Capture screenshot")
    parser.add_argument("--display", type=int, default=1, help="Display index")
    args = parser.parse_args()
    main(display=args.display)
