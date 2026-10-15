import pytest
from whyline.console import tui
from whyline.console.repl import _help_text

pytestmark = pytest.mark.skipif(not tui.TUI_AVAILABLE, reason="textual not installed")


def test_help_names_files():
    help_out = _help_text()
    assert "Files" in help_out
    assert "follow the file" in help_out


@pytest.mark.asyncio
async def test_files_button_exists_in_all_modes_with_label_files(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        for mode in ("chat", "relay", "agents"):
            await pilot.click(f"#mode-{mode}")
            await pilot.pause()
            btn = app.query_one("#see-files", tui.Button)
            assert str(btn.label) == "Files"
            assert btn.display is True


@pytest.mark.asyncio
async def test_pane_starts_hidden_and_shows_placeholder_when_clicked(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#file-pane")
        assert pane.display is False
        assert app.query_one("#transcript") is not None

        await pilot.click("#see-files")
        await pilot.pause()
        assert pane.display is True
        path_label = app.query_one("#file-path", tui.Static)
        assert "No file yet. A file opens here when an agent writes one." in str(path_label.renderable)

        # Turning it off keeps the text
        view = app.query_one("#file-view", tui.FollowView)
        view.text = "retained content"
        await pilot.pause(0.25)
        await pilot.click("#see-files")
        await pilot.pause()
        assert pane.display is False
        assert view.text == "retained content"


@pytest.mark.asyncio
async def test_view_is_read_only_and_does_not_soft_wrap(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test() as pilot:
        view = app.query_one("#file-view", tui.FollowView)
        assert view.read_only is True
        assert view.soft_wrap is False
        assert view.show_line_numbers is True


@pytest.mark.asyncio
async def test_at_160_by_40_split_is_side_by_side(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.click("#see-files")
        await pilot.pause()
        split = app.query_one("#split")
        assert "stacked" not in split.classes
        col = app.query_one("#console-column")
        pane = app.query_one("#file-pane")
        assert col.region.x == 0
        assert pane.region.x >= 80
        assert col.region.y == pane.region.y


@pytest.mark.asyncio
async def test_at_80_by_24_with_files_on_it_is_stacked_and_stop_and_save_inside_screen(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.click("#see-files")
        await pilot.pause()
        split = app.query_one("#split")
        assert "stacked" in split.classes
        pane = app.query_one("#file-pane")
        col = app.query_one("#console-column")
        assert pane.region.y < col.region.y
        stop = app.query_one("#stop", tui.Button)
        save = app.query_one("#cb-save", tui.Button)
        assert 0 <= stop.region.x < 80
        assert 0 <= stop.region.bottom <= 24
        assert 0 <= save.region.x < 80
        assert 0 <= save.region.bottom <= 24


@pytest.mark.asyncio
async def test_write_opens_on_right_and_second_path_replaces_it(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.click("#see-files")
        await pilot.pause()

        split = app.query_one("#split")
        pane = app.query_one("#file-pane")
        assert "stacked" not in split.classes
        assert pane.region.x >= 80

        # First write arrives
        app._apply_follow(
            tui.file_follow.FollowUpdate(
                path="src/main.py",
                text="print('hello')\n",
                notice=None,
                changed_line=1,
            )
        )
        await pilot.pause()

        path_label = app.query_one("#file-path", tui.Static)
        view = app.query_one("#file-view", tui.FollowView)
        assert str(path_label.renderable) == "src/main.py"
        assert view.text == "print('hello')\n"
        assert app._follow_order == ["src/main.py"]

        # Second path replaces it
        app._apply_follow(
            tui.file_follow.FollowUpdate(
                path="src/util.py",
                text="def util(): pass\n",
                notice=None,
                changed_line=1,
            )
        )
        await pilot.pause()

        assert str(path_label.renderable) == "src/util.py"
        assert view.text == "def util(): pass\n"
        assert app._follow_order == ["src/main.py", "src/util.py"]
        assert app._follow_index == 1


@pytest.mark.asyncio
async def test_earlier_holds_first_file_and_newer_write_only_updates_path_line(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.click("#see-files")
        await pilot.pause()

        # Follow two writes
        app._apply_follow(
            tui.file_follow.FollowUpdate(
                path="file1.py",
                text="file 1 content\n",
                notice=None,
                changed_line=1,
            )
        )
        app._apply_follow(
            tui.file_follow.FollowUpdate(
                path="file2.py",
                text="file 2 content\n",
                notice=None,
                changed_line=1,
            )
        )
        await pilot.pause()

        earlier_btn = app.query_one("#file-earlier", tui.Button)
        later_btn = app.query_one("#file-later", tui.Button)
        assert earlier_btn.disabled is False
        assert later_btn.disabled is True

        # Click Earlier: holds the first file
        await pilot.click("#file-earlier")
        await pilot.pause()

        path_label = app.query_one("#file-path", tui.Static)
        view = app.query_one("#file-view", tui.FollowView)
        assert app._follow_hold is True
        assert str(path_label.renderable) == "file1.py · held · 1 newer"
        assert view.text == "file 1 content\n"
        assert earlier_btn.disabled is True
        assert later_btn.disabled is False

        # Newer write arrives: only updates path line, leaves view alone
        app._apply_follow(
            tui.file_follow.FollowUpdate(
                path="file3.py",
                text="file 3 content\n",
                notice=None,
                changed_line=1,
            )
        )
        await pilot.pause()

        assert str(path_label.renderable) == "file1.py · held · 2 newer"
        assert view.text == "file 1 content\n"
        assert app._follow_shown["file3.py"] == "file 3 content\n"
        assert app._follow_order == ["file1.py", "file2.py", "file3.py"]

        # Clicking Later steps forward
        await pilot.click("#file-later")
        await pilot.pause(0.25)
        assert str(path_label.renderable) == "file2.py · held · 1 newer"
        assert view.text == "file 2 content\n"

        # Reaching newest with Later resumes following
        await pilot.click("#file-later")
        await pilot.pause(0.25)
        assert str(path_label.renderable) == "file3.py"
        assert view.text == "file 3 content\n"
        assert app._follow_hold is False
        assert later_btn.disabled is True


@pytest.mark.asyncio
async def test_same_file_save_after_user_scrolls_keeps_scroll_y_and_says_updated(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.click("#see-files")
        await pilot.pause()

        initial_content = "".join(f"line {i:03d}\n" for i in range(100))
        app._apply_follow(
            tui.file_follow.FollowUpdate(
                path="doc.py",
                text=initial_content,
                notice=None,
                changed_line=1,
            )
        )
        await pilot.pause()

        view = app.query_one("#file-view", tui.FollowView)
        path_label = app.query_one("#file-path", tui.Static)
        assert str(path_label.renderable) == "doc.py"

        # User scrolls
        view.scroll_y = 20
        await pilot.pause()
        assert app._follow_user_scrolled is True

        # Same-file save arrives
        updated_content = "".join(f"modified line {i:03d}\n" for i in range(100))
        app._apply_follow(
            tui.file_follow.FollowUpdate(
                path="doc.py",
                text=updated_content,
                notice=None,
                changed_line=50,
            )
        )
        await pilot.pause()

        assert "doc.py — updated" in str(path_label.renderable)
        assert view.scroll_y == 20
        assert "modified line" in view.text


@pytest.mark.asyncio
async def test_notice_shows_no_bytes(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.click("#see-files")
        await pilot.pause()

        view = app.query_one("#file-view", tui.FollowView)
        view.text = "previous text"
        await pilot.pause()

        app._apply_follow(
            tui.file_follow.FollowUpdate(
                path="binary.dat",
                text=None,
                notice="binary, not shown",
                changed_line=1,
            )
        )
        await pilot.pause()

        path_label = app.query_one("#file-path", tui.Static)
        assert str(path_label.renderable) == "binary.dat — binary, not shown"
        assert view.text == ""
        assert "binary.dat" not in app._follow_order


@pytest.mark.asyncio
async def test_busy_arms_and_idle_disarms_only_with_files_on(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        # Files is off
        assert app._files_on is False
        app._set_busy(True, "agent working")
        assert app._follow_timer is None
        app._set_busy(False)
        assert app._follow_timer is None

        # Turn Files on
        await pilot.click("#see-files")
        await pilot.pause()
        assert app._files_on is True

        app._set_busy(True, "agent working")
        assert app._follow_timer is not None

        app._set_busy(False)
        assert app._follow_timer is None

        # Turning Files off during run disarms
        app._set_busy(True, "agent working")
        assert app._follow_timer is not None
        await pilot.click("#see-files")
        await pilot.pause()
        assert app._files_on is False
        assert app._follow_timer is None


@pytest.mark.asyncio
async def test_fake_relay_state_adds_relay_repo_and_shows_file_as_repo_name_path(tmp_path):
    import subprocess
    from whyline_relay import running, state

    # Initialize root git repo
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init root"], cwd=tmp_path, check=True, capture_output=True)

    # Initialize task git repo
    task_repo = tmp_path / "sub_repo"
    task_repo.mkdir()
    subprocess.run(["git", "init"], cwd=task_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=task_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=task_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init task repo"], cwd=task_repo, check=True, capture_output=True)

    # Write plan and fake relay state
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("- [ ] TASK-1 Some task\n  relay-repo: sub_repo\n", encoding="utf-8")
    st = state.RelayState(
        plan=str(plan_file),
        branch="main",
        task_id="TASK-1",
        round=1,
        base_commit="HEAD",
        paused_reason="",
        log_path="",
    )
    state.save(tmp_path, st)

    # Set running marker
    running.start_turn(tmp_path, "antigravity", "TASK-1", 1)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.click("#see-files")
        await pilot.pause()

        watched = [r.resolve() for r in app._watched_repos()]
        assert task_repo.resolve() in watched

        # File in task repo shown as repo-name:path
        expected_display = f"{task_repo.name}:feature.py"
        app._apply_follow(
            tui.file_follow.FollowUpdate(
                path=expected_display,
                text="def feature(): pass\n",
                notice=None,
                changed_line=1,
            )
        )
        await pilot.pause()

        path_label = app.query_one("#file-path", tui.Static)
        view = app.query_one("#file-view", tui.FollowView)
        assert str(path_label.renderable) == expected_display
        assert view.text == "def feature(): pass\n"


@pytest.mark.asyncio
async def test_gather_error_sets_path_line_and_leaves_transcript(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.click("#see-files")
        await pilot.pause()

        transcript = app.query_one("#transcript", tui.RichLog)
        initial_lines = len(transcript.lines)

        error_reason = "git: fatal error reading porcelain status"
        app._on_gather_error(error_reason)
        await pilot.pause()

        path_label = app.query_one("#file-path", tui.Static)
        assert str(path_label.renderable) == error_reason
        assert len(transcript.lines) == initial_lines
        assert app._follow_last_error == error_reason

        # Setting error again only sets it once
        app._on_gather_error(error_reason)
        await pilot.pause()
        assert str(path_label.renderable) == error_reason
        assert len(transcript.lines) == initial_lines


@pytest.mark.asyncio
async def test_gather_follow_detects_real_changes_and_ledger_hints(tmp_path):
    import json
    import subprocess
    from whyline.events import FILE_TOUCHED, new_event

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        app._arm_follow()
        assert app._follow_timer is not None
        app._disarm_follow()
        assert app._follow_timer is None

        file_p = tmp_path / "hello.py"
        file_p.write_text("print('hello world')\n", encoding="utf-8")

        ledger_dir = tmp_path / ".whyline"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_p = ledger_dir / "ledger.jsonl"
        with open(ledger_p, "a", encoding="utf-8") as f:
            f.write(json.dumps(new_event(FILE_TOUCHED, path="hello.py")) + "\n")

        baseline, offset, update = app._gather_follow()
        assert update is not None
        assert update.path == "hello.py"
        assert update.text == "print('hello world')\n"
        assert offset > 0


def test_gather_follow_error_on_bad_repo(tmp_path):
    app = tui.WhylineConsoleApp(root=tmp_path)
    with pytest.raises(RuntimeError):
        app._gather_follow()
