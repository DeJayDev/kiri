import os

from kiri import config

_HEADER = (
    "## Skills\n\n"
    "Procedures for what the shell cannot teach you: a tool's real surface, and "
    "the traps in it. Read a skill's file before doing the thing it covers -- it "
    "is cheaper than rediscovering it, and it records mistakes you would otherwise "
    "repeat. The owner can also invoke one directly by writing /<name>."
)


def _frontmatter(path):
    with open(path) as f:
        text = f.read()

    if not text.startswith("---\n"):
        raise RuntimeError(f"skill {path} has no frontmatter (it must open with ---)")

    body = text[4:]
    end = body.find("\n---")
    if end == -1:
        raise RuntimeError(f"skill {path} has an unterminated frontmatter block")

    fields = {}
    for line in body[:end].splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def index():
    # Read once at boot and folded into the base prompt: this rides in the cache
    # prefix, so it must not change between requests. `reload` re-execs, which is
    # how an edited skill takes effect.
    if not os.path.isdir(config.SKILLS_DIR):
        return ""

    lines = []
    for name in sorted(os.listdir(config.SKILLS_DIR)):
        path = os.path.join(config.SKILLS_DIR, name, "SKILL.md")
        if not os.path.exists(path):
            continue

        fields = _frontmatter(path)
        description = fields.get("description")
        if not description:
            raise RuntimeError(
                f"skill {path} has no description -- the model cannot know when to read it"
            )
        lines.append(f"- {fields.get('name', name)} ({path}): {description}")

    if not lines:
        return ""
    return _HEADER + "\n\n" + "\n".join(lines)
