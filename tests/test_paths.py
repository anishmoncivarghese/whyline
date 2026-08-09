from whyline import paths


def test_find_repo_root_from_nested_directory(repo):
    nested = repo.path / "a" / "b"
    nested.mkdir(parents=True)
    assert paths.find_repo_root(nested) == repo.path


def test_find_repo_root_returns_none_outside_a_repo(tmp_path):
    assert paths.find_repo_root(tmp_path) is None


def test_is_initialised_is_false_before_init(repo):
    assert paths.is_initialised(repo.path) is False


def test_is_initialised_is_true_once_ledger_exists(repo):
    paths.ledger_path(repo.path).parent.mkdir(parents=True)
    paths.ledger_path(repo.path).touch()
    assert paths.is_initialised(repo.path) is True
