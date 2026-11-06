import pytest

from whyline.release import cli as release_cli
from whyline.release import setup_github as sg
from whyline.release.ready import Result


class Runner:
    """Answers commands from a table keyed by the leading argv words."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        for prefix, result in self.answers.items():
            if tuple(args[:len(prefix)]) == prefix:
                if isinstance(result, Exception):
                    raise result
                return result
        return Result(1, "", "unexpected")


def test_status_without_gh(tmp_path):
    run = Runner({("git",): Result(1, "", ""), ("gh", "--version"): FileNotFoundError()})
    got = sg.status(tmp_path, run=run)
    assert got == sg.GitHubStatus(False, False, "", "", False)


def test_status_gh_not_signed_in(tmp_path):
    run = Runner({("git",): Result(0, "git@github.com:a/b.git\n", ""),
                  ("gh", "--version"): Result(0, "gh 2", ""),
                  ("gh", "auth"): Result(1, "", "not logged in")})
    got = sg.status(tmp_path, run=run)
    assert got == sg.GitHubStatus(True, False, "", "git@github.com:a/b.git", True)


def test_status_signed_in_without_origin(tmp_path):
    run = Runner({("git",): Result(128, "", "no remote"),
                  ("gh", "--version"): Result(0, "gh 2", ""),
                  ("gh", "auth"): Result(0, "", ""),
                  ("gh", "api"): Result(0, "anish\n", "")})
    got = sg.status(tmp_path, run=run)
    assert got == sg.GitHubStatus(True, True, "anish", "", False)


def test_status_non_github_origin(tmp_path):
    run = Runner({("git",): Result(0, "https://gitlab.com/a/b.git\n", ""),
                  ("gh", "--version"): Result(0, "", ""),
                  ("gh", "auth"): Result(0, "", ""),
                  ("gh", "api"): Result(0, "me", "")})
    got = sg.status(tmp_path, run=run)
    assert got.origin_url == "https://gitlab.com/a/b.git" and not got.origin_is_github


def test_status_https_github_origin(tmp_path):
    run = Runner({("git",): Result(0, "https://github.com/a/b.git", ""),
                  ("gh", "--version"): FileNotFoundError()})
    assert sg.status(tmp_path, run=run).origin_is_github


def test_sign_in_streams_lines_and_passes_newline():
    seen = {}

    def streaming(args, stdin, on_line):
        seen.update(args=args, stdin=stdin)
        on_line("! First copy your one-time code: ABCD-1234")
        on_line("done")
        return 0

    lines = []
    assert sg.sign_in(run_streaming=streaming, on_line=lines.append) == 0
    assert seen["stdin"] == "\n"
    assert seen["args"] == ["gh", "auth", "login", "--web", "--git-protocol", "https",
                            "--hostname", "github.com"]
    assert lines == ["! First copy your one-time code: ABCD-1234", "done"]


def test_sign_in_returns_exit_code():
    assert sg.sign_in(run_streaming=lambda a, s, o: 4, on_line=print) == 4


def create_runner(origin_after="https://github.com/me/x"):
    state = {"created": False}

    def run(args, **kwargs):
        run.calls.append(list(args))
        if args[:2] == ["git", "remote"]:
            return Result(0, origin_after, "") if state["created"] else Result(2, "", "none")
        if args[:3] == ["gh", "repo", "create"]:
            state["created"] = True
            return Result(0, "https://github.com/me/x\n", "")
        return Result(1, "", "")

    run.calls = []
    return run


def test_create_private_argv(tmp_path):
    run = create_runner()
    assert sg.create_repo(tmp_path, "x", run=run) == "https://github.com/me/x"
    assert ["gh", "repo", "create", "x", "--private", "--source", ".", "--remote",
            "origin"] in run.calls


def test_create_public_with_description(tmp_path):
    run = create_runner()
    sg.create_repo(tmp_path, "x", private=False, description="hi", run=run)
    assert ["gh", "repo", "create", "x", "--public", "--source", ".", "--remote", "origin",
            "--description", "hi"] in run.calls


def test_create_never_pushes_and_uses_no_token(tmp_path):
    run = create_runner()
    sg.create_repo(tmp_path, "x", run=run)
    for call in run.calls:
        assert "push" not in call and "--push" not in call
        text = " ".join(call).lower()
        assert "token" not in text and "ghp_" not in text


def test_create_refuses_existing_origin(tmp_path):
    def run(args, **kwargs):
        run.calls.append(args)
        return Result(0, "https://github.com/a/b", "")

    run.calls = []
    with pytest.raises(sg.SetupError, match="already has an origin"):
        sg.create_repo(tmp_path, "x", run=run)
    assert not any(c[:3] == ["gh", "repo", "create"] for c in run.calls)


@pytest.mark.parametrize("name", ["", "a b", "a/b", "x" * 101, "né"])
def test_create_refuses_bad_name(tmp_path, name):
    run = create_runner()
    with pytest.raises(sg.SetupError):
        sg.create_repo(tmp_path, name, run=run)
    assert run.calls == []


def test_create_reports_gh_failure(tmp_path):
    def run(args, **kwargs):
        if args[:2] == ["git", "remote"]:
            return Result(2, "", "")
        return Result(1, "", "name already exists")

    with pytest.raises(sg.SetupError, match="name already exists"):
        sg.create_repo(tmp_path, "x", run=run)


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(release_cli, "_root", lambda: tmp_path)
    return tmp_path


def fake_status(monkeypatch, **fields):
    base = dict(gh_installed=True, signed_in=True, user="me", origin_url="", origin_is_github=False)
    monkeypatch.setattr(sg, "status", lambda r, **k: sg.GitHubStatus(**{**base, **fields}))


def test_cli_setup_prints_status(root, monkeypatch, capsys):
    fake_status(monkeypatch)
    assert release_cli.main(["setup", "github"]) == 0
    out = capsys.readouterr().out
    assert "Signed in as me" in out and "Origin: none" in out


def test_cli_setup_signs_in_on_a_terminal(root, monkeypatch, capsys):
    fake_status(monkeypatch, signed_in=False)
    monkeypatch.setattr(release_cli, "_interactive", lambda: True)
    monkeypatch.setattr(sg, "sign_in", lambda *, on_line, **k: (on_line("code ABCD"), 0)[1])
    assert release_cli.main(["setup", "github"]) == 0
    assert "code ABCD" in capsys.readouterr().out


def test_cli_setup_skips_sign_in_without_a_terminal(root, monkeypatch, capsys):
    fake_status(monkeypatch, signed_in=False)
    monkeypatch.setattr(release_cli, "_interactive", lambda: False)
    monkeypatch.setattr(sg, "sign_in", lambda **k: pytest.fail("must not sign in"))
    assert release_cli.main(["setup", "github"]) == 1
    assert "needs a terminal" in capsys.readouterr().err


def test_cli_setup_create(root, monkeypatch, capsys):
    fake_status(monkeypatch)
    got = {}

    def create(r, name, *, private=True, **k):
        got.update(name=name, private=private)
        return "https://github.com/me/x"

    monkeypatch.setattr(sg, "create_repo", create)
    assert release_cli.main(["setup", "github", "--create", "x", "--public"]) == 0
    assert got == {"name": "x", "private": False}
    assert "Created https://github.com/me/x" in capsys.readouterr().out


def test_cli_setup_create_error(root, monkeypatch, capsys):
    fake_status(monkeypatch)

    def create(*a, **k):
        raise sg.SetupError("already has an origin")

    monkeypatch.setattr(sg, "create_repo", create)
    assert release_cli.main(["setup", "github", "--create", "x"]) == 1
    assert "already has an origin" in capsys.readouterr().err


def test_cli_setup_without_gh(root, monkeypatch, capsys):
    fake_status(monkeypatch, gh_installed=False, signed_in=False)
    assert release_cli.main(["setup", "github"]) == 1
    assert "not installed" in capsys.readouterr().out


def _prot_run(security, alerts):
    return Runner({("gh", "api", "repos/o/r", "--jq"): security,
                   ("gh", "api", "repos/o/r/vulnerability-alerts"): alerts})


def test_owner_repo_from_origin():
    assert sg.owner_repo("git@github.com:a/b.git") == "a/b"
    assert sg.owner_repo("https://github.com/a/b") == "a/b"
    assert sg.owner_repo("https://gitlab.com/a/b.git") == ""


def test_protection_status_all_on():
    body = ('{"secret_scanning":{"status":"enabled"},'
            '"secret_scanning_push_protection":{"status":"enabled"}}')
    got = sg.protection_status("o/r", run=_prot_run(Result(0, body, ""), Result(0, "", "")))
    assert got == {"secret_scanning": "on", "secret_scanning_push_protection": "on",
                   "dependabot_alerts": "on"}


def test_protection_status_off_and_404():
    body = ('{"secret_scanning":{"status":"disabled"},'
            '"secret_scanning_push_protection":{"status":"disabled"}}')
    got = sg.protection_status(
        "o/r", run=_prot_run(Result(0, body, ""), Result(1, "", "gh: Not Found (HTTP 404)")))
    assert set(got.values()) == {"off"}


def test_protection_status_unavailable():
    got = sg.protection_status(
        "o/r", run=_prot_run(Result(0, "null", ""), Result(1, "", "HTTP 403")))
    assert set(got.values()) == {"unavailable"}


def test_enable_protection_argv():
    run = Runner({("gh",): Result(0, "", "")})
    assert sg.enable_protection("o/r", "secret_scanning", run=run) == ""
    assert sg.enable_protection("o/r", "secret_scanning_push_protection", run=run) == ""
    assert sg.enable_protection("o/r", "dependabot_alerts", run=run) == ""
    assert run.calls == [
        ["gh", "api", "-X", "PATCH", "repos/o/r",
         "-f", "security_and_analysis[secret_scanning][status]=enabled"],
        ["gh", "api", "-X", "PATCH", "repos/o/r",
         "-f", "security_and_analysis[secret_scanning_push_protection][status]=enabled"],
        ["gh", "api", "-X", "PUT", "repos/o/r/vulnerability-alerts"],
    ]


@pytest.mark.parametrize("code", ["403", "422"])
def test_enable_protection_unavailable_message(code):
    run = Runner({("gh",): Result(1, "", f"Not allowed (HTTP {code})")})
    got = sg.enable_protection("o/r", "secret_scanning", run=run)
    assert got == f"not available for this repository: Not allowed (HTTP {code})"


def test_enable_protection_gh_missing_does_not_crash():
    run = Runner({("gh",): FileNotFoundError()})
    assert "could not turn on" in sg.enable_protection("o/r", "dependabot_alerts", run=run)
