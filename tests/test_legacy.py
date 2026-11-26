"""Vaktar att loggar skrivna före namnbytet fortfarande går att analysera.

Loggfilerna på disk är historik och skrivs aldrig om. Tre format finns:

1. Före namnbytet: ``bid``/``bid_name``/``blind`` i händelserna,
   ``player_stats`` med ``bids``/``blinds``, handlingen ``"bud"`` och
   rollnamn som "Ärlig-Adolf". Saknar ``format``.
2. Efter namnbytet men före protokollversionen: ``claim``/``unseen``, men
   fortfarande ``player_stats`` som dict. Saknar ``format``.
3. Nuvarande: ``format: 2`` och spelarnas förmågor i ``players``.

Format 1 och 2 tappades när formatkravet infördes, och analysen kraschade på
dem med ``KeyError: 'claims'``. De här testerna håller alla tre läsbara.
"""

import json

from meier import analysis, legacy, match


def _old_pre_rename() -> dict:
    """En post i det allra äldsta formatet, med gamla nyckelnamn."""
    return {
        "game": 1,
        "players": [{"index": 0, "role": "arling", "name": "Ärlig-Adolf"},
                    {"index": 1, "role": "axel", "name": "Axel"}],
        "winner": "Axel",
        "winner_role": "axel",
        "events": [{"kind": "roll", "action": "bud", "bid": 52, "bid_name": "52",
                    "blind": False}],
        "player_stats": {
            "Ärlig-Adolf": {"bids": 1, "blinds": 0, "bluffs": 0, "truths": 1,
                            "decisions": 0, "raises": 0, "passes": 0, "calls": 0,
                            "calls_won": 0, "calls_lost": 0, "lives_lost": 1,
                            "eliminated": True},
            "Axel": {"bids": 0, "blinds": 0, "bluffs": 0, "truths": 0,
                     "decisions": 1, "raises": 0, "passes": 0, "calls": 1,
                     "calls_won": 1, "calls_lost": 0, "lives_lost": 0,
                     "eliminated": False},
        },
    }


def test_upgrade_record_renames_old_keys():
    out = legacy.upgrade_record(_old_pre_rename())
    assert "format" not in out
    event = out["events"][0]
    assert event["action"] == "påstå"
    assert event["claim"] == 52 and event["claim_name"] == "52"
    assert event["unseen"] is False
    assert "bid" not in event and "blind" not in event
    assert out["player_stats"]["Axel"]["claims"] == 0
    assert out["player_stats"]["Axel"]["unseen"] == 0


def test_upgrade_record_is_idempotent():
    once = legacy.upgrade_record(_old_pre_rename())
    twice = legacy.upgrade_record(once)
    assert once == twice


def test_old_pre_rename_log_survives_analysis():
    text = json.dumps(_old_pre_rename(), ensure_ascii=False) + "\n"
    records, skipped = analysis.parse_jsonl_text(text)
    assert skipped == 0 and len(records) == 1
    digest = analysis.build_digest(records)
    assert digest["games"] == 1
    assert digest["roles"]
    assert digest["legacy_games"] == 1


def test_read_jsonl_upgrades_old_file(tmp_path):
    path = tmp_path / "gammal.jsonl"
    path.write_text(json.dumps(_old_pre_rename(), ensure_ascii=False) + "\n",
                    encoding="utf-8")
    raw = match.read_jsonl(path)
    assert raw[0]["events"][0]["action"] == "påstå"
    assert "bids" not in raw[0]["player_stats"]["Axel"]
    # Filen på disk är orörd.
    on_disk = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert on_disk["events"][0]["action"] == "bud"


def test_summarize_does_not_crash_on_old_stats():
    """Regressionsvakt: gamla ``player_stats`` gav ``KeyError: 'claims'``."""
    text = json.dumps(_old_pre_rename(), ensure_ascii=False) + "\n"
    records, _ = analysis.parse_jsonl_text(text)
    summary = match.summarize(records)
    assert summary["games"] == 1
    # Rollerna får siffror, inte krasch.
    for bucket in summary["roles"].values():
        assert "claims" in bucket
