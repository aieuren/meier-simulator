"""Deterministisk policy-kärna för Meier.

Den här modulen är ryggraden i agentmodellen (se ``docs/agent-model.md``).
Den räknar fram ett drag ur speltillståndet och agentens parametrar. Den är
medvetet **deterministisk och frikopplad från LLM:en**: LLM:en får föreslå och
motivera, men draget som spelas ägs av policyn. Annars går det inte att avgöra
om en profil vinner på grund av sina parametrar, på promptformuleringen eller
på slumpen.

Tre delar:

- ``OUTCOME_P`` – exakt sannolikhet för vart och ett av de 21 utfallen, härledd
  ur ``rules.FACE_WEIGHTS`` (de avlånga tärningarna). Ingen skattning.
- ``CallOdds`` – förväntade liv vid en syn på ett givet bud, plus tröskeln ``q*``
  där en syn går jämnt upp.
- ``BasePolicy`` – en stark, fryst, icke-läsande referensagent som maximerar
  förväntad överlevnad. Den har en enda global tro ``q`` på motståndarens
  bluffbenägenhet och läser aldrig enskilda motståndare.

Meier har inga poäng per steg — bara liv. Målet är därför förväntade kvarvarande
liv, inte "poäng nästa steg".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from . import rules

# -- Exakt sannolikhetsmodell ------------------------------------------------

def _outcome_probabilities() -> dict[int, float]:
    """Exakt P(utfall) för alla 21 utfall, ur tärningarnas vikter."""
    weights = rules.FACE_WEIGHTS
    total = sum(weights) ** 2
    probs = {value: 0.0 for value in rules.RANKING}
    for a, b in product(range(1, 7), repeat=2):
        probs[rules.read_dice(a, b)] += weights[a - 1] * weights[b - 1] / total
    return probs


#: P(utfall) för varje giltigt värde. Summan är 1,0.
OUTCOME_P: dict[int, float] = _outcome_probabilities()


def outcome_probability(value: int) -> float:
    """Sannolikheten att ett slag visar exakt ``value``."""
    return OUTCOME_P[value]


def at_least_probability(value: int) -> float:
    """P(tärningarna visar ``value`` eller högre)."""
    return sum(p for v, p in OUTCOME_P.items() if rules.compare(v, value) >= 0)


def lives_lost(bid: int, shown: int) -> int:
    """Antal liv som förloras vid en syn. Meier kostar dubbelt, på båda sidor."""
    return 2 if (rules.is_meier(bid) or rules.is_meier(shown)) else 1


def _strength(value: int) -> float:
    """Hur högt ett värde är i rangordningen, 0 (31) till 1 (Meier).

    Proxy för hur attraktivt ett bud är att syna: ju högre bud, desto billigare
    är synen och desto oftare syns den (empiriskt: Meier 46 %, 66 46 %, låga bud
    aldrig).
    """
    return 1.0 - rules.rank(value) / (len(rules.RANKING) - 1)


@dataclass(frozen=True)
class CallOdds:
    """Vad en syn på budet ``bid`` är värd, och när den går jämnt upp.

    ``l_win``  – förväntade liv som *hållaren* förlorar, givet att synaren vinner
                 (tärningarna visar lägre än budet).
    ``l_lose`` – förväntade liv som *synaren* förlorar, givet att synaren förlorar
                 (tärningarna visar budet eller högre).
    ``q_star`` – minsta bluff-sannolikhet där synen ger positivt livsöverskott.
    """

    bid: int
    p_win: float  # P(tärningarna visar lägre än budet) — synaren vinner
    l_win: float
    l_lose: float

    @property
    def q_star(self) -> float:
        denom = self.l_win + self.l_lose
        return self.l_lose / denom if denom else 1.0

    def ev_call(self, q: float) -> float:
        """Förväntat livsöverskott för synaren, givet blufftron ``q``.

        Positivt värde betyder att synen är lönsam i förväntade liv.
        """
        return q * self.l_win - (1.0 - q) * self.l_lose

    def call_is_profitable(self, q: float) -> bool:
        return self.ev_call(q) > 0.0


def _call_odds(bid: int) -> CallOdds:
    lo = [v for v in rules.RANKING if rules.compare(v, bid) < 0]   # synaren vinner
    hi = [v for v in rules.RANKING if rules.compare(v, bid) >= 0]  # synaren förlorar
    p_lo = sum(OUTCOME_P[v] for v in lo)
    p_hi = sum(OUTCOME_P[v] for v in hi)
    l_win = sum(lives_lost(bid, v) * OUTCOME_P[v] for v in lo) / p_lo if p_lo else 0.0
    l_lose = sum(lives_lost(bid, v) * OUTCOME_P[v] for v in hi) / p_hi if p_hi else 0.0
    return CallOdds(bid=bid, p_win=p_lo, l_win=l_win, l_lose=l_lose)


#: CallOdds för varje giltigt bud. Beräknas en gång.
CALL_ODDS: dict[int, CallOdds] = {value: _call_odds(value) for value in rules.RANKING}


# -- Agentens parametrar -----------------------------------------------------

@dataclass(frozen=True)
class AgentParams:
    """En agents beteendeprofil.

    ``risk``    – hur mycket säkerhet som offras för chansen att vinna mer.
    ``press``   – hur ofta agenten bluffar/höjer och pressar motståndaren.
    ``reading`` – hur mycket motståndarnas tidigare beteende får styra.
    """

    risk: float = 0.5
    press: float = 0.5
    reading: float = 0.0

    def __post_init__(self) -> None:
        for name in ("risk", "press", "reading"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} måste vara mellan 0 och 1, fick {v}")


#: De fyra spelarna och deras egna profiler bor i ``meier/agents/roster.py``.
#: Parametrarna (risk/press/reading) är den enda platsen profilen får bo —
#: inte i ett namn. Se registret för värdena och motiveringen.


# -- Beslut -----------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    """Ett färdigt beslut från policyn.

    ``action`` är en av ``"bud"``, ``"slå"``, ``"syna"``, ``"skicka"`` eller
    ``"titta"``/``"blint"`` (vid tvingad höjning). ``bid`` är satt för bud och slå.
    ``reason`` är en kort maskinell motivering (LLM:en får formulera en rikare).
    """

    action: str
    bid: int | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {"action": self.action, "bid": self.bid, "reason": self.reason}


#: Den typiska bluff-frekvensen i populationen, mätt på **avslöjade** bud
#: (frivilliga väger fullt, blinda halvt). Används som nämnare när en motståndares
#: benägenhet mäts relativt populationen, och som förhandstro innan en spelare
#: avslöjats. Kalibrerad mot en färsk strategisk serie (300 matcher, 0,715).
#:
#: Notera att detta **inte** är samma tal som andelen överbud bland alla synliga
#: bud (0,586). Skillnaden är de tvingade höjningarna: de är mekaniska (~78 %
#: "överbud" för alla) och räknas därför bort ur profilen. Använder man 0,586 som
#: nämnare får varje normal spelare ratio > 1,0 och en läsande agent synar i
#: onödan.
DEFAULT_Q = 0.715

#: Kalibrerad, fryst, **riskjusterad** tro på ``P(synaren vinner | budnivå)``.
#:
#: Detta är kärnan i ``q``-modellen, men **per budnivå**. Ett enda globalt tal
#: räcker inte: sannolikheten att en syn vinner varierar kraftigt med budet,
#: därför att motståndare bjuder över sina tärningar när de är svaga.
#:
#: Tabellen är **inte** den råa sannolikheten ``P(shown < bid)``. Den är medvetet
#: *mer försiktig* än så, och det av två skäl som hänger ihop:
#:
#: 1. **Livsförlusten är asymmetrisk.** Att syna ett lågt bud som 33 vinner ofta
#:    (P ≈ 0,73), men när det går fel kostar det mycket. En rå sannolikhet skulle
#:    därför locka agenten att syna bud som har negativt *livs*överskott.
#: 2. **Synfrekvensen styr inlärningen.** Synar ingen frivilligt blir de enda
#:    avslöjade buden tvingade höjningar — och då finns ingen data att läsa. En
#:    alltför försiktig tabell gör därför *läsningen* värdelös (se avsnitt 6).
#:
#: Tabellen är kalibrerad som en **halvvägs-sammandragning** mellan den
#: riskjusterade försiktiga nivån och den uppmätta sanna sannolikheten (se
#: ``docs/agent-model.md``, avsnitt 5.1). Den punkten ger samtidigt en stark
#: BASE, en stark läsande baslinje och ett **positivt** värde av läsning.
CALL_PRIOR: dict[int, float] = {
    21: 0.544, 11: 0.620, 22: 0.618, 33: 0.499, 44: 0.475, 55: 0.474, 66: 0.482,
    65: 0.535, 64: 0.486, 63: 0.423, 62: 0.438, 61: 0.431, 54: 0.322, 53: 0.283,
    52: 0.326, 51: 0.404, 43: 0.248, 42: 0.293, 41: 0.277, 32: 0.333, 31: 0.000,
}

#: Tröghetströskel för synen: ``inertia = CALL_INERTIA_BASE + CALL_INERTIA_RISK * risk``.
#:
#: En syn som ligger nära break-even är ett lotteri om livet, och i Meier räknas
#: överlevnad, inte vunna rundor. Tröskeln gör agenten konservativ; en högre
#: ``risk`` sänker den och synar mer. Tröskeln är den *andra* hälften av samma
#: avvägning som tabellen: den håller nere marginal-synar som tabellen ensam
#: skulle bjuda in till.
CALL_INERTIA_BASE = 0.10
CALL_INERTIA_RISK = 0.06

#: Golv och lutning för ``P(budet blir synat)``. Högre bud synas oftare. Golvet
#: hindrar att ett lågt bud ser ut att vara gratis att bluffa till.
CALL_FLOOR = 0.10
CALL_SLOPE = 0.40

#: Värde av ett *säkert* bud (bid ≤ visat). Ett sådant bud kan aldrig straffa
#: dig vid en syn — synaren förlorar. ``SAFE_POSITION`` gör ett högre säkert bud
#: (närmare det visade) mer värt, eftersom det är svårare att slå över.
SAFE_BASE = 0.10
SAFE_POSITION = 0.25


@dataclass
class BasePolicy:
    """Stark, fryst, icke-läsande referensagent.

    Den maximerar förväntad överlevnad och har en enda global tro ``q`` på
    motståndarens bluffbenägenhet. Den läser aldrig enskilda motståndare.
    """

    params: AgentParams = field(default_factory=lambda: AgentParams(0.5, 0.5, 0.0))
    q: float = DEFAULT_Q

    # -- Beslut 3: syna eller skicka ------------------------------------
    def decide_call(
        self, bid: int, *, lives: int = 3, opponent_q: float | None = None
    ) -> Decision:
        """Ska agenten syna budet ``bid``? Agenten ser inte sina tärningar här.

        ``opponent_q`` är en motståndarspecifik bluffskattning (för läsande
        agenter). Utan den används den **budspecifika** tron ``CALL_PRIOR[bid]``.

        Synen avgörs av det förväntade livsöverskottet, med en liten
        tröghetströskel: att skicka vidare ger noll chans att vinna rundan, så
        en syn som nästan går jämnt upp är värd att ta.

        Den här metoden ser bara två val. Spelaren har tre — se
        :meth:`decide_response`, som även väger in att slå.
        """
        odds = CALL_ODDS[bid]
        q = CALL_PRIOR[bid] if opponent_q is None else opponent_q
        ev = odds.ev_call(q)
        # En syn är bara värd att ta om livsöverskottet är klart positivt. En syn
        # som ligger nära break-even är ett lotteri om livet, och i Meier är det
        # *att överleva* som räknas — inte att vinna enskilda rundor. Tröskeln
        # ``inertia`` gör agenten konservativ, och ``risk`` sänker den.
        inertia = CALL_INERTIA_BASE + CALL_INERTIA_RISK * self.params.risk
        if ev > -inertia:
            return Decision(
                "syna",
                reason=f"P(vinst)={q:.2f}; EV={ev:+.3f} liv > −{inertia:.3f}",
            )
        return Decision(
            "skicka",
            reason=f"P(vinst)={q:.2f}; EV={ev:+.3f} liv < −{inertia:.3f}",
        )

    # -- Beslut 3b: alla tre svar på ett bud ------------------------------
    def decide_response(
        self, bid: int, *, lives: int = 3, opponent_q: float | None = None
    ) -> Decision:
        """Välj mellan att syna, skicka vidare och slå.

        Alla tre värderas som **mitt** förväntade livsöverskott, så att de går
        att jämföra direkt. Det är skillnaden mot :meth:`decide_call`, som bara
        väger synen mot att lägga sig.

        - **Syna** — tärningarna avgör. Värdet är synens EV (samma som i
          :meth:`decide_call`).
        - **Skicka vidare** — budet står kvar men ansvaret flyttas till mig.
          Jag förlorar liv om tärningarna visar lägre än budet; annars förlorar
          nästa spelare som synar. Värdet är därför nollsummespelet ovanför
          budet, viktat med hur ofta budet synas.
        - **Slå** — jag skakar blint och måste bjuda högre. Vilket bud det blir
          avgör :meth:`decide_raise`; det är samma bud som motorn sedan spelar.
          Värdet är hållarvärdet för just det budet.

        Ingen av de tre tvingas fram. ``slå`` väljs bara när det slår båda
        andra, och ``syna`` behåller sin tröghetströskel så att en syn nära
        break-even inte blir ett lotteri om livet.
        """
        odds = CALL_ODDS[bid]
        q = CALL_PRIOR[bid] if opponent_q is None else opponent_q

        call_ev = odds.ev_call(q)
        inertia = CALL_INERTIA_BASE + CALL_INERTIA_RISK * self.params.risk

        hold_ev = self._hold_value(bid)

        options: list[tuple[str, float, str]] = [
            ("syna", call_ev + inertia, f"EV={call_ev:+.3f} liv (tröskel −{inertia:.3f})"),
            ("skicka", hold_ev, f"hållarvärde={hold_ev:+.3f} liv"),
        ]

        shake = self.decide_raise(bid)
        if shake.action == "slå" and shake.bid is not None:
            shake_ev = self._hold_value(shake.bid)
            options.append(
                ("slå", shake_ev, f"slå till {rules.name(shake.bid)}: {shake_ev:+.3f} liv")
            )

        action, _, why = max(options, key=lambda opt: opt[1])
        return Decision(action, bid=None, reason=why)

    def _hold_value(self, bid: int) -> float:
        """Mitt förväntade livsöverskott av att bära budet ``bid``.

        Budet synas med sannolikheten ``p_called``. Blir det synat vinner jag
        om tärningarna visar lägre än budet — då förlorar synaren liv. Annars
        förlorar jag. Blir det inte synat händer ingenting i den här rundan.
        """
        odds = CALL_ODDS[bid]
        p_called = self._p_called(bid)
        win = (1.0 - odds.p_win) * odds.l_lose
        lose = odds.p_win * odds.l_win
        return p_called * (win - lose)

    # -- Beslut 2: slå (ser inte tärningarna) ---------------------------
    def decide_raise(self, bid: int) -> Decision:
        """Vilket bud ska agenten säga när den slår (blint) över ``bid``?

        Eftersom agenten inte ser sina tärningar är den minsta lagliga höjningen
        säkrast (minst chans att tärningarna visar lägre). ``press`` driver budet
        högre för att sätta motståndaren under press.
        """
        higher = rules.higher_options(bid)
        if not higher:
            return Decision("syna", reason="Inget högre bud finns; enda svar är att syna.")
        # higher[0] är högst (Meier), higher[-1] är minsta höjning.
        steps = int(round(self.params.press * (len(higher) - 1)))
        new_bid = higher[-(steps + 1)]
        return Decision("slå", bid=new_bid, reason=f"Slår till {rules.name(new_bid)}.")

    # -- Beslut 1: första budet (ser tärningarna) -----------------------
    def decide_bid(self, shown: int, *, opponent_factor: float = 1.0) -> Decision:
        """Vilket bud ska agenten säga när den sett tärningarna visa ``shown``?

        Att bjuda ``shown`` är **säkert**: blir det synat visar tärningarna minst
        budet, så synaren förlorar. Det är grundbudet.

        Ett bud **över** ``shown`` är en bluff. Den vinner bara om motståndaren
        lägger sig (sannolikhet ``1 − p_called``) och förlorar liv om den synas.
        En bluff lönar sig därför bara när den är *billig att bli synad på* — alltså
        på budnivåer som sällan synas. ``press`` väger vinsten av att lägga sig;
        vid låg press bjuder agenten sanning, vid hög press tar den chansen.

        ``opponent_factor`` är motståndarens **synbenägenhet** relativt det
        normala (1,0 = som folk mest). En motståndare som synar ofta gör varje
        bluff dyrare, och då bluffar agenten mindre. Det är läsningens inverkan
        på budet — skild från ``press``, som är agentens egen benägenhet.
        """
        if rules.is_meier(shown):
            return Decision("bud", bid=shown, reason="Meier — högsta möjliga, bjuder det.")

        best_bluff: int | None = None
        best_gain = 0.0
        for cand in rules.higher_options(shown):  # strikt högre än visat
            p_called = self._p_called(cand, opponent_factor)
            gain = (1.0 - p_called) * self.params.press - p_called * CALL_ODDS[cand].l_lose
            if gain > best_gain:
                best_gain, best_bluff = gain, cand

        if best_bluff is not None:
            return Decision(
                "bud",
                bid=best_bluff,
                reason=(
                    f"Visar {rules.name(shown)}; bluffar {rules.name(best_bluff)} "
                    f"(vinst {best_gain:+.2f} liv)."
                ),
            )
        return Decision(
            "bud",
            bid=shown,
            reason=f"Visar {rules.name(shown)}; bjuder sanning.",
        )

    def _bid_value(self, bid: int, shown: int) -> float:
        """Värdet av att bjuda ``bid`` när tärningarna visar ``shown``.

        Behålls som en enkel, läsbar poängsättning för analys och tester. Det
        faktiska budvalet görs i :meth:`decide_bid`, som jämför sanning mot bästa
        bluff direkt.
        """
        cmp = rules.compare(bid, shown)
        if cmp <= 0:
            return SAFE_BASE + _strength(bid) * SAFE_POSITION
        p_called = self._p_called(bid)
        return (1.0 - p_called) * self.params.press - p_called * CALL_ODDS[bid].l_lose

    def _p_called(self, bid: int, opponent_factor: float = 1.0) -> float:
        """Uppskattad sannolikhet att ett bud blir synat.

        Fryst heuristik, kalibrerad mot empirin: högre bud synas oftare eftersom
        de är billigare att syna (synaren vinner oftare). Låga bud synas sällan
        men aldrig *aldrig* — därför ett golv. Utan golvet ser en bluff till ett
        lågt bud ut att vara gratis, och agenten bluffar ihjäl sig.

        ``opponent_factor`` skalar uppskattningen med motståndarens kända
        synbenägenhet (se :meth:`OpponentTracker.risk_factor`). Den som möter en
        synbenägen motståndare räknar med att bli synad oftare — och bluffar
        därför mindre.
        """
        base = min(1.0, CALL_FLOOR + CALL_SLOPE * _strength(bid))
        return min(1.0, base * opponent_factor)

    # -- Beslut 4: tvingad höjning (titta eller blint) ------------------
    def decide_forced(self, bid: int) -> Decision:
        """Titta på de nya tärningarna eller bjuda blint? Fattas utan att titta."""
        if not rules.higher_options(bid):
            return Decision("syna", reason="Meier är högst; kan inte höja.")
        # En pressande profil bjuder hellre blint (döljer information);
        # en försiktig profil tittar hellre (kan bjuda nära sanningen).
        if self.params.press > self.params.risk:
            return Decision("blint", reason="Pressande profil: bjuder blint.")
        return Decision("titta", reason="Försiktig profil: tittar på tärningarna.")
