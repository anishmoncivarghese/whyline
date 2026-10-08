import json
import os

import pytest

from whyline.agents import deliveries as dl, records, service
from whyline.agents import definitions as d


def test_round_trip_and_private_file(home):
    want = dl.Delivery(email=("a@example.com", "o'brien@example.com"), subject="Daily jobs",
                       telegram_chat=-1001, telegram_label="Family jobs (group)",
                       attach="docx", on_failure="silent", command="echo hi")
    dl.save("personal:jobs", want)
    assert dl.get("personal:jobs") == want
    assert dl.get("personal:other") is None
    if os.name != "nt":
        assert (dl.path().stat().st_mode & 0o777) == 0o600


def test_repo_agent_ids_with_paths_are_valid_keys(home, tmp_path):
    agent_id = f"repo:{tmp_path.resolve()}:digest"
    dl.save(agent_id, dl.Delivery(email=("a@example.com",)))
    assert dl.get(agent_id).email == ("a@example.com",)


def test_an_empty_delivery_removes_the_table(home):
    dl.save("personal:jobs", dl.Delivery(email=("a@example.com",)))
    dl.save("personal:jobs", dl.Delivery())
    assert dl.get("personal:jobs") is None


@pytest.mark.parametrize("delivery, message", [
    (dl.Delivery(email=("not-an-address",)), "not an email address"),
    (dl.Delivery(email=("a@b@example.com",)), "not an email address"),
    (dl.Delivery(email=("a @example.com",)), "not an email address"),
    (dl.Delivery(email=("a@example.com",), subject="x" * 121), "120 characters"),
    (dl.Delivery(email=("a@example.com",), subject="two\nlines"), "one line"),
    (dl.Delivery(email=("a@example.com",), attach="pdf"), "docx or md"),
    (dl.Delivery(email=("a@example.com",), on_failure="loud"), "alert or silent"),
    (dl.Delivery(command="a\nb"), "one line"),
])
def test_validation(home, delivery, message):
    with pytest.raises(dl.DeliveryError, match=message):
        dl.save("personal:jobs", delivery)


def test_an_unknown_telegram_chat_is_refused_on_save(home):
    with pytest.raises(dl.DeliveryError, match="Telegram setup"):
        dl.save("personal:jobs", dl.Delivery(telegram_chat=5), known_chats={7})
    dl.save("personal:jobs", dl.Delivery(telegram_chat=7), known_chats={7})


def test_parse_emails():
    assert dl.parse_emails(" a@example.com, ,b@example.com ") == ("a@example.com", "b@example.com")


def test_unreadable_file_raises_a_delivery_error(home):
    dl.path().write_text("not = [valid", encoding="utf-8")
    with pytest.raises(dl.DeliveryError, match="deliveries.toml"):
        dl.load_all()


def test_deleting_an_agent_removes_its_deliveries(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "p.toml").write_text(
        f'name="p"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n')
    defn = d.load(folder / "p.toml", kind="personal")
    dl.save(defn.agent_id, dl.Delivery(email=("a@example.com",)))
    service.delete("p", None)
    assert dl.get(defn.agent_id) is None


def test_run_record_keeps_deliveries(home, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    folder = home / ".whyline/agents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "p.toml").write_text(
        f'name="p"\ninstructions="x"\nrunner="codex"\nworkdir={json.dumps(str(work))}\n')
    defn = d.load(folder / "p.toml", kind="personal")
    from datetime import datetime
    record, run_dir = records.new_run(defn, source="manual", now=datetime(2026, 10, 9, 7, 0))
    assert records.run_folder(record.run_id) == run_dir
    record.deliveries = [{"to": "email", "ok": True, "detail": ""}]
    records.save_metadata(record)
    assert records.load(record.run_id).deliveries == record.deliveries
