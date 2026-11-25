"""Integrationstester för den strategiska agenten kopplad till motorn.

Dessa tester fångar de fel som faktiskt uppstod under utvecklingen och som en
enhetstestning av policyn aldrig hade hittat:

- matcher som aldrig tog slut (livelock vid Meier när ingen synade),
- motståndarmodellen som inte matades av motorn,
- den läsande agenten som blev för passiv och därför aldrig synade.

De täcker också att registret (Axel + Berit/Cecilia/David) spelar en hel match
och att Axel är den LLM-fria referensen.
"""

import pytest

from meier.agents.base import Role
from meier.agents.roster import ROSTER, make_players
from meier.agents.strategic import StrategicAgent
from meier.opponents import OpponentTracker
from meier.policy import AgentParams
from meier.session import Session


def make(name: str, params: AgentParams, tracker: OpponentTracker):
    role = Role(key=name, name=name, description="", style="")
    return StrategicAgent(role, params, tracker=tracker)


def play(names: list[str], lives: int = 3):
    """Spela en match med registrets profiler och en delad motståndarmodell."""
    tracker = OpponentTracker()
    players = [make(n, ROSTER[n].params, tracker) for n in names]
    session = Session.new(players, lives=lives)
    session.tracker = tracker
    session.play_to_end()
    return session, tracker


def test_full_match_terminates():
    session, _ = play(["axel", "berit", "cecilia", "david"])
    assert session.finished
    assert session._winner() is not None


@pytest.mark.parametrize("run", range(20))
def test_matches_always_terminate(run):
    # Livelock-buggen: utan Meier-regeln fastnade matcherna i tusentals rundor.
    session, _ = play(["axel", "berit", "cecilia", "david"])
    assert session.finished
    assert session.round < 200


def test_shaking_is_a_real_choice_in_matches():
    """``slå`` ska kunna spelas i en hel match, inte bara finnas i koden.

    En lagpressprofil väljer det minsta lagliga påståendet, och då är hållarvärdet
    bättre än att skicka vidare. Över flera matcher ska ``slå`` därför dyka upp
    i loggen — annars är det tredje valet död kod igen.

    En enskild match kan sakna ``slå`` beroende på vem som börjar, så svepet går
    över flera matcher.
    """
    calm = AgentParams(unpredictability=0.0, reading=0.0)
    actions: set[str] = set()
    for _ in range(10):
        tracker = OpponentTracker()
        players = [make(n, calm, tracker) for n in ("axel", "berit", "cecilia", "david", "elsa")]
        session = Session.new(players, lives=3)
        session.tracker = tracker
        session.play_to_end()
        assert session.finished
        actions |= {e.action for e in session.log if e.kind == "action"}

    assert "slå" in actions


def test_every_action_in_log_is_legal():
    session, _ = play(["axel", "berit", "cecilia", "david"])
    for entry in session.log:
        if entry.kind != "action":
            continue
        if entry.action in {"påstå", "höja", "slå"}:
            assert entry.claim is not None


def test_tracker_receives_engine_events():
    session, tracker = play(["axel", "berit", "cecilia", "david"])
    assert tracker.stats, "motståndarmodellen fick inga händelser"
    total = sum(s.decisions for s in tracker.stats.values())
    assert total > 0, "inga beslut spårades"


def test_tracker_sees_bluffs_only_after_reveal():
    # Varje avslöjat påstående måste ha skett vid en syn, aldrig i förväg.
    session, tracker = play(["axel", "berit", "cecilia", "david"])
    calls = sum(1 for e in session.log if e.kind == "action" and e.action == "syna")
    revealed = sum(s.revealed for s in tracker.stats.values())
    assert revealed <= calls


def test_a_reading_agent_still_calls():
    # Den läsande agenten fick EV djupt negativ mot en "ärlig" motståndare och
    # synade aldrig — matchen fastnade. Den ska fortfarande svara på påståenden.
    session, _ = play(["cecilia", "berit"])
    calls = sum(1 for e in session.log if e.kind == "action" and e.action == "syna")
    assert calls > 0


def test_no_agent_passes_forever():
    # Ingen agent får skicka vidare ett Meier-påstående: det är bevisbart sämre.
    session, _ = play(["axel", "berit", "cecilia", "david"])
    for entry in session.log:
        if entry.kind == "action" and entry.action == "skicka":
            assert entry.claim != 21, "Meier skickades vidare"


def test_base_model_uses_no_llm_and_no_reading():
    """Axel är referensen: ingen språkmodell, ingen läsning.

    Däremot krävs inte att hans drag är reproducerbara ner på slumpnivå —
    ``unpredictability`` får variera mellan körningar.
    """
    from meier.agents.roster import make_player

    axel = make_player("axel")
    assert axel.llm is None
    assert axel.tracker is None
    assert axel.params.reading == 0.0


def test_reading_changes_the_prior():
    # Läsning ska göra något: en läsande agent ska bedöma en känd bluffare
    # annorlunda än en känd ärlig spelare, givet samma historik.
    tracker = OpponentTracker()
    for _ in range(20):
        tracker.observe_claim("bluffare", unseen=False)
        tracker.reveal("bluffare", was_bluff=True)
        tracker.observe_claim("ärlig", unseen=False)
        tracker.reveal("ärlig", was_bluff=False)

    reader = make("reader", AgentParams(reading=1.0), tracker)
    unseen = make("unseen", AgentParams(reading=0.0), tracker)

    assert tracker.bluff_ratio("bluffare") > tracker.bluff_ratio("ärlig")
    # En agent utan läsning faller tillbaka på populationen (inget omdöme).
    assert unseen._opponent_prior(61, "bluffare") is None
    # Den läsande agenten tror mer på ett högt påstående från en känd bluffare än
    # från en känd ärlig spelare.
    assert reader._opponent_prior(61, "bluffare") > reader._opponent_prior(61, "ärlig")


def test_make_players_shares_one_tracker_among_readers():
    players, tracker = make_players(["axel", "berit", "cecilia", "david", "elsa"])
    by_key = {p.role.key: p for p in players}
    # Axel läser inget: ingen tracker.
    assert by_key["axel"].tracker is None
    # Alla läsande spelare delar samma tracker.
    readers = [p for p in players if p.params.reading > 0.0]
    assert readers, "minst en spelare ska läsa"
    assert all(p.tracker is tracker for p in readers)
    # Axel får aldrig en LLM-klient.
    assert by_key["axel"].llm is None


def test_reader_profile_is_used_when_answering_a_claim():
    # En läsande agent ska bygga en motståndarprofil ur offentligt spel och
    # låta den styra synbeslutet — utan LLM via sekreterarens aritmetik.
    tracker = OpponentTracker()
    for _ in range(8):
        tracker.observe_claim("bluffare", unseen=False)
        tracker.reveal("bluffare", was_bluff=True)
    reader = make("cecilia", ROSTER["cecilia"].params, tracker)
    decision = reader.decide(61, opponent="bluffare")
    assert "bluffare" in reader.profiles
    assert reader.profiles["bluffare"].bluff_tendency > 0.5
    assert "bild av bluffare" in decision.reasoning


def test_non_reader_never_builds_a_profile():
    # Axel läser ingen: ingen profil, ingen justering av tron.
    tracker = OpponentTracker()
    for _ in range(8):
        tracker.reveal("bluffare", was_bluff=True)
    axel = make("axel", ROSTER["axel"].params, tracker)
    assert axel.opponent_profile("bluffare") is None
    assert axel._opponent_prior(61, "bluffare") is None
    assert axel.profiles == {}


class _TalkingLLM:
    """LLM som försöker lägga ord i spelarens mun.

    Den svarar med både draget och en egen replik, för att bevisa att repliken
    aldrig kommer från modellen.
    """

    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def complete(self, system, user, *, json_mode=False):
        import json

        self.prompts.append(user)
        return json.dumps(self.payload)


def test_line_is_built_locally_never_from_the_model():
    llm = _TalkingLLM({"claim": 54, "line": "MITT EGET PÅSTÅENDE", "reasoning": "motiv"})
    agent = make("cecilia", ROSTER["cecilia"].params, OpponentTracker())
    agent.llm = llm
    ann = agent.announce((5, 2))
    assert ann.claim == 54
    assert ann.line == "Jag säger 54."
    assert "MITT EGET PÅSTÅENDE" not in ann.line


def test_no_prompt_asks_the_model_for_a_reply():
    llm = _TalkingLLM({"claim": 54, "action": "skicka", "unseen": False, "reasoning": "motiv"})
    agent = make("cecilia", ROSTER["cecilia"].params, OpponentTracker())
    agent.llm = llm
    agent.announce((5, 2))
    agent.decide(52)
    agent.announce_forced((5, 2), previous_claim=52)
    assert llm.prompts
    for prompt in llm.prompts:
        assert '"line"' not in prompt


def test_forced_choice_line_is_local_but_reasoning_is_kept():
    llm = _TalkingLLM({"claim": 54, "unseen": True, "reasoning": "kör på känsla"})
    agent = make("cecilia", ROSTER["cecilia"].params, OpponentTracker())
    agent.llm = llm
    ann = agent.announce_forced((5, 2), previous_claim=52)
    assert ann.choice_line == "Jag påstår utan att titta."
    assert ann.choice_reasoning == "kör på känsla"


def test_player_count_is_free():
    """Maskinen ska spela med det antal spelare användaren väljer."""
    from meier.match import play_match

    for roles in (
        ["axel", "cecilia"],
        ["axel", "berit", "elsa"],
        ["axel", "berit", "cecilia", "david", "elsa"],
    ):
        rec = play_match(roles, with_llm=False)
        played = rec.to_dict()["players"]
        assert len(played) == len(roles)
        assert [p["role"] for p in played] == roles
        assert rec.winner in {p["name"] for p in played}


def test_claim_prompt_marks_each_legal_claim_as_higher_or_lower():
    """Prompten ska säga vilka påståenden som är högre respektive lägre.

    Utan märkningen hände det att modellen kallade ett högre påstående för
    "lägre" i motiveringen, eftersom den inte höll Meiers ordning i huvudet.
    Då pekade draget och motiveringen åt olika håll.
    """
    agent = make("elsa", ROSTER["elsa"].params, OpponentTracker())
    context = agent._claim_context((2, 5), 52, None, [61, 52, 51], None)

    assert "61 (högre, alltså bluff)" in context
    assert "52 (exakt dina tärningar)" in context
    assert "51 (lägre, alltså sant men svagare)" in context


def test_rules_text_says_pairs_beat_singles():
    """Modellen trodde att bara Meier låg över 66 och tittade därför i onödan.

    En platt rangordning utan förklaring läses som talordning. Reglerna måste
    säga att par slår singlar och att sex påståenden ligger över 66.
    """
    from meier import rules
    from meier.agents.strategic import _RULES

    text = _RULES.format(rang=", ".join(rules.name(v) for v in rules.RANKING))

    assert "Ordningen är inte talordning" in text
    assert "Par slår singlar" in text
    assert "55 högre än 66" in text
    assert "44 högre än 65" in text
    assert "66 är bara sjua" in text
    assert "31 är lägst" in text
    assert [rules.name(v) for v in rules.higher_options(66)] == [
        "21 – Meier", "11", "22", "33", "44", "55"
    ]


def test_shake_context_lists_the_legal_raises():
    """Den som slår ska inte tro att den måste ha Meier för att få säga något.

    Över 66 finns sex lagliga påståenden. Prompten ska räkna upp dem, så att
    valet att titta handlar om information och inte om laglighet.
    """
    agent = make("david", ROSTER["david"].params, OpponentTracker())
    context = agent._shake_context(66, opponent=None)

    assert "6 lagliga påståenden" in context
    for name in ("55", "44", "33", "22", "11", "21 – Meier"):
        assert name in context
    assert "inte ett krav" in context


def test_unseen_context_says_low_claims_are_easy_to_raise_over():
    """Ett lågt påstående är lätt att slå över. 31 ger 94 %, 11 bara 6 %."""
    from meier import rules

    agent = make("david", ROSTER["david"].params, OpponentTracker())
    context = agent._unseen_context(31, [41, 32], opponent=None)

    assert "lätt för nästa spelare att slå över" in context
    assert "svårare för nästa spelare att slå över" not in context

    rolls = [rules.read_dice(a, b) for a in range(1, 7) for b in range(1, 7)]
    assert sum(1 for r in rolls if rules.is_higher(r, 31)) > sum(
        1 for r in rolls if rules.is_higher(r, 11)
    )
