"""Tester för batchkörning och statistik (utan riktiga LLM-anrop)."""

import json

from meier import analysis, match, rules
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
    # Orsaken måste följa med ut, inte bara typen. Kvotbrist och nätverksfel
    # kräver helt olika åtgärder.
    assert stats["failed"]["messages"] == ["LLMError: överbelastad"]


def test_failed_messages_are_deduplicated_and_capped(monkeypatch):
    """Samma fel två gånger ska bara visas en gång, och listan ska vara kort."""
    recs = [
        {"failed": True, "kind": "llm", "error": "LLMError: kvoten är slut"},
        {"failed": True, "kind": "llm", "error": "LLMError: kvoten är slut"},
        {"failed": True, "kind": "llm", "error": "LLMError: nätverket svarar inte"},
        {"failed": True, "kind": "llm", "error": "LLMError: modellen är överbelastad"},
        {"failed": True, "kind": "llm", "error": "LLMError: ett fjärde fel"},
    ]
    stats = match.summarize(recs)
    assert stats["failed"]["count"] == 5
    assert stats["failed"]["messages"] == [
        "LLMError: kvoten är slut",
        "LLMError: nätverket svarar inte",
        "LLMError: modellen är överbelastad",
    ]


def test_failed_messages_skip_records_without_error():
    stats = match.summarize([{"failed": True, "kind": "okänt"}])
    assert stats["failed"]["count"] == 1
    assert stats["failed"]["messages"] == []


def test_an_unexpected_error_is_not_mistaken_for_an_llm_error(monkeypatch):
    def broken(role_keys, *, game=1, lives=3, with_llm=True):
        raise ZeroDivisionError("bugg")

    monkeypatch.setattr(match, "play_match", broken)
    recs = list(match.run_matches(["a", "b"], 1))
    assert recs[0].kind == "oväntat"
    assert "ZeroDivisionError" in recs[0].error


# -- Gamla loggar (skrivna före namnbytet bid -> claim) ----------------------


def test_logg_utan_format_lases_som_aldre_logg(tmp_path):
    """En post utan ``format`` är en äldre logg och ska läsas in, inte kastas.

    Filerna på disk skrivs inte om: de är historik. Händelserna och statistiken
    i en äldre post är fullt läsbara, så posten behålls med ``format`` 0.
    Flaggan gör att en blandad serie syns i sammanställningen i stället för att
    gamla matcher tyst försvinner ur underlaget.
    """
    path = tmp_path / "gammal.jsonl"
    post = {
        "players": [{"index": 0, "role": "axel", "name": "A"}],
        "winner_role": "axel",
        "events": [],
        "player_stats": {},
    }
    path.write_text(json.dumps(post, ensure_ascii=False) + "\n", encoding="utf-8")

    raw = match.read_jsonl(path)
    assert "format" not in raw[0]

    text = path.read_text(encoding="utf-8")
    records, skipped = analysis.parse_jsonl_text(text)
    assert skipped == 0
    assert len(records) == 1
    assert records[0]["format"] == 0

    digest = analysis.build_digest(records)
    assert digest["legacy_games"] == 1
    assert digest["formats"] == {0: 1}
    # Originalposten på disk ska vara orörd.
    assert "format" not in json.loads(text.splitlines()[0])


# -- Protokollet bär spelarnas förmågor -------------------------------------


def test_record_carries_player_params(monkeypatch):
    """Protokollet ska räcka för att säga vilka förmågor som spelade."""
    monkeypatch.setattr(match, "_new_agents", lambda keys: match._new_agents_no_llm(keys))
    d = match.play_match(["axel", "berit"], game=1).to_dict()

    assert d["format"] == match.PROTOCOL_FORMAT
    assert d["lives_per_player"] == 3
    for p in d["players"]:
        assert set(p["params"]) == {
            "caution",
            "statistics",
            "unpredictability",
            "reading",
        }
        assert p["lives_at_start"] == 3


def test_record_marks_rule_player_without_llm(monkeypatch):
    """En regelspelare ska gå att skilja från en LLM-spelare."""
    monkeypatch.setattr(match, "_new_agents", lambda keys: match._new_agents_no_llm(keys))
    d = match.play_match(["axel", "berit"], game=1).to_dict()
    axel = next(p for p in d["players"] if p["role"] == "axel")
    assert axel["uses_llm"] is False
    assert axel["params"]["reading"] == 0.0


# -- Spelsätt: vad som faktiskt lönar sig -----------------------------------


def _rec(events, winner_role="a", players=(("a", "A"), ("b", "B"))):
    """En minimal matchpost med givna händelser."""
    return {
        "format": match.PROTOCOL_FORMAT,
        "game": 1,
        "winner_role": winner_role,
        "winner": "A" if winner_role == "a" else "B",
        "starter": "A",
        "rounds": 1,
        "players": [
            {"role": r, "name": n, "params": {"caution": 0.5}} for r, n in players
        ],
        "events": list(events),
        "player_stats": {},
        "lives": {},
        "lives_per_player": 3,
    }


def test_tactics_measures_raise_steps():
    """Ett kliv mäts i steg i ordningen, inte i talens skillnad."""
    rec = _rec(
        [
            {"action": "påstå", "player_name": "A", "claim": 52,
             "shown": 52, "truth": True},
            {"action": "slå", "player_name": "B", "claim": 62,
             "shown": 62, "truth": True, "accepted_claim": 52},
        ]
    )
    t = match.summarize([rec])["tactics"]
    # 52 har rang 14 och 62 rang 10: fyra steg i stegen, inte i talen.
    assert t["b"]["raise_steps"] == 4.0
    assert t["b"]["raises"] == 1
    assert t["a"]["raises"] == 0


def test_tactics_counts_understated_claims():
    """Att säga lägre än tärningarna ska synas som ett eget mått."""
    rec = _rec(
        [{"action": "påstå", "player_name": "A", "claim": 52,
          "shown": 66, "truth": True}]
    )
    t = match.summarize([rec])["tactics"]
    assert t["a"]["understate_share"] == 1.0
    assert t["a"]["understate_margin"] > 0
    assert t["a"]["bluffs"] == 0


def test_call_precision_uses_dice_not_truth_flag():
    """En synrad har alltid truth=False, så lögnen måste räknas ur tärningarna."""
    lie = _rec(
        [
            {"action": "påstå", "player_name": "A", "claim": 52,
             "shown": 31, "truth": False},
            {"action": "syna", "player_name": "B", "accepted_claim": 52,
             "claim": 52, "shown": 31, "truth": False, "holder_name": "A"},
        ]
    )
    honest = _rec(
        [
            {"action": "påstå", "player_name": "A", "claim": 52,
             "shown": 52, "truth": True},
            {"action": "syna", "player_name": "B", "accepted_claim": 52,
             "claim": 52, "shown": 52, "truth": False, "holder_name": "A"},
        ]
    )

    t_lie = match.summarize([lie])["tactics"]
    assert t_lie["b"]["call_precision"] == 1.0
    assert t_lie["a"]["lies_revealed"] == 1
    assert t_lie["a"]["claims_upheld"] == 0.0

    t_honest = match.summarize([honest])["tactics"]
    assert t_honest["b"]["call_precision"] == 0.0
    assert t_honest["a"]["claims_upheld"] == 1.0


def test_tactics_split_by_match_outcome():
    """Spelsättet ska gå att jämföra mellan vunna och förlorade matcher."""
    won = _rec(
        [{"action": "påstå", "player_name": "A", "claim": 52,
          "shown": 52, "truth": True}],
        winner_role="a",
    )
    lost = _rec(
        [{"action": "påstå", "player_name": "A", "claim": 52,
          "shown": 52, "truth": True}],
        winner_role="b",
    )
    split = match.summarize([won, lost])["tactics_by_outcome"]
    assert set(split) == {"vann", "förlorade"}
    assert split["vann"]["claims"] == 1
    assert split["förlorade"]["claims"] == 1


def test_roll_row_is_not_a_claim():
    """Tärningsraden (kind "roll") bär inget bud och ska inte räknas som påstående."""
    rec = _rec(
        [
            {"kind": "roll", "action": "slag", "player_name": "A",
             "dice": (3, 4), "shown": 43, "claim": None},
            {"kind": "roll", "action": "påstå", "player_name": "A",
             "dice": (3, 4), "shown": 43, "claim": None},
            {"action": "påstå", "player_name": "A", "claim": 43,
             "shown": 43, "truth": True},
        ]
    )
    t = match.summarize([rec])["tactics"]
    assert t["a"]["claims"] == 1


def test_calls_per_claim_normalises_call_count():
    """Antal synar ska gå att jämföra även när spelarna spelar olika många drag."""
    one = _rec(
        [
            {"action": "påstå", "player_name": "A", "claim": 31,
             "shown": 31, "truth": True},
            {"action": "syna", "player_name": "B", "accepted_claim": 31,
             "claim": 31, "shown": 31, "truth": False, "holder_name": "A"},
        ]
    )
    t = match.summarize([one])["tactics"]
    assert t["b"]["calls"] == 1
    assert t["b"]["calls_per_claim"] == 1.0
    # En spelare utan påståenden ska få 0, inte division med noll.
    assert t["a"]["calls_per_claim"] == 0.0


def test_summary_setup_reports_abilities():
    """Uppsättningen ska visa förmågorna och om de var stabila i serien."""
    rec = _rec([])
    summary = match.summarize([rec])
    assert summary["setup"]["player_count"] == 2
    assert summary["setup"]["lives_per_player"] == [3]
    assert summary["setup"]["stable"] is True
    # Bara en förmåga loggad, så nivågrupperingen ska finnas för den.
    assert "caution" in summary["abilities"]
