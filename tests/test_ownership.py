from concurrent.futures import ThreadPoolExecutor

from whyline import ownership


def test_different_actors_claiming_the_same_file_get_a_warning(repo):
    ownership.claim(
        repo.path,
        task="WL-42",
        actor="codex",
        role="implementer",
        files=["src/a.py"],
    )

    state, conflicts = ownership.claim(
        repo.path,
        task="WL-43",
        actor="claude",
        role="reviewer",
        files=["src/a.py"],
    )

    assert len(state["claims"]) == 2
    assert len(conflicts) == 1
    assert conflicts[0]["files"] == ["src/a.py"]
    assert set(conflicts[0]["actors"]) == {"codex", "claude"}


def test_same_actor_and_task_replaces_its_claim(repo):
    ownership.claim(
        repo.path, task="WL-42", actor="codex", role="planner", files=["a.py"]
    )

    state, conflicts = ownership.claim(
        repo.path,
        task="WL-42",
        actor="codex",
        role="implementer",
        files=["b.py"],
    )

    assert conflicts == []
    assert len(state["claims"]) == 1
    assert state["claims"][0]["files"] == ["b.py"]
    assert state["claims"][0]["role"] == "implementer"


def test_empty_file_claims_conflict_on_the_same_task(repo):
    ownership.claim(repo.path, task="WL-42", actor="codex", role="", files=[])

    _state, conflicts = ownership.claim(
        repo.path, task="WL-42", actor="claude", role="", files=[]
    )

    assert len(conflicts) == 1
    assert conflicts[0]["task_conflict"] is True


def test_release_is_idempotent_and_scoped_to_actor(repo):
    ownership.claim(repo.path, task="WL-42", actor="codex", role="", files=[])
    ownership.claim(repo.path, task="WL-42", actor="claude", role="", files=[])

    first = ownership.release(repo.path, task="WL-42", actor="codex")
    second = ownership.release(repo.path, task="WL-42", actor="codex")

    assert [claim["actor"] for claim in first["claims"]] == ["claude"]
    assert second == first


def test_load_starts_with_an_empty_versioned_state(repo):
    assert ownership.load(repo.path) == {"v": 1, "claims": []}


def test_concurrent_claims_do_not_overwrite_each_other(repo):
    def add(index):
        ownership.claim(
            repo.path,
            task=f"WL-{index}",
            actor=f"agent-{index}",
            role="implementer",
            files=[f"src/{index}.py"],
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(add, range(24)))

    assert len(ownership.load(repo.path)["claims"]) == 24
