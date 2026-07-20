import os

from kiri import config

_HEADER = (
    "## Skills\n\n"
    "Procedures for what the shell cannot teach you: a tool's real surface, and "
    "the traps in it. Read a skill's file before doing the thing it covers -- it "
    "is cheaper than rediscovering it, and it records mistakes you would otherwise "
    "repeat. The owner can also invoke one directly by writing /<name>."
)

# Skills shipped with Kiri live beside this module; the owner's live in
# SKILLS_DIR and are scanned second, so a skill there shadows a built-in of the
# same name.
BUILTIN_DIR = os.path.dirname(__file__)


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
        if not line.strip():
            continue

        key, sep, value = line.partition(":")
        # A wrapped line would otherwise vanish, taking the half of the
        # description that says when to read the skill with it.
        if not sep:
            raise RuntimeError(
                f"skill {path} wraps a frontmatter line onto the next -- keep each field on one line"
            )
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def _find(directory):
    if not os.path.isdir(directory):
        return {}

    found = {}
    for name in os.listdir(directory):
        path = os.path.join(directory, name, "SKILL.md")
        if os.path.exists(path):
            found[name] = path
    return found


def _paths():
    return _find(BUILTIN_DIR) | _find(config.SKILLS_DIR)


def load(name):
    # The body a /<name> invocation force-feeds the model, frontmatter stripped:
    # the model already has the description from the index and needs the procedure.
    path = _paths().get(name)
    if path is None:
        return None

    with open(path) as f:
        text = f.read()
    if text.startswith("---\n"):
        end = text[4:].find("\n---")
        if end != -1:
            text = text[4 + end + 4 :]
    return text.strip()


def names():
    return sorted(_paths())


def index():
    # Read once at boot and folded into the base prompt: this rides in the cache
    # prefix, so it must not change between requests. `reload` re-execs, which is
    # how an edited skill takes effect.
    paths = _paths()

    lines = []
    for name, path in sorted(paths.items()):
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
