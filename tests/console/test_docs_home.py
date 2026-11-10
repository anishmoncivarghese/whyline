"""The Project home screen in Docs, and the console's follow-up (HOME-6)."""

import json
import threading
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.widgets import Button, Checkbox, Input, OptionList, Static

from whyline.console import tui
from whyline.console.docs_screen import DocsScreen, HomeChoice, HomeResult, ProjectHomeScreen
from whyline.sdlc import docset
from whyline.sdlc import home as real_home
from whyline.sdlc import library as sdlc_library

pytestmark = [
    pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed"),
    pytest.mark.asyncio,
]


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self.results = []

    def on_mount(self):
        self.push_screen(self._screen, self.results.append)


def _labels(widget):
    return [str(widget.get_option_at_index(i).prompt) for i in range(widget.option_count)]


@pytest.fixture
def library(tmp_path):
    return docset.create(tmp_path, "Job search", "feature", "human", roles={"implementer": "claude"})


class HomeStub:
    folder_name = staticmethod(real_home.folder_name)

    def __init__(self, parent, fresh=False, refusal=None, gate=None):
        self.parent, self.fresh, self.refusal, self.gate = parent, fresh, refusal, gate
        self.ideas = [
            real_home.NameIdea("Quill", "quill", "short"),
            real_home.NameIdea("Fern Desk", "fern-desk", "calm"),
        ]

    def is_fresh(self, root):
        return self.fresh

    def last_parent(self):
        return self.parent

    def suggest_names(self, root, found, *, agent):
        if self.gate is not None:
            self.gate.wait(5)
        return self.ideas

    def check_target(self, root, parent, folder):
        return self.refusal


class GhStub:
    def __init__(self, fix=None, owner="anish"):
        self.fix, self.owner = fix, owner

    def gh_ready(self, root):
        return self.fix

    def default_owner(self, root):
        return self.owner


class RunnerStub:
    def __init__(self, target):
        self.target, self.calls = target, []

    def choose_home(self, root, slug, **kwargs):
        self.calls.append((root, slug, kwargs))
        kwargs["progress"]("run git init")
        return self.target

    def run(self, root, slug, progress=None):
        self.calls.append(("run", root, slug))
        return SimpleNamespace(state="done", message="")


def _home_screen(tmp_path, **kwargs):
    kwargs.setdefault("home", HomeStub(tmp_path))
    kwargs.setdefault("github", GhStub())
    return ProjectHomeScreen(tmp_path, "job-search", docs=tmp_path, **kwargs)


async def _settle(pilot):
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.parametrize("fresh,expected", [(True, "here"), (False, "new")])
async def test_default_choice_follows_whether_the_repo_is_fresh(tmp_path, library, fresh, expected):
    screen = _home_screen(tmp_path, home=HomeStub(tmp_path, fresh=fresh))
    async with Host(screen).run_test() as pilot:
        await _settle(pilot)
        assert screen.choice == expected


async def test_suggestions_fill_the_choices_and_the_folder_follows(tmp_path, library):
    gate = threading.Event()
    screen = _home_screen(tmp_path, home=HomeStub(tmp_path, gate=gate))
    async with Host(screen).run_test() as pilot:
        await pilot.pause()
        names = screen.query_one("#home-names", OptionList)
        assert _labels(names)[0] == "Suggesting names…"
        gate.set()
        await _settle(pilot)
        assert _labels(names) == ["Quill — short", "Fern Desk — calm", "My own name"]
        assert (screen.project, screen.folder) == ("Quill", "quill")
        screen.choose_name(1)
        assert screen.query_one("#home-folder", Input).value == "fern-desk"
        screen.choose_name(None)
        screen.query_one("#home-own", Input).value = "My App"
        await pilot.pause()
        assert (screen.project, screen.folder) == ("My App", "my-app")
        screen.query_one("#home-folder", Input).value = "my-app-2"
        await pilot.pause()
        assert screen.folder == "my-app-2"
        assert screen.path_shown == str(tmp_path / "my-app-2")


async def test_refusal_disables_continue_and_shows_why(tmp_path, library):
    text = "/x/quill already exists and isn't empty."
    screen = _home_screen(tmp_path, home=HomeStub(tmp_path, refusal=text))
    async with Host(screen).run_test() as pilot:
        await _settle(pilot)
        assert screen.path_shown == text
        assert screen.query_one("#home-continue", Button).disabled
        screen.submit()
        await pilot.pause()
        assert pilot.app.results == []


async def test_choose_folder_uses_the_injected_picker(tmp_path, library):
    other = tmp_path / "elsewhere"
    screen = _home_screen(tmp_path, pick_folder_fn=lambda: other)
    async with Host(screen).run_test() as pilot:
        await _settle(pilot)
        screen._choose_folder()
        await _settle(pilot)
        assert screen.save_in == other
        assert screen.path_shown == str(other / "quill")


async def test_continue_returns_the_choice(tmp_path, library):
    screen = _home_screen(tmp_path)
    async with Host(screen).run_test() as pilot:
        await _settle(pilot)
        screen.set_github(True)
        screen.private = False
        screen.submit()
        await pilot.pause()
        (got,) = pilot.app.results
        assert got == HomeChoice("new", tmp_path, "quill", "Quill", True, False, "anish", "quill")


async def test_github_box_is_off_by_default_with_the_default_owner(tmp_path, library):
    screen = _home_screen(tmp_path)
    async with Host(screen).run_test() as pilot:
        await _settle(pilot)
        assert not screen.query_one("#home-github", Checkbox).value
        assert screen.query_one("#home-owner", Input).value == "anish"
        assert screen.private


async def test_github_box_is_disabled_with_the_fix_when_gh_is_not_ready(tmp_path, library):
    screen = _home_screen(tmp_path, github=GhStub(fix="Run: gh auth login"))
    async with Host(screen).run_test() as pilot:
        await _settle(pilot)
        box = screen.query_one("#home-github", Checkbox)
        assert box.disabled and not box.value
        assert "gh auth login" in str(screen.query_one("#home-github-fix", Static).render())
        screen.set_github(True)
        assert not screen.github_on


async def test_docs_waiting_for_home_chooses_and_closes_with_the_new_root(tmp_path, library):
    target = tmp_path / "new-project"
    runner = RunnerStub(target)
    options = {"home": HomeStub(tmp_path), "github": GhStub()}
    screen = DocsScreen(tmp_path, docs=tmp_path, check=lambda root: None, set_slug="job-search",
                        open_home=True, runner=runner, home_options=options)
    async with Host(screen).run_test() as pilot:
        await _settle(pilot)
        home_screen = pilot.app.screen
        assert isinstance(home_screen, ProjectHomeScreen)
        home_screen.set_github(True)
        home_screen.submit()
        await _settle(pilot)
        await _settle(pilot)
        (got,) = pilot.app.results
        assert got.root == target and got.changed and got.slug == "job-search"
        assert got.github.owner == "anish" and got.github.repo == "quill"
        _, slug, kwargs = runner.calls[0]
        assert (slug, kwargs["choice"], kwargs["folder"], kwargs["name"]) == (
            "job-search", "new", "quill", "Quill")
        assert kwargs["agents"] == ["claude"]


async def test_docs_use_here_without_github_carries_on_in_the_same_root(tmp_path, library):
    runner = RunnerStub(tmp_path)
    options = {"home": HomeStub(tmp_path, fresh=True), "github": GhStub()}
    screen = DocsScreen(tmp_path, docs=tmp_path, check=lambda root: None, set_slug="job-search",
                        open_home=True, runner=runner, home_options=options)
    async with Host(screen).run_test() as pilot:
        await _settle(pilot)
        pilot.app.screen.submit()
        await _settle(pilot)
        await _settle(pilot)
        assert pilot.app.results == []
        assert runner.calls[-1] == ("run", tmp_path, "job-search")


async def test_moved_set_row_and_switch_button(tmp_path, library):
    manifest = tmp_path / docset.SDLC_DIR / "job-search" / docset.MANIFEST
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data.update(state="moved", moved_to=str(tmp_path / "elsewhere"))
    manifest.write_text(json.dumps(data), encoding="utf-8")
    screen = DocsScreen(tmp_path, docs=tmp_path, check=lambda root: None, set_slug="job-search")
    async with Host(screen).run_test() as pilot:
        left = _labels(screen.query_one("#docs-left", OptionList))
        assert f"Job search · Moved to {tmp_path / 'elsewhere'}" in left
        assert screen.query_one("#docs-switch", Button).display
        screen._set_action("docs-switch")
        await pilot.pause()
        (got,) = pilot.app.results
        assert got == HomeResult("job-search", tmp_path / "elsewhere", True)
        assert sdlc_library.sets(tmp_path)[0].moved_to == str(tmp_path / "elsewhere")


@pytest.mark.parametrize("answer", ["confirm", "cancel"])
async def test_console_switches_then_asks_before_creating_the_github_repo(
        tmp_path, monkeypatch, answer):
    from whyline.sdlc import github_repo

    created, switched, opened = [], [], []

    def create(root, **kw):
        created.append(kw)
        return "https://github.com/anish/quill"

    monkeypatch.setattr(github_repo, "create_repo", create)
    app = tui.WhylineConsoleApp(root=tmp_path)
    monkeypatch.setattr(app, "_switch_repo", lambda target, ok: switched.append((target, ok)))
    monkeypatch.setattr(app, "_open_docs", lambda slug, kind, **kw: opened.append((slug, kw)))
    choice = HomeChoice("new", tmp_path, "quill", "Quill", True, True, "anish", "quill")
    async with app.run_test() as pilot:
        app._docs_closed(HomeResult("job-search", tmp_path / "quill", True, choice))
        await pilot.pause()
        assert switched == [(tmp_path / "quill", True)]
        assert "github.com/anish/quill (private)" in str(app.screen.query_one("Label").render())
        await pilot.click(f"#{answer}")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert opened == [("job-search", {"resume": True})]
        if answer == "confirm":
            assert created[0]["owner"] == "anish" and created[0]["name"] == "quill"
        else:
            assert created == []


async def test_console_github_refusal_is_shown_and_the_set_carries_on(tmp_path, monkeypatch):
    from whyline.sdlc import github_repo

    def refuse(root, **kw):
        raise github_repo.GithubRepoError("This project already has a remote: x")

    monkeypatch.setattr(github_repo, "create_repo", refuse)
    app = tui.WhylineConsoleApp(root=tmp_path)
    opened = []
    monkeypatch.setattr(app, "_open_docs", lambda slug, kind, **kw: opened.append(slug))
    choice = HomeChoice("here", None, "", "Quill", True, True, "anish", "repo")
    async with app.run_test() as pilot:
        app._docs_closed(HomeResult("job-search", tmp_path, False, choice))
        await pilot.pause()
        await pilot.click("#confirm")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert opened == ["job-search"]


async def test_console_without_github_switches_and_resumes_docs(tmp_path, monkeypatch):
    app = tui.WhylineConsoleApp(root=tmp_path)
    switched, opened = [], []
    monkeypatch.setattr(app, "_switch_repo", lambda target, ok: switched.append((target, ok)))
    monkeypatch.setattr(app, "_open_docs", lambda slug, kind, **kw: opened.append((slug, kw)))
    async with app.run_test():
        app._docs_closed(HomeResult("job-search", tmp_path / "quill", True))
        assert switched == [(tmp_path / "quill", True)]
        assert opened == [("job-search", {"resume": True})]


class RepoStub:
    def __init__(self, error=None):
        self.error, self.created = error, []

    def default_owner(self, root):
        return "anish"

    def describe(self, owner, name, private):
        return f"Create github.com/{owner}/{name}?"

    def create_repo(self, root, **kwargs):
        if self.error:
            raise RuntimeError(self.error)
        self.created.append(kwargs)
        return f"https://github.com/{kwargs['owner']}/{kwargs['name']}"


def _docs_with_repo(tmp_path, repo):
    return DocsScreen(tmp_path, docs=tmp_path, check=lambda root: None, set_slug="job-search",
                      repo_creator=repo)


async def test_reopened_docs_offers_create_github_and_yes_creates(tmp_path, library):
    repo = RepoStub()
    screen = _docs_with_repo(tmp_path, repo)
    async with Host(screen).run_test() as pilot:
        assert screen.query_one("#docs-github", Button).display
        screen._set_action("docs-github")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await _settle(pilot)
        assert repo.created[0]["owner"] == "anish" and repo.created[0]["slug"] == "job-search"
        assert repo.created[0]["name"] == tmp_path.name


async def test_create_github_no_creates_nothing_and_stays_offered(tmp_path, library):
    repo = RepoStub()
    screen = _docs_with_repo(tmp_path, repo)
    async with Host(screen).run_test() as pilot:
        screen._set_action("docs-github")
        await pilot.pause()
        await pilot.click("#confirm-no")
        await _settle(pilot)
        assert repo.created == []
        assert screen.query_one("#docs-github", Button).display


async def test_create_github_refusal_is_shown_and_stays_offered(tmp_path, library):
    repo = RepoStub(error="This project already has a remote: x")
    screen = _docs_with_repo(tmp_path, repo)
    async with Host(screen).run_test() as pilot:
        screen._set_action("docs-github")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await _settle(pilot)
        assert "already has a remote" in str(screen.query_one("#docs-status", Static).render())
        assert screen.query_one("#docs-github", Button).display


async def test_create_github_is_hidden_once_recorded(tmp_path, library):
    manifest = tmp_path / docset.SDLC_DIR / "job-search" / docset.MANIFEST
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["github"] = {"url": "https://github.com/anish/x", "private": True}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    screen = _docs_with_repo(tmp_path, RepoStub())
    async with Host(screen).run_test():
        assert not screen.query_one("#docs-github", Button).display
