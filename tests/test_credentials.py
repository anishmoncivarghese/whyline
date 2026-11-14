import os

import pytest

from whyline import credentials as cr

SECRET = "s3cr3t-VALUE"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


class Store:
    def __init__(self):
        self.argvs, self.stdins, self.data = [], [], {}

    def run(self, argv, **kwargs):
        self.argvs.append(list(argv))
        self.stdins.append(kwargs.get("input"))

        class R:
            returncode = 0
            stdout = ""

        r = R()
        if argv[:2] == ["security", "-i"]:
            line = kwargs["input"]
            name = line.split(" -a ")[1].split(" ")[0]
            quoted = line.split(" -w ", 1)[1].rstrip("\n")
            self.data[name] = quoted[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        elif argv[0] == "security" and argv[1] == "find-generic-password":
            r.stdout = self.data.get(argv[argv.index("-a") + 1], "") + "\n"
            r.returncode = 0 if argv[argv.index("-a") + 1] in self.data else 44
        elif argv[0] == "security" and argv[1] == "delete-generic-password":
            self.data.pop(argv[argv.index("-a") + 1], None)
        return r


MAC = {"which": lambda tool: "/usr/bin/" + tool, "system": "Darwin"}


def test_save_then_value_round_trips_without_secret_in_argv(home):
    store = Store()
    cr.save(cr.Credential("gh", "bearer", origins=("https://api.github.com",)), SECRET,
            run=store.run, **MAC)
    assert cr.value("gh", run=store.run, **MAC) == SECRET
    assert all(SECRET not in part for argv in store.argvs for part in argv)
    assert cr.get("gh").origins == ("https://api.github.com",)


def test_awkward_value_survives_or_is_refused(home):
    store = Store()
    tricky = 'a "quoted" \\ value with spaces'
    cr.save(cr.Credential("tricky", "bearer"), tricky, run=store.run, **MAC)
    assert cr.value("tricky", run=store.run, **MAC) == tricky
    with pytest.raises(ValueError):
        cr.save(cr.Credential("nl", "bearer"), "line1\nline2", run=store.run, **MAC)
    assert cr.get("nl") is None


def test_remove_deletes_metadata_and_value(home):
    store = Store()
    cr.save(cr.Credential("gh", "bearer"), SECRET, run=store.run, **MAC)
    cr.remove("gh", run=store.run, **MAC)
    assert cr.get("gh") is None and "gh" not in store.data


def test_locked_when_no_tool(home):
    none = {"which": lambda tool: None, "system": "Linux"}
    assert cr.available(**none) == (False, "no secure credential store on this system")
    with pytest.raises(cr.Locked, match="no secure credential store"):
        cr.value("gh", **none)


def test_metadata_file_has_no_value_and_is_private(home):
    store = Store()
    cr.save(cr.Credential("gh", "bearer"), SECRET, run=store.run, **MAC)
    target = home / ".whyline" / "credentials.toml"
    assert SECRET not in target.read_text()
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


def test_env_credential_has_no_origins(home):
    store = Store()
    cr.save(cr.Credential("tok", "env"), SECRET, run=store.run, **MAC)
    assert cr.get("tok").origins == ()
    with pytest.raises(ValueError):
        cr.save(cr.Credential("bad", "env", origins=("https://x.com",)), SECRET,
                run=store.run, **MAC)


def test_redaction_values_include_base64_for_basic(home):
    store = Store()
    cr.save(cr.Credential("b", "basic"), "user:pw", run=store.run, **MAC)
    assert cr.redaction_values(["b"], run=store.run, **MAC) == ["user:pw", "dXNlcjpwdw=="]
