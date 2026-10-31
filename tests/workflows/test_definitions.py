from pathlib import Path

import pytest

from whyline.workflows import definitions as d
from whyline.workflows import paths
from whyline.workflows.steps import STEP_TYPES

@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


EXAMPLE = '''
name = "pr-digest"
description = "Weekday PR summary to Telegram"
version = 1

[trigger]
kind = "weekdays"
at = "08:00"

[[input]]
name = "topic"
type = "string"
default = ""

[[step]]
id = "summarise"
type = "agent"
runner = "claude"
backup = ["codex"]
instructions = "Summarise these PRs: what needs my action today."
inputs = ["{{ steps.fetch.body }}"]
output = "text"

[[step]]
id = "send"
type = "deliver"
to = "telegram"
text = "{{ steps.summarise.output }}"

[layout]
summarise = [0, 0]
send = [1, 0]
'''

ROUTED = '''
name = "route"

[trigger]
kind = "manual"

[[step]]
id = "check"
type = "condition"
left = "{{ inputs.topic }}"
op = "contains"
right = "pr"
then = "yes"
else = "no"

[[step]]
id = "yes"
type = "stop"

[[step]]
id = "no"
type = "switch"
value = "{{ inputs.topic }}"
default = "end"
cases = { a = { equals = "a", goto = "end" } }

[[step]]
id = "end"
type = "stop"
'''


def parse(text: str, kind: str = "personal", **kw) -> d.Workflow:
    return d.parse(text, kind=kind, path=Path("w.toml"), **kw)


def errors_of(text: str) -> list[str]:
    with pytest.raises(d.DefinitionError) as info:
        parse(text)
    return str(info.value).splitlines()


def step(body: str, extra: str = "") -> str:
    return f'name = "w"\n[[step]]\nid = "a"\n{body}\n{extra}'


def test_paths_are_private(home):
    assert paths.home() == home / ".whyline" / "workflows"
    assert paths.home().stat().st_mode & 0o777 == 0o700
    assert paths.runs_dir().stat().st_mode & 0o777 == 0o700
    assert paths.state_path().name == "state.sqlite"
    assert paths.settings_path().name == "settings.toml"
    assert paths.reports_dir("x") == paths.home() / "reports" / "x"
    assert paths.repo_dir(Path("/r")) == Path("/r/.whyline/workflows")


def test_registry_has_the_plan_one_types():
    assert set(STEP_TYPES) == {"set", "condition", "switch", "wait", "stop",
                               "approval", "agent", "deliver"}
    assert STEP_TYPES["deliver"].writes and not STEP_TYPES["agent"].writes
    for name in ("runner", "backup", "model", "instructions"):
        assert not STEP_TYPES["agent"].field(name).templated
    for name in ("to", "chat", "email"):
        assert not STEP_TYPES["deliver"].field(name).templated
    assert STEP_TYPES["agent"].field("inputs").templated


def test_example_round_trips(home):
    first = parse(EXAMPLE)
    assert first.workflow_id == "personal:pr-digest"
    assert [s.id for s in first.steps] == ["summarise", "send"]
    assert first.trigger == d.TriggerSpec("weekdays", at="08:00")
    text = d.render(first)
    assert text.rstrip().splitlines()[-3] == "[layout]"
    assert parse(text) == first


def test_routed_example_round_trips():
    first = parse(ROUTED)
    assert parse(d.render(first)) == first


def test_repo_workflow_id_and_root(tmp_path):
    flow = parse(ROUTED, "repo", repo_root=tmp_path)
    assert flow.workflow_id == f"repo:{tmp_path.resolve()}:route"
    assert "needs its repository" in errors_of_repo(ROUTED)[0]


def errors_of_repo(text: str) -> list[str]:
    with pytest.raises(d.DefinitionError) as info:
        parse(text, "repo")
    return str(info.value).splitlines()


def test_name_pattern():
    assert 'field "name"' in errors_of('name = "Bad_Name"')[0]


def test_unknown_top_level_key():
    assert errors_of('name = "w"\nbogus = 1') == ['field "bogus": unknown']


def test_invalid_toml():
    assert errors_of("name = ")[0].startswith("not valid TOML")


@pytest.mark.parametrize("trigger, fragment", [
    ('kind = "telegram"', 'field "kind"'),
    ('kind = "daily"', 'field "at"'),
    ('kind = "daily"\nat = "8am"', 'field "at"'),
    ('kind = "every"\nevery_hours = 5', 'field "every_hours"'),
    ('kind = "every"\nevery_hours = 25', 'field "every_hours"'),
    ('kind = "folder"', 'field "folder"'),
    ('kind = "folder"\nfolder = "/etc"', 'inside your home'),
    ('kind = "manual"\nat = "08:00"', 'field "at"'),
])
def test_trigger_rules(trigger, fragment):
    lines = errors_of(f'name = "w"\n[trigger]\n{trigger}')
    assert len(lines) == 1 and lines[0].startswith("trigger:") and fragment in lines[0]


def test_trigger_folder_under_home_and_every_hours(home):
    parse(f'name = "w"\n[trigger]\nkind = "folder"\nfolder = "~/Inbox"')
    parse('name = "w"\n[trigger]\nkind = "every"\nevery_hours = 4')


def test_step_id_rules():
    assert 'step "A" field "id"' in errors_of(
        'name = "w"\n[[step]]\nid = "A"\ntype = "stop"')[0]
    lines = errors_of('name = "w"\n[[step]]\nid = "a"\ntype = "stop"\n'
                      '[[step]]\nid = "a"\ntype = "stop"')
    assert lines == ['step "a" field "id": used twice']
    assert errors_of('name = "w"\n[[step]]\ntype = "stop"')[0].startswith("step #1 field")


def test_unknown_type_names_the_step():
    assert errors_of(step('type = "http"'))[0].startswith('step "a" field "type"')


def test_unknown_key_required_and_kind():
    assert errors_of(step('type = "stop"\nbogus = 1')) == [
        'step "a" field "bogus": unknown for a stop step']
    assert errors_of(step('type = "deliver"\nto = "file"')) == [
        'step "a" field "text": required']
    assert errors_of(step('type = "approval"\nmessage = 3')) == [
        'step "a" field "message": must be a str']
    assert errors_of(step('type = "approval"\nmessage = "x"\nexpires_hours = "1"')) == [
        'step "a" field "expires_hours": must be a int']


def test_every_problem_is_reported_one_per_line():
    lines = errors_of(step('type = "agent"\nrunner = "nope"\nbogus = 1'))
    assert len(lines) == 3
    assert all(line.startswith('step "a" field') for line in lines)


def test_ranges_and_rules():
    assert 'field "minutes"' in errors_of(step('type = "wait"\nminutes = 0'))[0]
    assert 'exactly one' in errors_of(step('type = "wait"'))[0]
    assert 'field "until"' in errors_of(step('type = "wait"\nuntil = "9"'))[0]
    assert 'field "timeout_minutes"' in errors_of(
        step('type = "agent"\nrunner = "claude"\ninstructions = "x"\ntimeout_minutes = 999'))[0]
    assert 'field "backup"' in errors_of(
        step('type = "agent"\nrunner = "claude"\ninstructions = "x"\nbackup = ["claude"]'))[0]
    assert 'field "right"' in errors_of(
        step('type = "condition"\nleft = "x"\nop = "eq"'))[0]
    assert 'field "email"' in errors_of(
        step('type = "deliver"\nto = "email"\ntext = "x"'))[0]


@pytest.mark.parametrize("field_line, name", [
    ('runner = "{{ x }}"', "runner"),
    ('backup = ["{{ x }}"]', "backup"),
    ('model = "{{ x }}"', "model"),
    ('instructions = "{{ x }}"', "instructions"),
])
def test_agent_target_fields_refuse_templates(field_line, name):
    body = {"runner": 'runner = "claude"', "instructions": 'instructions = "x"'}
    body[name] = field_line
    text = step('type = "agent"\n' + "\n".join(body.values()) +
                ("" if name in body else "\n" + field_line))
    lines = errors_of(text)
    assert any(f'step "a" field "{name}": must not contain a template' in ln for ln in lines)


@pytest.mark.parametrize("name", ["to", "chat", "email"])
def test_deliver_target_fields_refuse_templates(name):
    fields = {"to": 'to = "telegram"', "text": 'text = "x"'}
    fields[name] = f'{name} = "{{{{ x }}}}"'
    lines = errors_of(step('type = "deliver"\n' + "\n".join(fields.values())))
    assert any(f'step "a" field "{name}": must not contain a template' in ln for ln in lines)


def test_templates_allowed_in_templated_fields():
    parse(step('type = "deliver"\nto = "file"\ntext = "{{ run.id }}"\nsubject = "{{ run.id }}"'))


def test_routing_target_refuses_template():
    text = ROUTED.replace('then = "yes"', 'then = "{{ inputs.topic }}"')
    lines = errors_of(text)
    assert lines == ['step "check" field "then": must not contain a template ({{ }})']
    text = ROUTED.replace('goto = "end"', 'goto = "{{ x }}"')
    assert errors_of(text) == ['step "no" field "cases.a.goto": '
                               'must not contain a template ({{ }})']


def test_missing_routing_target():
    lines = errors_of(ROUTED.replace('else = "no"', 'else = "gone"'))
    assert lines == ['step "check" field "else": no step "gone"']


def test_self_and_backward_routing_targets_are_refused():
    lines = errors_of(ROUTED.replace('then = "yes"', 'then = "check"'))
    assert lines == ['step "check" field "then": "check" must come later in the file']
    lines = errors_of(ROUTED.replace('default = "end"', 'default = "check"'))
    assert lines == ['step "no" field "default": "check" must come later in the file']
    lines = errors_of(ROUTED.replace('goto = "end"', 'goto = "yes"'))
    assert 'cases.a.goto' in lines[0] and 'must come later' in lines[0]


def test_switch_case_shape():
    lines = errors_of(ROUTED.replace('{ equals = "a", goto = "end" }', '{ equals = "a" }'))
    assert lines[0].startswith('step "no" field "cases": case "a"')


def test_step_limit():
    steps = "".join(f'[[step]]\nid = "s{i}"\ntype = "stop"\n' for i in range(31))
    assert 'at most 30' in errors_of('name = "w"\n' + steps)[0]
    parse('name = "w"\n' + steps.replace('[[step]]\nid = "s30"\ntype = "stop"\n', ""))


def test_input_rules():
    base = 'name = "w"\n[[input]]\n'
    assert 'field "name"' in errors_of(base + 'name = "Bad"')[0]
    assert 'field "type"' in errors_of(base + 'name = "a"\ntype = "date"')[0]
    assert 'field "default"' in errors_of(base + 'name = "a"\ntype = "number"\ndefault = "x"')[0]
    assert 'used twice' in errors_of(base + 'name = "a"\n[[input]]\nname = "a"')[0]


def test_layout_move_changes_layout_hash_only():
    a = parse(EXAMPLE)
    b = parse(EXAMPLE.replace("send = [1, 0]", "send = [4, 2]"))
    assert d.layout_hash(a.raw) != d.layout_hash(b.raw)
    assert d.semantic_hash(a.raw) == d.semantic_hash(b.raw)


def test_instruction_change_changes_semantic_hash_only():
    a = parse(EXAMPLE)
    b = parse(EXAMPLE.replace("what needs my action today", "anything urgent"))
    assert d.semantic_hash(a.raw) != d.semantic_hash(b.raw)
    assert d.layout_hash(a.raw) == d.layout_hash(b.raw)


def test_hash_ignores_formatting_and_round_trip():
    a = parse(EXAMPLE)
    assert d.semantic_hash(parse(d.render(a)).raw) == d.semantic_hash(a.raw)
    assert len(d.semantic_hash(a.raw)) == 64


def test_discover_lists_broken_and_valid(home, tmp_path):
    personal = home / ".whyline" / "workflows"
    personal.mkdir(parents=True)
    (personal / "good.toml").write_text(ROUTED.replace('"route"', '"good"'))
    (personal / "bad.toml").write_text(step('type = "deliver"\nto = "{{ x }}"\ntext = "x"'))
    (personal / "settings.toml").write_text("daily_agent_cap = 0\n")
    repo = tmp_path / "repo"
    (repo / ".whyline" / "workflows").mkdir(parents=True)
    (repo / ".whyline" / "workflows" / "shared.toml").write_text(
        ROUTED.replace('"route"', '"shared"'))
    found = d.discover(repo)
    assert [(type(f).__name__, f.path.name) for f in found] == [
        ("Workflow", "shared.toml"), ("Broken", "bad.toml"), ("Workflow", "good.toml")]
    broken = found[1]
    assert broken.kind == "personal"
    assert 'step "a" field "to": must not contain a template' in broken.error
    assert [f.path.name for f in d.discover(None)] == ["bad.toml", "good.toml"]
