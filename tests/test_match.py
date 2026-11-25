"""Tester för batchkörning och statistik (utan riktiga LLM-anrop)."""

import json

from meier import match, rules
from meier.agents.base import Role
from meier.agents.player import MeierPlayerAgent


class ScriptedLLM:
    """LLM som svarar enligt ett manus, så att en match blir deterministisk."""

    def __init__(self, claims=None, actions=None):
        self.claims = list(claims or [])
        self.actions = list(actions or [])
        self._claim_i = 0
        self._act_i = 0

    def _next_claim(self, default):
        if self._claim_i < len(self.claims):
            v = self.claims[self._claim_i]
            self._claim_i += 1
            return v
        return default

    def complete(self, system, user, *, json_mode=False):
        if "MÅSTE säga" in user or "utan att titta" in user:
            return '{"claim": %s, "line": "höjer", "reasoning": "t"}' % self._next_claim(52)
        if "DITT VAL" in user:
            act = self.actions[self._act_i] if self._act_i < len(self.actions) else "syna"
            self._act_i += 1
            if act == "slå":
                return (
                    '{"action": "slå", "claim": %s, "line": "slår", "reasoning": "t"}'
                    % self._next_claim(66)
                )
            return '{"action": "%s", "line": "ok", "reasoning": "t"}' % act
        return '{"claim": %s, "line": "säger", "reasoning": "t"}' % self._next_claim(52)


def make_agents(role_keys):
    """Agentfabrik för tester: alla får ett manus som synar direkt."""
    agents = []
    for key in role_keys:
        role = Role(key=key, name=f"Spelare-{key}", description="test", style="spela")
        agents.append(MeierPlayerAgent(role=role, llm=ScriptedLLM(claims=[31], actions=["syna"])))
    return agents


def test_play_match_records_structure(monkeypatch):
    monkeypatch.setattr(match, "_new_agents", make_agents)
    rec = match.play_match(["a", "b", "c"], game=1)
    d = rec.to_dict()

    # Går att serialisera till JSON (kravet för analysfilen).
    json.dumps(d, ensure_ascii=False)

    assert d["game"] == 1
    assert len(d["players"]) == 3
    assert d["winner"] in [p["name"] for p in d["players"]]
    assert d["rounds"] >= 1
    assert set(d["lives"]) == {p["name"] for p in d["players"]}

    # Varje match ska ha minst en syn och en livsrad.
    kinds = {e["kind"] for e in d["events"]}
    assert "roll" in kinds and "action" in kinds and "life" in kinds

    # Alla spelare finns i per-spelar-statistiken.
    for p in d["players"]:
        assert p["name"] in d["player_stats"]


def test_events_carry_analysis_fields(monkeypatch):
    monkeypatch.setattr(match, "_new_agents", make_agents)
    rec = match.play_match(["a", "b"]).to_dict()
    call = next(e for e in rec["events"] if e.get("action") == "syna")
    # Synen ska bära med sig vem som förlorade och livsställningen.
    assert call["caller_loses"] in (True, False)
    assert call["actor_lives"] is not None
    assert call["active_players"] is not None
    assert call["accepted_claim"] is not None


def test_summarize_aggregates_roles(monkeypatch):
    monkeypatch.setattr(match, "_new_agents", make_agents)
    records = [match.play_match(["a", "b"], game=g).to_dict() for g in range(4)]
    stats = match.summarize(records)

    assert stats["games"] == 4
    assert set(stats["roles"]) == {"a", "b"}
    for b in stats["roles"].values():
        assert b["games"] == 4
        assert 0.0 <= b["win_rate"] <= 1.0
        assert 0.0 <= b["bluff_rate"] <= 1.0
        assert 0.0 <= b["unseen_rate"] <= 1.0
        assert b["wins"] <= b["games"]
    # Vinnarna fördelas på rollerna och antalet stämmer.
    assert sum(stats["winner_counts"].values()) == 4


def test_summarize_adds_up_the_models_that_answered():
    """Sammanställningen ska visa modellerna även när loggen lästs från disk."""
    base = {
        "players": [
            {
                "role": "a",
                "name": "A",
                "index": 0,
                "lives_lost": 0,
                "claims": 0,
                "visible_claims": 0,
                "bluffs": 0,
                "unseen_claims": 0,
                "decisions": 0,
                "passes": 0,
                "raises": 0,
                "calls": 0,
                "calls_won": 0,
            }
        ],
        "events": [],
        "player_stats": {},
        "winner_role": "a",
        "winner_name": "A",
        "starter": "A",
        "rounds": 3,
    }
    recs = [
        {**base, "game": 1, "usage": {"models": {"gemini-x": 4}}},
        {**base, "game": 2, "usage": {"models": {"gemini-x": 2, "reserv-y": 3}}},
    ]
    stats = match.summarize(recs)
    assert stats["tokens"]["models"] == {"gemini-x": 6, "reserv-y": 3}


def test_jsonl_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(match, "_new_agents", make_agents)
    records = [match.play_match(["a", "b"], game=g) for g in range(3)]
    path = tmp_path / "m.jsonl"
    n = match.write_jsonl(records, path)
    assert n == 3
    back = match.read_jsonl(path)
    assert len(back) == 3
    assert back[0]["game"] == 0
    # Sammanfattningen ska kunna räknas fram ur den återlästa filen.
    assert match.summarize(back)["games"] == 3


def test_run_matches_numbers_the_games(monkeypatch):
    monkeypatch.setattr(match, "_new_agents", make_agents)
    recs = list(match.run_matches(["a", "b"], 3))
    assert [r.game for r in recs] == [1, 2, 3]


def test_run_matches_parallel_workers(monkeypatch):
    monkeypatch.setattr(match, "_new_agents", make_agents)
    recs = list(match.run_matches(["a", "b"], 4, workers=4))
    # Alla matcher blir klara och får var sitt matchnummer. Ordningen kan
    # variera eftersom de spelas samtidigt.
    assert len(recs) == 4
    assert sorted(r.game for r in recs) == [1, 2, 3, 4]


# -- En kraschad match får inte fälla serien ---------------------------------


def test_progress_reports_each_round(monkeypatch):
    """Rundan ska rapporteras medan matchen spelas, inte bara vid start.

    En match tar minuter. Utan rapporter står statusraden still och ser ut att
    ha fastnat, trots att allt går som det ska.
    """
    monkeypatch.setattr(match, "_new_agents", make_agents)
    seen: list[tuple[int, int]] = []

    def on_match_progress(game, round_no, alive):
        seen.append((game, round_no))

    list(match.run_matches(["a", "b"], 1, on_match_progress=on_match_progress))

    assert seen, "progress ska rapporteras minst en gång per match"
    assert {g for g, _ in seen} == {1}
    # Första rapporten är runda 1, och rundnumret får aldrig gå bakåt.
    assert seen[0][1] == 1
    assert [r for _, r in seen] == sorted(r for _, r in seen)


def test_play_match_calls_on_progress_when_a_round_ends(monkeypatch):
    """on_progress ska anropas från play_match, med runda och antal kvar."""
    monkeypatch.setattr(match, "_new_agents", make_agents)
    seen: list[tuple[int, int]] = []

    match.play_match(
        ["a", "b"], on_progress=lambda r, k: seen.append((r, k))
    )

    assert seen, "on_progress ska anropas"
    assert seen[0][0] == 1
    assert all(1 <= kvar <= 2 for _, kvar in seen)


def test_a_failing_match_does_not_stop_the_series(monkeypatch):
    """Ett LLM-fel i match 2 ska bara kosta match 2, inte hela serien.

    Utan detta förlorade en enda 503:a alla matcher som redan spelats, eftersom
    CLI:t samlade hela serien i minnet innan den skrevs till disk.
    """
    from meier.llm import LLMError

    calls: list[int] = []

    def flaky(role_keys, *, game=1, lives=3, with_llm=True):
        calls.append(game)
        if game == 2:
            raise LLMError("Modellen är överbelastad (503)")
        return match.GameRecord(
            game=game,
            provider="test",
            model="test",
            players=[],
            order=[],
            starter="",
            winner="",
            winner_role="",
            rounds=0,
            lives={},
            elimination_order=[],
            events=[],
            player_stats={},
        )

    monkeypatch.setattr(match, "play_match", flaky)
    recs = list(match.run_matches(["a", "b"], 3))

    assert calls == [1, 2, 3], "alla matcher ska försökas"
    assert len(recs) == 3
    failed = [r for r in recs if isinstance(r, match.FailedMatch)]
    assert len(failed) == 1
    assert failed[0].game == 2
    assert failed[0].kind == "llm"
    assert "503" in failed[0].error


def test_failed_matches_are_written_and_excluded_from_the_summary(tmp_path, monkeypatch):
    """Bortfallet ska synas i filen men inte räknas som en spelad match."""
    from meier.llm import LLMError

    def flaky(role_keys, *, game=1, lives=3, with_llm=True):
        raise LLMError("överbelastad")

    monkeypatch.setattr(match, "play_match", flaky)
    recs = list(match.run_matches(["a", "b"], 2))

    path = tmp_path / "serie.jsonl"
    assert match.write_jsonl(recs, path) == 2
    back = match.read_jsonl(path)
    assert all(r.get("failed") for r in back)

    stats = match.summarize(back)
    assert stats["games"] == 0, "inget spelades"
    assert stats["attempted"] == 2
    assert stats["failed"]["count"] == 2
    assert stats["failed"]["games"] == [1, 2]
    assert stats["failed"]["reasons"] == {"llm": 2}


def test_an_unexpected_error_is_not_mistaken_for_an_llm_error(monkeypatch):
    def broken(role_keys, *, game=1, lives=3, with_llm=True):
        raise ZeroDivisionError("bugg")

    monkeypatch.setattr(match, "play_match", broken)
    recs = list(match.run_matches(["a", "b"], 1))
    assert recs[0].kind == "oväntat"
    assert "ZeroDivisionError" in recs[0].error


# -- Gamla loggar (skrivna före namnbytet bid -> claim) ----------------------


def _gammal_post() -> dict:
    """En post i det gamla formatet: bid, bud och bids."""
    return {
        "players": [{"index": 0, "role": "axel", "name": "A"}],
        "starter": 0,
        "winner": "A",
        "winner_role": "axel",
        "rounds": 1,
        "events": [
            {
                "kind": "action",
                "action": "bud",
                "bid": 52,
                "bid_name": "52",
                "accepted_bid": None,
                "previous_bid": None,
            }
        ],
        "player_stats": {
            "A": {"bids": 3, "blinds": 1, "bluffs": 1, "truths": 2, "decisions": 2,
                  "raises": 0, "passes": 1, "calls": 1, "calls_won": 1,
                  "calls_lost": 0, "lives_lost": 0, "eliminated": False},
        },
    }


def test_gammal_logg_lases_som_ny(tmp_path):
    """En logg med bid/bud ska gå att läsa utan att filen skrivs om."""
    path = tmp_path / "gammal.jsonl"
    path.write_text(json.dumps(_gammal_post(), ensure_ascii=False) + "\n", encoding="utf-8")

    post = match.read_jsonl(path)[0]

    event = post["events"][0]
    assert event["action"] == "påstå"
    assert event["claim"] == 52
    assert "bid" not in event and "bid_name" not in event
    stat = post["player_stats"]["A"]
    assert stat["claims"] == 3
    assert stat["unseen"] == 1
    assert "bids" not in stat


def test_gammal_logg_kan_sammanfattas(tmp_path):
    """Summeringen ska räkna gamla loggar som nya, inte tappa dem."""
    path = tmp_path / "gammal.jsonl"
    path.write_text(json.dumps(_gammal_post(), ensure_ascii=False) + "\n", encoding="utf-8")

    stats = match.summarize(match.read_jsonl(path))

    assert stats["games"] == 1
    assert stats["roles"]["axel"]["claims"] == 3
