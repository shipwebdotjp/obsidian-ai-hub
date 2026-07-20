import string
from pathlib import Path


def render_prompt(template_path: Path, context: dict) -> str:
    """
    Loads a prompt template from a file and renders it with the given context.
    Uses ${name} placeholder style.
    """
    if not template_path.exists():
        raise FileNotFoundError(f"Prompt template not found at {template_path}")

    with open(template_path, "r", encoding="utf-8") as f:
        template_text = f.read()

    template = string.Template(template_text)
    # Using substitute to ensure all placeholders are provided.
    # If leniency is needed, safe_substitute could be used instead.
    return template.substitute(context)
