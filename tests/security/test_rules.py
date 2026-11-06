"""The bundled secret rules and the Go-to-Python regex translator.

Samples are assembled from pieces so this file never holds a literal that a
secret scanner (GitHub push protection, or whyline's own) would flag.
"""

from __future__ import annotations

import re

import pytest

from whyline.security.rules import load_rules, translate


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def test_bundled_file_loads_and_nearly_all_rules_compile(rules):
    total = len(rules.rules) + len(rules.skipped)
    assert total >= 200
    assert len(rules.rules) / total >= 0.98


def test_rules_carry_their_fields(rules):
    by_id = {rule.id: rule for rule in rules.rules}
    aws = by_id["aws-access-token"]
    assert aws.entropy == 3
    assert "akia" in aws.keywords
    assert all(word == word.lower() for rule in rules.rules for word in rule.keywords)
    assert any(rule.allowlists for rule in rules.rules)
    generic = by_id["generic-api-key"]
    assert any(a.regex_target == "match" for a in generic.allowlists)
    assert rules.allowlist.paths
    assert rules.allowlist.stopwords


@pytest.mark.parametrize(
    ("go", "python"),
    [
        ("abc(?i)def", "abc(?i:def)"),
        ("x(?:a(?i)b)c", "x(?:a(?i:b))c"),
        ("foo\\z", "foo\\Z"),
        ("(?i)abc", "(?i)abc"),
        ("a(?i)b|c", "a(?i:b)|(?i:c)"),
        ("a(?-i)b", "a(?-i:b)"),
        ("[(?i)]x", "[(?i)]x"),
        ("[^]a(?i)]b", "[^]a(?i)]b"),
        ("\\(?i\\)x", "\\(?i\\)x"),
    ],
)
def test_translate(go, python):
    assert translate(go) == python
    re.compile(python)


def test_translate_applies_flags_only_to_the_rest_of_the_group():
    pattern = re.compile(translate("x(?:a(?i)b)c"))
    assert pattern.fullmatch("xaBc")
    assert not pattern.fullmatch("xaBC")
    assert not pattern.fullmatch("XaBc")


def test_translate_keeps_flags_across_alternation():
    pattern = re.compile(translate("a(?i)b|c"))
    assert pattern.fullmatch("aB")
    assert pattern.fullmatch("C")
    assert not pattern.fullmatch("A")


def test_translate_leaves_unsupported_forms_to_fail():
    with pytest.raises(re.error):
        re.compile(translate("a(?U)b"))


def test_skipped_ids_are_reported(tmp_path):
    config = tmp_path / "rules.toml"
    config.write_text(
        "\n".join(
            [
                "[[rules]]",
                'id = "fine"',
                "regex = '''abc(?i)def'''",
                "[[rules]]",
                'id = "broken"',
                "regex = '''(unclosed'''",
                "[[rules]]",
                'id = "bad-flag"',
                "regex = '''x(?U)y'''",
                "[[rules]]",
                'id = "bad-path"',
                "regex = '''ok'''",
                "path = '''(unclosed'''",
                "[[rules]]",
                'id = "bad-allow"',
                "regex = '''ok'''",
                "[[rules.allowlists]]",
                "regexes = ['''(unclosed''', '''fine''']",
            ]
        )
    )
    loaded = load_rules(config)
    assert [rule.id for rule in loaded.rules] == ["fine", "bad-allow"]
    assert loaded.skipped == ("broken", "bad-flag", "bad-path")
    assert len(loaded.skipped_allow) == 1
    assert loaded.skipped_allow[0].startswith("bad-allow:")
    assert len(loaded.rules[1].allowlists[0].regexes) == 1


def test_path_only_rule_loads_without_a_regex(rules):
    rule = next(r for r in rules.rules if r.id == "pkcs12-file")
    assert rule.regex is None
    assert rule.path.search("certs/site.p12")


def test_every_bundled_skip_is_a_real_rule_id(rules):
    live = {rule.id for rule in rules.rules}
    assert not live & set(rules.skipped)
    assert len(set(rules.skipped)) == len(rules.skipped)


def _samples():
    block = "-----BEGIN " + "RSA PRIV" + "ATE KEY-----"
    end = "-----END " + "RSA PRIV" + "ATE KEY-----"
    return {
        "aws-access-token": (
            "AKIA" + "QWERTYUIOPASDFGH",
            "AKIA" + "SHORT",
        ),
        "github-pat": (
            "gh" + "p_" + "a1B2" * 9,
            "gh" + "p_" + "a1B2" * 8,
        ),
        "github-fine-grained-pat": (
            "github" + "_pat_" + "A1b2C3d4E5" * 8 + "xy",
            "github" + "_pat_" + "A1b2C3d4E5",
        ),
        "slack-bot-token": (
            "xo" + "xb-" + "1234567890" + "-" + "1234567890123" + "-" + "abcdEFGH",
            "xo" + "xb-" + "123" + "-" + "456",
        ),
        "stripe-access-token": (
            "sk" + "_live_" + "A1b2C3d4E5f6G7h8",
            "sk" + "_live_" + "short",
        ),
        "openai-api-key": (
            "sk-" + "a1B2c3D4e5F6g7H8i9J0" + "T3Blbk" + "FJ" + "k1L2m3N4o5P6q7R8s9T0",
            "sk-" + "a1B2c3D4e5F6g7H8i9J0" + "T3Blbk" + "FJ" + "k1L2m3",
        ),
        "anthropic-api-key": (
            "sk-ant-" + "api03-" + "aB3_" * 23 + "a" + "AA",
            "sk-ant-" + "api03-" + "aB3_" * 5 + "AA",
        ),
        "gcp-api-key": (
            "AI" + "za" + "Sy" + "x7Q" * 11,
            "AI" + "za" + "short",
        ),
        "private-key": (
            block + "\n" + "A" * 70 + "\n" + end,
            "-----BEGIN " + "PUBLIC KEY-----\n" + "A" * 70 + "\n-----END " + "PUBLIC KEY-----",
        ),
        "generic-api-key": (
            "api" + "_key" + ' = "' + "q8Zx2LmN4vB7wR9tY1" + '"',
            "api" + "_key" + ' = "' + "abc" + '"',
        ),
    }


@pytest.mark.parametrize("rule_id", list(_samples()))
def test_sample_matches_and_near_miss_does_not(rules, rule_id):
    rule = next((r for r in rules.rules if r.id == rule_id), None)
    assert rule is not None, f"{rule_id} missing or skipped"
    sample, near_miss = _samples()[rule_id]
    assert rule.regex.search(sample)
    assert not rule.regex.search(near_miss)
