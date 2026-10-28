import copy
import json
import pytest
from scire.knowledge import Knowledge, observe, response_likelihoods
from scire.paths import write_json
from scire.models import validate_module
from scire.maps import public_map, concept_fingerprint
from scire.reading import reading_budget, reading_stats, validate_budget


def test_choice_specific_bayes_uses_likelihood_ratio():
    choices = response_likelihoods("a")
    choices["b"] = {"known": 0.01, "unknown": 0.3}
    choices["c"] = {"known": 0.12, "unknown": 0.15}
    diagnostic = observe(None, "b", False, likelihoods=choices, now=100)
    ambiguous = observe(None, "c", False, likelihoods=choices, now=100)
    posterior = 0.2 * 0.01 / (0.2 * 0.01 + 0.8 * 0.3)
    assert diagnostic["mastery"] == pytest.approx(posterior + (1 - posterior) * 0.12)
    assert diagnostic["mastery"] < ambiguous["mastery"]


def test_log_rebuild_ignores_changed_cache_deduplicates_and_forgets(workspace):
    store, repo, root, mapped, module = workspace
    k = Knowledge(store, repo["id"])
    before, after = k.record("dispatch", "q1", "a", True, "", "sha1", response_likelihoods("a"))
    k.record("dispatch", "q1", "a", True, "", "sha1", response_likelihoods("a"))
    write_json(k.path, {"dispatch": {**after, "mastery": 0.99, "attempts": 999}})
    restored = Knowledge(store, repo["id"]).states(now=after["updated_at"])["dispatch"]
    assert restored["attempts"] == 1
    assert restored["mastery"] == pytest.approx(after["mastery"])
    k.path.unlink()
    assert k.states(now=after["updated_at"])["dispatch"]["mastery"] == pytest.approx(after["mastery"])
    assert k.states(now=after["updated_at"] + 90 * 86400)["dispatch"]["mastery"] < after["mastery"]
    assert k.states({"dispatch": "sha2"}, after["updated_at"])["dispatch"]["code_changed"]
    events = [json.loads(line) for line in k.log.read_text().splitlines()]
    assert len([e for e in events if e["type"] == "assessment"]) == 1


def test_legacy_cache_is_imported_once_and_area_rollups_use_replay(workspace):
    store, repo, root, mapped, module = workspace
    k = Knowledge(store, repo["id"])
    legacy = observe(None, "a", True, now=100)
    write_json(k.path, {"dispatch": legacy})
    assert k.states(now=100)["dispatch"]["mastery"] == pytest.approx(legacy["mastery"])
    write_json(k.path, {"dispatch": {**legacy, "mastery": 0.99}})
    assert k.states(now=100)["dispatch"]["mastery"] == pytest.approx(legacy["mastery"])
    k.record("dispatch", "q2", "a", True, "", concept_fingerprint(root, mapped["concepts"][0]))
    m = public_map(store, repo["id"])
    assert m["areas"][0]["mastery"] == pytest.approx(m["concepts"][0]["mastery"])
    assert m["areas"][0]["assessed_count"] == 1
    summary = k.summary(mapped)
    assert summary["assessed"] == 1 and len(json.dumps(summary)) < 2500
    assert "observations" not in json.dumps(summary)


def test_invalid_likelihoods_are_rejected_and_old_questions_get_defaults(workspace):
    store, repo, root, mapped, module = workspace
    validated = validate_module(root, module, mapped)
    assert set(validated["questions"][0]["likelihoods"]) == {"a", "b", "c", "d", "unknown"}
    invalid = copy.deepcopy(validated)
    invalid["questions"][0]["likelihoods"]["a"]["known"] = 0.99
    with pytest.raises(ValueError, match="sum to 1"):
        validate_module(root, invalid, mapped)


def test_reading_budget_counts_questions_feedback_and_prose(workspace):
    module = workspace[-1]
    assert reading_stats([module])["questions"] == 1
    budget = reading_budget(2)
    validate_budget([module], budget)
    with pytest.raises(ValueError, match="reading budget"):
        validate_budget([module] * 3, budget)
    with pytest.raises(ValueError, match="2–15"):
        reading_budget(True)


def test_plain_launch_does_not_reopen_repo_picker_with_connected_repos(workspace, monkeypatch):
    from scire import cli, operations, discovery

    store, repo, root, mapped, module = workspace
    store.save_profile({"setup": False, "model": "test/model"})
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(operations, "check_updates", lambda: None)
    events = []
    monkeypatch.setattr(discovery, "connect_repositories", lambda: events.append("picker"))
    monkeypatch.setattr(cli, "serve", lambda no_open: events.append("open"))
    cli.main(["--no-open"])
    store.save_profile({"setup": True})
    cli.main(["--no-open"])
    assert events == ["open", "open"]
