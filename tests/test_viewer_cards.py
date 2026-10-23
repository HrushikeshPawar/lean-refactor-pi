import json

from arena.viewer_data import card_payload


def _card(label, actor, version, fields, changed, ts):
    return {"type": "card", "event_id": f"{label}{version}", "ts": ts, "actor_id": actor, "job_id": None if actor == "sol" else actor,
            "label": label, "version": version, "fields": fields, "changed": changed}


def test_card_payload_orders_actors_and_keeps_history(tmp_path):
    rows = [
        {"ts": 1000.0, "kind": "init"},
        _card("job10", "job10", 1, {"focus": "x"}, ["focus"], 1060.0),
        _card("job2", "job2", 1, {"focus": "a"}, ["focus"], 1120.0),
        _card("orchestrator", "sol", 1, {"focus": "f"}, ["focus"], 1180.0),
        _card("orchestrator", "sol", 2, {"best": "n3"}, ["focus", "best"], 1240.0),
    ]
    (tmp_path / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = card_payload(tmp_path)
    assert [a["label"] for a in out["actors"]] == ["orchestrator", "job2", "job10"]
    sol = out["actors"][0]
    assert [v["version"] for v in sol["versions"]] == [1, 2]
    assert sol["latest"]["fields"] == {"best": "n3"} and sol["latest"]["minutes"] == 4.0


def test_card_payload_empty(tmp_path):
    assert card_payload(tmp_path)["actors"] == []
