from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from whyline import cli
from whyline.console import relay_ops
from whyline.sdlc import cli as docs_cli, github_repo, home, docset, export, goldfish, lenses, library, product, review, runner, workspace
from whyline.sdlc.docset import DocSetError
from whyline.sdlc.stages import Stage

ROLES = {"writer": "claude"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(docs_cli, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspace, "docs_root", lambda root: tmp_path)
    monkeypatch.setattr(relay_ops, "current_roles", lambda root: dict(ROLES))
    return tmp_path


def docs(*argv: str) -> int:
    return cli.main(["docs", *argv])


def make(root, name="Login", **kw):
    made = docset.create(root, name, "feature", "human", roles=ROLES, prd_mode="none", **kw)
    docset.add_version(root, made, "spec", "# Spec\n\n## Goal\n\nOne.\n", author="claude", note="x")
    return docset.load(root, made.slug)


def test_list_empty_then_one_line_per_set(env, capsys):
    assert docs("list") == 0
    assert "No document sets yet." in capsys.readouterr().out
    made = make(env)
    assert docs("list") == 0
    assert capsys.readouterr().out.startswith(f"{made.slug}: Login")


def test_show_summary_and_document(env, capsys):
    made = make(env)
    assert docs("show", made.slug) == 0
    out = capsys.readouterr().out
    assert "Mode: Human in the loop" in out and "spec: In review, v1" in out
    assert docs("show", made.slug, "spec") == 0
    assert "## Goal" in capsys.readouterr().out


def test_show_missing_set_and_document_exit_non_zero(env, capsys):
    assert docs("show", "nope") == 1
    assert "No document set named" in capsys.readouterr().err
    made = make(env)
    assert docs("show", made.slug, "design") == 1
    assert "no 'design' document" in capsys.readouterr().err


def test_start_from_description_runs_the_set(env, monkeypatch, capsys):
    seen = {}

    def run(root, slug, *, progress):
        seen["slug"] = slug
        progress("drafting")
        return runner.RunOutcome("waiting", "spec")

    monkeypatch.setattr(runner, "run", run)
    assert docs("start", "--from-description", "Let people log in", "--size", "small",
                "--auto", "--name", "Login") == 0
    out = capsys.readouterr().out
    assert "Started login" in out and "drafting" in out and "State: waiting at spec" in out
    found = docset.load(env, "login")
    assert (found.description, found.mode, found.size) == ("Let people log in", "auto", "small")
    assert seen["slug"] == "login"


def test_start_from_file_as_spec_imports_it(env, monkeypatch, capsys):
    monkeypatch.setattr(runner, "run", lambda root, slug, *, progress: runner.RunOutcome("waiting", "spec"))
    source = env / "idea.md"
    source.write_text("# Spec\n\n## Goal\n\nOne.\n", encoding="utf-8")
    assert docs("start", "--from-file", str(source), "--as", "spec", "--size", "small") == 0
    assert "Imported spec v1" in capsys.readouterr().out
    assert docset.load(env, "idea").document("spec")["status"] == "in_review"


def test_start_from_file_without_as_uses_text_as_description(env, monkeypatch):
    monkeypatch.setattr(runner, "run", lambda root, slug, *, progress: runner.RunOutcome("waiting", "spec"))
    source = env / "idea.md"
    source.write_text("# Add search\n\nFind things.\n", encoding="utf-8")
    assert docs("start", "--from-file", str(source)) == 0
    found = docset.load(env, "add-search")
    assert "Find things." in found.description


def test_start_refuses_bad_combinations(env, capsys):
    assert docs("start", "--from-description", "x", "--as", "spec") == 1
    assert "--as needs --from-file" in capsys.readouterr().err
    source = env / "p.md"
    source.write_text("# P\n\ntext\n", encoding="utf-8")
    assert docs("start", "--from-file", str(source), "--as", "prd", "--size", "small") == 1
    assert "small set has no prd" in capsys.readouterr().err


def test_start_reports_a_run_error_non_zero(env, monkeypatch, capsys):
    monkeypatch.setattr(
        runner, "run",
        lambda root, slug, *, progress: runner.RunOutcome("error", "spec", message="A relay is running."),
    )
    assert docs("start", "--from-description", "x") == 1
    assert "A relay is running." in capsys.readouterr().err


def test_resume_prints_questions(env, monkeypatch, capsys):
    made = make(env)
    monkeypatch.setattr(
        runner, "run",
        lambda root, slug, *, progress: runner.RunOutcome("questions", "spec", questions=("Who logs in?",)),
    )
    assert docs("resume", made.slug) == 0
    out = capsys.readouterr().out
    assert "State: questions at spec" in out and "Question: Who logs in?" in out
    assert docs("resume", "nope") == 1


def test_prd_without_and_with_history(env, capsys):
    assert docs("prd") == 0
    assert "No product PRD yet." in capsys.readouterr().out

    def summary(root):
        return library.ProductSummary("1.2", "anish on 2026-11-01", ["- v1.1 a", "- v1.2 b"])

    library_product = library.product
    library.product = summary
    try:
        assert docs("prd") == 0
        out = capsys.readouterr().out
        assert "Product PRD v1.2" in out and "Approved by anish on 2026-11-01" in out
        assert "v1.1" not in out
        assert docs("prd", "--history") == 0
        assert "- v1.1 a" in capsys.readouterr().out
    finally:
        library.product = library_product


def test_approve_calls_review_and_prints_next(env, monkeypatch, capsys):
    calls = []

    def approve(root, slug, kind, *, approver):
        calls.append((slug, kind, approver))
        return Stage("plan", "Plan + test plan")

    monkeypatch.setattr(review, "approve", approve)
    assert docs("approve", "login", "spec") == 0
    assert calls[0][:2] == ("login", "spec")
    assert "Approved spec for login" in capsys.readouterr().out


def test_approve_refusal_exits_non_zero_with_the_message(env, monkeypatch, capsys):
    def refuse(root, slug, kind, *, approver):
        raise DocSetError("A relay is running in the documents checkout.")

    monkeypatch.setattr(review, "approve", refuse)
    assert docs("approve", "login", "spec") == 1
    assert "A relay is running in the documents checkout." in capsys.readouterr().err


def test_change_passes_comments_and_section(env, monkeypatch, capsys):
    seen = {}

    def ask(root, slug, kind, comments, *, section="", progress):
        seen.update(slug=slug, kind=kind, comments=comments, section=section)
        return ["Scope"]

    monkeypatch.setattr(review, "ask_for_changes", ask)
    assert docs("change", "login", "spec", "Be shorter", "--section", "Goal") == 0
    assert seen == {"slug": "login", "kind": "spec", "comments": "Be shorter", "section": "Goal"}
    assert "Also changed: Scope" in capsys.readouterr().out


def test_redo_and_its_refusal(env, monkeypatch, capsys):
    monkeypatch.setattr(review, "redo", lambda root, slug, kind, *, progress: [])
    assert docs("redo", "login", "spec") == 0
    assert "Redid spec for login" in capsys.readouterr().out

    def refuse(root, slug, kind, *, progress):
        raise DocSetError("There is nothing before this document to match.")

    monkeypatch.setattr(review, "redo", refuse)
    assert docs("redo", "login", "spec") == 1
    assert "nothing before this document" in capsys.readouterr().err


def test_answer_passes_answers(env, monkeypatch, capsys):
    seen = {}

    def answer(root, slug, kind, answers, *, progress):
        seen.update(slug=slug, kind=kind, answers=answers)
        return []

    monkeypatch.setattr(review, "answer_questions", answer)
    assert docs("answer", "login", "spec", "Staff only") == 0
    assert seen == {"slug": "login", "kind": "spec", "answers": "Staff only"}
    assert "Answered the questions on spec" in capsys.readouterr().out


def test_mode_saves_and_rejects_unknown(env, capsys):
    made = make(env)
    assert docs("mode", made.slug, "auto") == 0
    assert "Automatic" in capsys.readouterr().out
    assert docset.load(env, made.slug).mode == "auto"
    with pytest.raises(SystemExit) as exit_info:
        docs("mode", made.slug, "fast")
    assert exit_info.value.code == 2


def test_export_prints_files_and_notes(env, monkeypatch, capsys):
    seen = {}

    def pack(root, slug, out=None):
        seen.update(root=root, slug=slug, out=out)
        return export.ExportResult([Path("/o/login-docs.docx")], ["Review log is missing; skipped."])

    monkeypatch.setattr(export, "export_pack", pack)
    assert docs("export", "login", "--out", str(env / "out")) == 0
    out = capsys.readouterr().out
    assert "Wrote /o/login-docs.docx" in out and "Review log is missing" in out
    assert seen["slug"] == "login" and seen["out"] == env / "out"


def test_export_with_no_files_exits_non_zero(env, monkeypatch, capsys):
    monkeypatch.setattr(export, "export_pack", lambda root, slug, out=None: export.ExportResult([], ["Word could not be written."]))
    assert docs("export", "login") == 1


def write_report(root, made, kind="spec", version=1):
    folder = docset._folder(root, made.slug) / goldfish.REVIEWS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{kind}-v{version}.md"
    path.write_text(
        "Blockers: 1 · Major: 0 · Nits: 0 · Not run: security · Reviewer: codex\n\n"
        "## Blockers\n\n- Goal — Too vague — Name the user (lenses: clarity)\n",
        encoding="utf-8",
    )
    return path


def test_review_prints_first_line_and_path(env, monkeypatch, capsys):
    made = make(env)
    path = write_report(env, made)
    monkeypatch.setattr(
        review, "review_again", lambda root, slug, kind, *, progress=None: goldfish.Review(path=path)
    )
    assert docs("review", made.slug, "spec") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Blockers: 1") and out[1] == str(path)


def test_review_guard_refusal_exits_non_zero(env, monkeypatch, capsys):
    def refuse(root, slug, kind, *, progress=None):
        raise DocSetError("A relay is running.")

    monkeypatch.setattr(review, "review_again", refuse)
    assert docs("review", "login", "spec") == 1
    assert "A relay is running." in capsys.readouterr().err


def test_findings_lists_each_finding_and_not_run(env, capsys):
    made = make(env)
    write_report(env, made)
    assert docs("findings", made.slug, "spec") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "blocker: Goal — Too vague — Name the user (lenses: clarity)"
    assert out[-1] == "Not run: security"


def test_findings_without_a_review(env, capsys):
    made = make(env)
    assert docs("findings", made.slug, "spec") == 0
    assert "No fresh-eyes review" in capsys.readouterr().out


def test_outside_a_repository_exits_non_zero(monkeypatch, capsys):
    monkeypatch.setattr(docs_cli, "_root", lambda: None)
    assert docs("list") == 1
    assert "not a git repository" in capsys.readouterr().err


IDEAS = [home.NameIdea("Gatekeeper", "gatekeeper", "guards the door"),
         home.NameIdea("Latch", "latch", "short")]


def test_names_prints_each_suggestion(env, monkeypatch, capsys):
    made = make(env)
    monkeypatch.setattr(home, "suggest_names", lambda root, found, *, agent: IDEAS)
    assert docs("names", made.slug) == 0
    out = capsys.readouterr().out
    assert "Gatekeeper (gatekeeper) — guards the door" in out
    assert "Latch (latch) — short" in out


def test_home_new_uses_defaults_and_prints_cd(env, monkeypatch, capsys):
    made = make(env)
    seen = {}

    def choose(root, slug, **kw):
        seen.update(kw)
        return Path("/elsewhere/gatekeeper")

    monkeypatch.setattr(home, "suggest_names", lambda root, found, *, agent: IDEAS)
    monkeypatch.setattr(home, "last_parent", lambda: Path("/parents"))
    monkeypatch.setattr(runner, "choose_home", choose)
    assert docs("home", made.slug, "--new") == 0
    assert (seen["choice"], seen["name"], seen["folder"], seen["parent"]) == (
        "new", "Gatekeeper", "gatekeeper", Path("/parents"))
    out = capsys.readouterr().out
    assert "/elsewhere/gatekeeper" in out
    assert f"cd /elsewhere/gatekeeper && whyline docs resume {made.slug}" in out


def test_home_here_keeps_root_and_explicit_options(env, monkeypatch, capsys):
    made = make(env)
    seen = {}

    def choose(root, slug, **kw):
        seen.update(kw)
        return env

    monkeypatch.setattr(runner, "choose_home", choose)
    assert docs("home", made.slug, "--here") == 0
    assert seen["choice"] == "here"
    out = capsys.readouterr().out
    assert "cd " not in out and f"Next: whyline docs resume {made.slug}" in out
    assert docs("home", made.slug, "--new", "--name", "Zed", "--folder", "z", "--parent", "/p") == 0
    assert (seen["name"], seen["folder"], seen["parent"]) == ("Zed", "z", Path("/p"))


def test_home_refusal_exits_non_zero(env, monkeypatch, capsys):
    made = make(env)

    def refuse(root, slug, **kw):
        raise home.HomeError("Folder exists.")

    monkeypatch.setattr(runner, "choose_home", refuse)
    assert docs("home", made.slug, "--here") != 0
    assert "Folder exists." in capsys.readouterr().err


def test_github_yes_creates_and_prints_url(env, monkeypatch, capsys):
    made = make(env)
    seen = {}

    def create(root, **kw):
        seen.update(kw)
        return "https://github.com/me/login"

    monkeypatch.setattr(github_repo, "default_owner", lambda root: "me")
    monkeypatch.setattr(github_repo, "create_repo", create)
    assert docs("github", made.slug, "--yes") == 0
    assert (seen["owner"], seen["name"], seen["private"]) == ("me", "login", True)
    out = capsys.readouterr().out
    assert "Create github.com/me/login (private)" in out
    assert "https://github.com/me/login" in out
    assert docs("github", made.slug, "--yes", "--public", "--owner", "org", "--name", "x") == 0
    assert (seen["owner"], seen["name"], seen["private"]) == ("org", "x", False)


def test_github_no_answer_does_nothing(env, monkeypatch, capsys):
    made = make(env)
    calls = []
    monkeypatch.setattr(github_repo, "default_owner", lambda root: "me")
    monkeypatch.setattr(github_repo, "create_repo", lambda root, **kw: calls.append(kw))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert docs("github", made.slug) != 0
    assert calls == []
    out = capsys.readouterr().out
    assert "Create github.com/me/login (private)" in out
    assert "Nothing created." in out


def test_github_refusal_exits_non_zero(env, monkeypatch, capsys):
    made = make(env)

    def refuse(root, **kw):
        raise github_repo.GithubRepoError("Already has a remote.")

    monkeypatch.setattr(github_repo, "default_owner", lambda root: "me")
    monkeypatch.setattr(github_repo, "create_repo", refuse)
    assert docs("github", made.slug, "--yes") != 0
    assert "Already has a remote." in capsys.readouterr().err
