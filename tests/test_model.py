from whyline import model


def test_load_returns_empty_dict_when_absent(tmp_path):
    assert model.load(tmp_path) == {}


def test_save_then_load_round_trips(tmp_path):
    model.save(tmp_path, {"codex": "gpt-5-codex"})
    assert model.load(tmp_path) == {"codex": "gpt-5-codex"}


def test_load_corrupt_file_reads_as_empty(tmp_path):
    model.paths.model_path(tmp_path).parent.mkdir(parents=True)
    model.paths.model_path(tmp_path).write_text("{broken")
    assert model.load(tmp_path) == {}


def test_load_non_dict_json_reads_as_empty(tmp_path):
    model.paths.model_path(tmp_path).parent.mkdir(parents=True)
    model.paths.model_path(tmp_path).write_text('["not", "a", "dict"]')
    assert model.load(tmp_path) == {}


def test_load_corrupt_utf8_reads_as_empty(tmp_path):
    model.paths.model_path(tmp_path).parent.mkdir(parents=True)
    model.paths.model_path(tmp_path).write_bytes(b"\x80\xff broken utf8")
    assert model.load(tmp_path) == {}


def test_set_one_adds_a_single_agent_without_disturbing_others(tmp_path):
    model.save(tmp_path, {"claude": "opus"})
    model.set_one(tmp_path, "codex", "gpt-5-codex")
    assert model.load(tmp_path) == {"claude": "opus", "codex": "gpt-5-codex"}


def test_set_one_with_a_blank_value_removes_the_key(tmp_path):
    model.save(tmp_path, {"codex": "gpt-5-codex", "claude": "opus"})
    model.set_one(tmp_path, "codex", "")
    assert model.load(tmp_path) == {"claude": "opus"}


def test_set_one_with_blank_value_when_key_does_not_exist(tmp_path):
    model.save(tmp_path, {"claude": "opus"})
    model.set_one(tmp_path, "codex", "")
    assert model.load(tmp_path) == {"claude": "opus"}
