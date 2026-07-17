from kiri import config, resume


def test_marker_roundtrip_is_consumed_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KIRI_HOME", str(tmp_path))
    assert resume.take() is None
    resume.mark(7)
    assert resume.take() == 7
    assert resume.take() is None


def test_clear_removes_a_pending_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KIRI_HOME", str(tmp_path))
    resume.mark(1)
    resume.clear()
    assert resume.take() is None
