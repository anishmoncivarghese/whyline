import pytest

from whyline.agents import mail


def test_script_writes_the_message_to_a_file_and_triggers_the_agent():
    text = mail.script_text("inbox-triage", "/opt/bin/whyline")
    assert "using terms from application \"Mail\"" in text
    assert "perform mail action with messages" in text
    assert "/opt/bin/whyline agents trigger inbox-triage --file" in text
    assert "quoted form of" in text  # paths are quoted for the shell


def test_install_writes_into_mails_script_folder(home, monkeypatch):
    monkeypatch.setattr(mail, "_whyline_path", lambda: "/opt/bin/whyline")
    path = mail.install("inbox-triage")
    assert path == home / "Library/Application Scripts/com.apple.mail/whyline-inbox-triage.applescript"
    assert path.read_text().count("inbox-triage") >= 1


def test_an_executable_path_with_spaces_is_one_shell_word():
    path = "/Applications/Whyline Tools/bin/whyline"
    text = mail.script_text("inbox-triage", path)
    assert f"'{path}' agents trigger inbox-triage --file" in text
    assert f'"{path} agents trigger' not in text


def test_an_executable_path_with_an_apostrophe_stays_in_the_applescript_string():
    # shlex.quote turns an apostrophe into '"'"', and those double quotes
    # would end the AppleScript string unless they are escaped.
    text = mail.script_text("inbox-triage", "/Users/o'brien/bin/whyline")
    assert (
        "\"'/Users/o'\\\"'\\\"'brien/bin/whyline' "
        "agents trigger inbox-triage --file \""
    ) in text


def test_the_message_is_written_without_a_shell_heredoc():
    # A message body is untrusted. Pasting it into a quoted heredoc lets a
    # line equal to the delimiter end the heredoc and run the rest as shell.
    text = mail.script_text("inbox-triage", "/opt/bin/whyline")
    assert "sender of m" in text
    assert "subject of m" in text
    assert "date received of m" in text
    assert "content of m" in text
    assert "open for access" in text
    assert "WHYLINE_EOF" not in text


def test_a_name_that_is_not_an_agent_name_is_rejected():
    with pytest.raises(ValueError, match="name must be"):
        mail.script_text("../x", "/opt/bin/whyline")


def test_mail_script_command_prints_the_path(home, monkeypatch, capsys):
    from whyline import cli

    monkeypatch.setattr(mail, "_whyline_path", lambda: "/opt/bin/whyline")
    monkeypatch.setattr(mail, "supported", lambda: True)
    assert cli.main(["agents", "mail-script", "inbox-triage"]) == 0
    path = home / "Library/Application Scripts/com.apple.mail/whyline-inbox-triage.applescript"
    assert capsys.readouterr().out == path.as_posix() + "\n"
    assert "inbox-triage" in path.read_text()


def test_mail_script_command_needs_macos(monkeypatch, capsys):
    from whyline import cli

    monkeypatch.setattr(mail, "supported", lambda: False)

    def refuse(name):
        raise AssertionError("install")

    monkeypatch.setattr(mail, "install", refuse)
    assert cli.main(["agents", "mail-script", "inbox-triage"]) == 1
    err = capsys.readouterr().err
    assert err == mail.NEEDS_MACOS + "\n"
    assert "macOS" in err
