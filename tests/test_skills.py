import pytest

from kiri import config, skills


@pytest.fixture(autouse=True)
def builtin_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "BUILTIN_DIR", str(tmp_path / "builtin"))
    return tmp_path / "builtin"


@pytest.fixture(autouse=True)
def skills_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SKILLS_DIR", str(tmp_path / "skills"))
    return tmp_path / "skills"


def _write(skills_dir, name, text):
    path = skills_dir / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(text)


def test_no_skills_dir_costs_nothing(skills_dir):
    assert skills.index() == ""


def test_an_empty_skills_dir_costs_nothing(skills_dir):
    skills_dir.mkdir(parents=True)
    assert skills.index() == ""


def test_the_index_carries_the_description_but_never_the_body(skills_dir):
    _write(
        skills_dir,
        "todoist-cli",
        '---\nname: todoist-cli\ndescription: "Manage Todoist via the td CLI."\n---\n\n'
        "Never curl the attachment url.\n",
    )

    index = skills.index()

    assert "Manage Todoist via the td CLI." in index
    assert "Never curl the attachment url." not in index


def test_a_skill_without_a_description_fails_loud(skills_dir):
    _write(skills_dir, "broken", "---\nname: broken\n---\n\nbody\n")

    with pytest.raises(RuntimeError, match="no description"):
        skills.index()


def test_a_skill_without_frontmatter_fails_loud(skills_dir):
    _write(skills_dir, "broken", "# just a heading\n")

    with pytest.raises(RuntimeError, match="no frontmatter"):
        skills.index()


def test_a_wrapped_description_fails_loud_instead_of_losing_its_second_half(skills_dir):
    _write(
        skills_dir,
        "todoist-cli",
        "---\nname: todoist-cli\ndescription: Manage tasks via the td CLI. Use when the owner\n"
        "  mentions tasks, inbox, today, or projects.\n---\n",
    )

    with pytest.raises(RuntimeError, match="one line"):
        skills.index()


def test_a_description_keeps_everything_after_the_first_colon(skills_dir):
    _write(skills_dir, "wttr", "---\nname: wttr\ndescription: Weather: never fetch the png.\n---\n")

    assert "Weather: never fetch the png." in skills.index()


def test_a_directory_without_a_skill_file_is_ignored(skills_dir):
    (skills_dir / "scratch").mkdir(parents=True)
    assert skills.index() == ""


def test_skills_are_indexed_in_a_stable_order(skills_dir):
    _write(skills_dir, "b-skill", "---\nname: b-skill\ndescription: B.\n---\n")
    _write(skills_dir, "a-skill", "---\nname: a-skill\ndescription: A.\n---\n")

    index = skills.index()

    assert index.index("a-skill") < index.index("b-skill")
