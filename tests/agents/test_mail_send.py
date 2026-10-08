from pathlib import Path

import pytest

from whyline.agents import mail_send


def runner(code=0, stderr=""):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        class R:
            returncode = code
        R.stderr = stderr
        return R()

    return run, calls


def test_arguments_are_passed_separately_never_spliced(tmp_path):
    run, calls = runner()
    doc = tmp_path / "jobs.docx"
    mail_send.send(["a@example.com", "o'brien@example.com"], 'Daily "jobs" — 2026-10-09',
                   "body", [doc], run=run, system=lambda: "Darwin")
    argv, kwargs = calls[0]
    assert argv[:2] == ["osascript", "-"]
    assert argv[2:] == ['Daily "jobs" — 2026-10-09', "body", "2",
                        "a@example.com", "o'brien@example.com", str(doc)]
    assert kwargs["input"] == mail_send.SCRIPT and "o'brien" not in mail_send.SCRIPT


def test_automation_permission_message():
    run, _ = runner(1, "execution error: Not authorized to send Apple events to Mail. (-1743)")
    with pytest.raises(mail_send.MailError, match="Privacy & Security → Automation"):
        mail_send.send(["a@example.com"], "s", "b", [], run=run, system=lambda: "Darwin")


def test_no_account_message():
    run, _ = runner(1, "execution error: whyline: no Mail account (9001)")
    with pytest.raises(mail_send.MailError, match="no account set up"):
        mail_send.send(["a@example.com"], "s", "b", [], run=run, system=lambda: "Darwin")


def test_other_errors_use_the_first_line():
    run, _ = runner(1, "something odd\nmore")
    with pytest.raises(mail_send.MailError, match="^something odd$"):
        mail_send.send(["a@example.com"], "s", "b", [], run=run, system=lambda: "Darwin")


def test_not_on_macos():
    with pytest.raises(mail_send.MailError, match="needs the Mail app on macOS"):
        mail_send.send(["a@example.com"], "s", "b", [], system=lambda: "Linux")


def test_mail_not_ready_is_retried_once(tmp_path):
    # Found in the live check: the first send failed with "Connection is
    # invalid (-609)" while Mail was starting / asking for permission.
    calls, slept = [], []
    outcomes = [(1, "execution error: Mail got an error: Connection is invalid. (-609)"), (0, "")]

    def run(argv, **kwargs):
        calls.append(argv)
        code, err = outcomes[len(calls) - 1]

        class R:
            returncode = code
            stderr = err
        return R()

    mail_send.send(["a@example.com"], "s", "b", [], run=run, system=lambda: "Darwin",
                   sleep=slept.append)
    assert len(calls) == 2 and slept == [5]


def test_mail_still_not_ready_says_so_plainly():
    run, calls = runner(1, "execution error: Mail got an error: Connection is invalid. (-609)")
    with pytest.raises(mail_send.MailError, match="Mail wasn't ready"):
        mail_send.send(["a@example.com"], "s", "b", [], run=run, system=lambda: "Darwin",
                       sleep=lambda s: None)
    assert len(calls) == 2


def test_the_script_starts_mail_before_writing():
    assert "is not running" in mail_send.SCRIPT and "launch" in mail_send.SCRIPT
