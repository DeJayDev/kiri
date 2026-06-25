import os

from kiri import config

_DEFAULT = os.path.join(os.path.dirname(__file__), "default_prompt.md")


def load():
    # Override wins wholesale; only the engine's fail-loud behavior is enforced
    # regardless of what the prompt says.
    path = config.PROMPT_FILE or _DEFAULT
    with open(path) as f:
        return f.read().strip()
