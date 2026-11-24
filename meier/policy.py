"""Regelstyrd policy-kärna för Meier.

Den här modulen är ryggraden i agentmodellen (se ``docs/agent-model.md``).
Den räknar fram ett drag ur speltillståndet och agentens parametrar. Den är
medvetet **frikopplad från LLM:en**: LLM:en får föreslå och motivera, men
draget som spelas ägs av policyn. Annars går det inte att avgöra om en profil
vinner på grund av sina parametrar, på promptformuleringen eller på slumpen.
Slumpen i sig är liten och styrs av ``unpredictability``.

Tre delar:

- ``OUTCOME_P`` – exakt sannolikhet för vart och ett av de 21 utfallen, härledd
  ur ``rules.FACE_WEIGHTS`` (de avlånga tärningarna). Ingen skattning.
- ``CallOdds`` – förväntade liv vid en syn på ett givet påstående, plus tröskeln ``q*``
  där en syn går jämnt upp.
- ``BasePolicy`` – en stark, fryst, icke-läsande referensagent som maximerar
  förväntad överlevnad. Den har en enda global tro ``q`` på motståndarens
  bluffbenägenhet och läser aldrig enskilda motståndare.

Meier har inga poäng per steg — bara liv. Målet är därför förväntade kvarvarande
liv, inte "poäng nästa steg".
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from itertools import product

from . import legality, rules

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


def lives_lost(claim: int, shown: int) -> int:
    """Antal liv som förloras vid en syn. Meier kostar dubbelt, på båda sidor."""
    return 2 if (rules.is_meier(claim) or rules.is_meier(shown)) else 1


def _strength(value: int) -> float:
    """Hur högt ett värde är i rangordningen, 0 (31) till 1 (Meier).

    Proxy för hur attraktivt ett påstående är att syna: ju högre påstående, desto billigare
    är synen och desto oftare syns den (empiriskt: Meier 46 %, 66 46 %, låga påståenden
    aldrig).
    """
    return 1.0 - rules.rank(value) / (len(rules.RANKING) - 1)


@dataclass(frozen=True)
class CallOdds:
    """Vad en syn på påståendet ``claim`` är värd, och när den går jämnt upp.

    ``l_win``  – förväntade liv som *hållaren* förlorar, givet att synaren vinner
                 (tärningarna visar lägre än påståendet).
    ``l_lose`` – förväntade liv som *synaren* förlorar, givet att synaren förlorar
                 (tärningarna visar påståendet eller högre).
    ``q_star`` – minsta bluff-sannolikhet där synen ger positivt livsöverskott.
    """

    claim: int
    p_win: float  # P(tärningarna visar lägre än påståendet) — synaren vinner
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


def _call_odds(claim: int) -> CallOdds:
    lo = [v for v in rules.RANKING if rules.compare(v, claim) < 0]   # synaren vinner
    hi = [v for v in rules.RANKING if rules.compare(v, claim) >= 0]  # synaren förlorar
    p_lo = sum(OUTCOME_P[v] for v in lo)
    p_hi = sum(OUTCOME_P[v] for v in hi)
    l_win = sum(lives_lost(claim, v) * OUTCOME_P[v] for v in lo) / p_lo if p_lo else 0.0
    l_lose = sum(lives_lost(claim, v) * OUTCOME_P[v] for v in hi) / p_hi if p_hi else 0.0
    return CallOdds(claim=claim, p_win=p_lo, l_win=l_win, l_lose=l_lose)


#: CallOdds för varje giltigt påstående. Beräknas en gång.
CALL_ODDS: dict[int, CallOdds] = {value: _call_odds(value) for value in rules.RANKING}


# -- Agentens parametrar -----------------------------------------------------

@dataclass(frozen=True)
class AgentParams:
    """En agents beteendeprofil: fyra oberoende dimensioner på skalan 0–1.

    ``caution``           – hur gärna agenten undviker risk och låter andra ta
                            besluten. Hög försiktighet höjer tröskeln för att syna.
    ``statistics``        – hur mycket agenten styr sina beslut av sannolikheter.
                            Noll betyder en enda fast tro; ett betyder fullt ut
                            den påståendespecifika tabellen.
    ``unpredictability``  – hur mycket agenten varierar sitt spel för att vara
                            svår att läsa.
    ``reading``           – hur mycket motståndarnas tidigare beteende får styra.

    Bluffandet är **inte** en parameter. I Meier måste man höja över det som
    står, och då blir en del påståenden lögner vad man än vill. Bluffen är ett
    nödvändigt ont i spelet, inte en personlighetsegenskap att skruva på.
    """

    caution: float = 0.5
    statistics: float = 0.5
    unpredictability: float = 0.2
    reading: float = 0.0

    def __post_init__(self) -> None:
        for name in ("caution", "statistics", "unpredictability", "reading"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} måste vara mellan 0 och 1, fick {v}")


#: Spelarna och deras egna profiler bor i ``meier/agents/roster.py``.
#: Parametrarna är den enda platsen profilen får bo — inte i ett namn. Se
#: registret för värdena och motiveringen.


# -- Beslut -----------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    """Ett färdigt beslut från policyn.

    ``action`` är en av ``"påstå"``, ``"slå"``, ``"syna"``, ``"skicka"`` eller
    ``"titta"``/``"unseen"`` (vid tvingad höjning). ``claim`` är satt för påstående och slå.
    ``reason`` är en kort maskinell motivering (LLM:en får formulera en rikare).
    """

    action: str
    claim: int | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {"action": self.action, "claim": self.claim, "reason": self.reason}


#: Den typiska bluff-frekvensen i populationen, mätt på **avslöjade** påstående
#: (frivilliga väger fullt, de som görs utan att titta halvt). Används som nämnare när en motståndares
#: benägenhet mäts relativt populationen, och som förhandstro innan en spelare
#: avslöjats.
#:
#: Notera att detta **inte** är samma tal som andelen påståenden över tärningarna
#: bland alla synliga påståenden (~0,52). Skillnaden är de tvingade
#: höjningarna: de ligger mekaniskt över tärningarna för alla och räknas därför
#: bort ur profilen. Använder man 0,52 som
#: nämnare får varje normal spelare ratio > 1,0 och en läsande agent synar i
#: onödan.
#:
#: Värdet är fryst. Det påverkas inte av tärningarnas form: samma mätning ger
#: 0,048 med areamodellen och 0,040 med rymdvinkelmodellen. Eftersom
#: ``bluff_ratio`` delar med detta tal förkortas det till stor del bort — det som
#: styr läsningen är förhållandet mellan spelaren och populationen.
DEFAULT_Q = 0.715

#: Kalibrerad, fryst, **riskjusterad** tro på ``P(synaren vinner | påståendenivå)``.
#:
#: Detta är kärnan i ``q``-modellen, men **per påståendenivå**. Ett enda globalt tal
#: räcker inte: sannolikheten att en syn vinner varierar kraftigt med påståendet,
#: därför att motståndare påstår över sina tärningar när de är svaga.
#:
#: Tabellen är **inte** den råa sannolikheten ``P(shown < claim)``. Den är medvetet
#: *mer försiktig* än så, och det av två skäl som hänger ihop:
#:
#: 1. **Livsförlusten är asymmetrisk.** Att syna ett lågt påstående som 33 vinner ofta
#:    (P ≈ 0,73), men när det går fel kostar det mycket. En rå sannolikhet skulle
#:    därför locka agenten att syna påstående som har negativt *livs*överskott.
#: 2. **Synfrekvensen styr inlärningen.** Synar ingen frivilligt blir de enda
#:    avslöjade påståendena tvingade höjningar — och då finns ingen data att läsa. En
#:    alltför försiktig tabell gör därför *läsningen* värdelös (se avsnitt 6).
#:
#: Tabellen är kalibrerad som en **halvvägs-sammandragning** mellan den
#: riskjusterade försiktiga nivån och den uppmätta sanna sannolikheten (se
#: ``docs/agent-model.md``, avsnitt 5.1). Den punkten ger samtidigt en stark
#: BASE, en stark läsande baslinje och ett **positivt** värde av läsning.
CALL_PRIOR: dict[int, float] = {
    21: 0.549, 11: 0.627, 22: 0.627, 33: 0.507, 44: 0.481, 55: 0.478, 66: 0.485,
    65: 0.534, 64: 0.482, 63: 0.416, 62: 0.433, 61: 0.428, 54: 0.316, 53: 0.274,
    52: 0.319, 51: 0.399, 43: 0.240, 42: 0.287, 41: 0.273, 32: 0.331, 31: 0.000,
}

#: Tröghetströskel för synen, i liv:
#: ``inertia = CALL_INERTIA_BASE + CALL_INERTIA_CAUTION * (0.5 - caution)``.
#:
#: Tröskeln är det försprång en syn får: den läggs på synens värde, så ett högre
#: tal betyder att agenten synar oftare. En försiktig agent ska syna *mindre*,
#: alltså får ``caution`` dra åt andra hållet. Vid ``caution = 0,5`` blir värdet
#: exakt ``CALL_INERTIA_BASE``, så baslinjen spelar som förut.
CALL_INERTIA_BASE = 0.13
CALL_INERTIA_CAUTION = 0.10

#: Värdet av att en bluff står obesvarat, i liv. **Fast**, inte en parameter.
#:
#: Bluffen är ett nödvändigt ont i Meier: den som slår måste alltid säga ett högre
#: påstående, och då blir en del påståenden lögnar vad spelaren än vill. Därför finns
#: det ingen bluffparameter att skruva på.
#:
#: Talet är **inte** hämtat ur reglerna. Reglerna säger bara vad som händer vid en
#: syn; de säger ingenting om vad ett påstående som ingen synar är värt. Att sätta
#: ett tal här är alltså ett antagande om bordet, inte en regel. Det är medvetet
#: hållet fast: maskinens uppgift är att visa vad agenterna gör, inte att hitta den
#: bästa strategin. Vill man undersöka bluffandet är det här ratten sitter, men
#: ändra den inte för att "rätta" ett spel som ser fel ut.
BLUFF_GAIN = 0.5

#: Den platta tron på ``P(synaren vinner | påstående)`` som en agent med
#: ``statistics = 0`` använder. Medelvärdet av ``CALL_PRIOR``: agenten bortser från
#: påståendenivån och tror samma sak oavsett vad som står.
FLAT_Q = 0.45

#: Hur stort bruset från ``unpredictability`` är, i liv, vid värdet 1,0.
#:
#: Värdena som jämförs ligger typiskt mellan −0,5 och +0,5 liv. Bruset måste vara
#: stort nog att byta ut två nästan lika bra drag, men litet nog att aldrig göra
#: ett uppenbart dåligt drag. 0,15 liv gör precis det.
UNPREDICTABILITY_SPAN = 0.15

#: Golv och lutning för ``P(påståendet blir synat)``. Högre påståenden synas oftare. Golvet
#: hindrar att ett lågt påstående ser ut att vara gratis att bluffa till.
CALL_FLOOR = 0.10
CALL_SLOPE = 0.40


@dataclass
class BasePolicy:
    """Stark, icke-läsande referensagent.

    Den maximerar förväntad överlevnad och har en enda global tro ``q`` på
    motståndarens bluffbenägenhet. Den läser aldrig enskilda motståndare.

    ``rng`` styr bara hur mycket agenten varierar sitt spel
    (``unpredictability``). Varje policy får en egen slumptalare.
    """

    params: AgentParams = field(default_factory=AgentParams)
    q: float = DEFAULT_Q
    rng: random.Random = field(default_factory=random.Random)

    # -- Trons beroende av påståendenivån ----------------------------------
    def belief(self, claim: int, opponent_q: float | None = None) -> float:
        """Tron på att en syn vinner, vägd enligt ``statistics``.

        ``statistics = 1`` ger fullt ut den påståendespecifika tabellen
        (eller motståndarens skattning, om en sådan finns). ``statistics = 0``
        ger en enda platt tro: agenten struntar i vilket påstående som står och
        tror samma sak varje gång. Däremellan blandas de två linjärt.
        """
        specific = CALL_PRIOR[claim] if opponent_q is None else opponent_q
        weight = self.params.statistics
        return weight * specific + (1.0 - weight) * FLAT_Q

    def inertia(self) -> float:
        """Försprånget en syn får. ``caution`` minskar det, alltså synas mindre."""
        return CALL_INERTIA_BASE + CALL_INERTIA_CAUTION * (0.5 - self.params.caution)

    # -- Oförutsägbarhet ---------------------------------------------------
    def jitter(self) -> float:
        """Ett litet avvikelsebelopp som gör draget svårare att läsa.

        Agenten väljer inte slumpmässigt bland alternativen — det vore att kasta
        bort spelet. Den lägger i stället ett brus på sina värderingar, så att två
        nästan lika bra drag ibland byts ut mot varandra. Med
        ``unpredictability = 0`` blir bruset noll och agenten helt mekanisk.
        """
        if self.params.unpredictability <= 0.0:
            return 0.0
        return self.rng.uniform(-1.0, 1.0) * self.params.unpredictability * UNPREDICTABILITY_SPAN

    # -- Beslut 3: syna eller skicka ------------------------------------
    def decide_call(
        self, claim: int, *, lives: int = 3, opponent_q: float | None = None
    ) -> Decision:
        """Ska agenten syna påståendet ``claim``? Agenten ser inte sina tärningar här.

        ``opponent_q`` är en motståndarspecifik bluffskattning (för läsande
        agenter). Utan den används den **påståendespecifika** tron ``CALL_PRIOR[claim]``,
        blandad med den platta tron enligt ``statistics``.

        Synen avgörs av det förväntade livsöverskottet, med en liten
        tröghetströskel: att skicka vidare ger noll chans att vinna rundan, så
        en syn som nästan går jämnt upp är värd att ta.

        Den här metoden ser bara två val. Spelaren har tre — se
        :meth:`decide_response`, som även väger in att slå.
        """
        odds = CALL_ODDS[claim]
        q = self.belief(claim, opponent_q)
        ev = odds.ev_call(q)
        # En syn är bara värd att ta om livsöverskottet är klart positivt. En syn
        # som ligger nära break-even är ett lotteri om livet, och i Meier är det
        # *att överleva* som räknas — inte att vinna enskilda rundor. Tröskeln
        # ``inertia`` gör agenten konservativ, och ``caution`` höjer den.
        inertia = self.inertia()
        if ev > -inertia:
            return Decision(
                "syna",
                reason=f"P(vinst)={q:.2f}; EV={ev:+.3f} liv > −{inertia:.3f}",
            )
        return Decision(
            "skicka",
            reason=f"P(vinst)={q:.2f}; EV={ev:+.3f} liv < −{inertia:.3f}",
        )

    # -- Beslut 3b: alla tre svar på ett påstående ------------------------------
    def decide_response(
        self, claim: int, *, lives: int = 3, opponent_q: float | None = None
    ) -> Decision:
        """Välj mellan att syna, skicka vidare och slå.

        Alla tre värderas som **mitt** förväntade livsöverskott, så att de går
        att jämföra direkt. Det är skillnaden mot :meth:`decide_call`, som bara
        väger synen mot att lägga sig.

        - **Syna** — tärningarna avgör. Värdet är synens EV (samma som i
          :meth:`decide_call`).
        - **Skicka vidare** — påståendet står kvar men ansvaret flyttas till mig.
          Jag förlorar liv om tärningarna visar lägre än påståendet; annars förlorar
          nästa spelare som synar. Värdet är därför nollsummespelet ovanför
          påståendet, viktat med hur ofta påståendet synas.
        - **Slå** — jag skakar utan att titta och måste påstå högre. Vilket påstående det blir
          avgör :meth:`decide_raise`; det är samma påstående som motorn sedan spelar.
          Värdet är hållarvärdet för just det påståendet.

        Ingen av de tre tvingas fram. ``slå`` väljs bara när det slår båda
        andra, och ``syna`` behåller sin tröghetströskel så att en syn nära
        break-even inte blir ett lotteri om livet. ``unpredictability`` lägger
        ett litet brus på värdena, så nästan lika bra drag ibland byts ut.
        """
        odds = CALL_ODDS[claim]
        q = self.belief(claim, opponent_q)

        call_ev = odds.ev_call(q)
        inertia = self.inertia()
        noise = self.jitter()

        hold_ev = self._hold_value(claim)

        options: list[tuple[str, float, str]] = [
            ("syna", call_ev + inertia + noise, f"EV={call_ev:+.3f} liv (tröskel −{inertia:.3f})"),
            ("skicka", hold_ev - noise, f"hållarvärde={hold_ev:+.3f} liv"),
        ]

        shake = self.decide_raise(claim)
        if shake.action == "slå" and shake.claim is not None:
            shake_ev = self._hold_value(shake.claim)
            options.append(
                ("slå", shake_ev + noise, f"slå till {rules.name(shake.claim)}: {shake_ev:+.3f} liv")
            )

        action, _, why = max(options, key=lambda opt: opt[1])
        return Decision(action, claim=None, reason=why)

    def _hold_value(self, claim: int) -> float:
        """Mitt förväntade livsöverskott av att bära påståendet ``claim``.

        Påståendet synas med sannolikheten ``p_called``. Blir det synat vinner jag
        om tärningarna visar lägre än påståendet — då förlorar synaren liv. Annars
        förlorar jag. Blir det inte synat händer ingenting i den här rundan.
        """
        odds = CALL_ODDS[claim]
        p_called = self._p_called(claim)
        win = (1.0 - odds.p_win) * odds.l_lose
        lose = odds.p_win * odds.l_win
        return p_called * (win - lose)

    # -- Beslut 2: slå (ser tärningarna, om spelaren inte väljer bort det) ----
    def decide_raise(self, claim: int) -> Decision:
        """Vilket påstående ska agenten säga när den slår utan att titta, över ``claim``?

        Detta är **fintaktikens** väg: spelaren har valt bort titten och vet därför
        inte vad tärningarna visar. Den minsta lagliga höjningen är då säkrast
        (minst chans att tärningarna visar lägre). En oförutsägbar agent hoppar
        ibland högre ändå, just för att den inte ska gå att läsa.

        Grundtaktiken går i stället via :meth:`decide_claim`, som får de sedda
        tärningarna. Se :meth:`decide_shake`.
        """
        higher = rules.higher_options(claim)
        if not higher:
            return Decision("syna", reason="Inget högre påstående finns; enda svar är att syna.")
        # higher[0] är högst (Meier), higher[-1] är minsta höjning.
        steps = 0
        if self.params.unpredictability > 0.0:
            if self.rng.random() < self.params.unpredictability:
                steps = self.rng.randint(1, len(higher) - 1) if len(higher) > 1 else 0
        new_claim = higher[-(steps + 1)]
        return Decision("slå", claim=new_claim, reason=f"Slår till {rules.name(new_claim)}.")

    def decide_shake(self, claim: int) -> Decision:
        """Väljer spelaren att titta på de nya tärningarna när den slår?

        Att titta är det normala: reglerna låter spelaren lyfta på locket på sitt
        eget slag, och den som tittar kan lägga påståendet rätt. Att avstå är
        fintaktik. Det köper ingen information, men det gör påståendet svårt att
        läsa, och en syn går ändå hem om tärningarna visar påståendet eller högre.

        Grundtaktiken väljer alltid titten. Det håller referensen enkel och
        begriplig: fintaktiken hör till de profiler som uttryckligen har
        ``unpredictability``.
        """
        return Decision("titta", reason="Tittar på tärningarna.")

    # -- Beslut 1: första påståendet (ser tärningarna) -----------------------
    def decide_claim(
        self,
        shown: int,
        *,
        opponent_factor: float = 1.0,
        previous_claim: int | None = None,
    ) -> Decision:
        """Vilket påstående ska agenten säga när den sett tärningarna visa ``shown``?

        Att påstå ``shown`` är **säkert**: blir det synat visar tärningarna minst
        påståendet, så synaren förlorar. Det är grundpåståendet.

        Ett påstående **över** ``shown`` är en bluff. Den vinner bara om motståndaren
        lägger sig (sannolikhet ``1 − p_called``) och förlorar liv om den synas.
        En bluff lönar sig därför bara när den är *billig att bli synad på* — alltså
        på påståendenivåer som sällan synas. Vikten av att motståndaren lägger sig
        är den fasta ``BLUFF_GAIN``: bluffen är ett nödvändigt ont i Meier, inte en
        personlighetsegenskap.

        ``previous_claim`` är påståendet som ligger när spelaren måste höja. Utan det
        valde agenten påståenden som om bordet var tomt, och motorn fick sedan tyst
        skriva om påståendet till minsta lagliga höjning. Här väljer agenten i stället
        bland de lagliga påståendena direkt, så att påståendet den säger är dess eget.

        ``opponent_factor`` är motståndarens **synbenägenhet** relativt det
        normala (1,0 = som folk mest). En motståndare som synar ofta gör varje
        bluff dyrare, och då bluffar agenten mindre. Det är läsningens inverkan
        på påståendet, skild från agentens egen ``caution``, som styr hur gärna
        den synar.
        """
        legal = legality.legal_claims(shown=shown, previous_claim=previous_claim)
        if not legal:
            raise ValueError(f"Inget lagligt påstående över {rules.name(previous_claim)}")

        if rules.is_meier(shown):
            return Decision("påstå", claim=shown, reason="Meier — högsta möjliga, påstår det.")

        # Grundpåståendet är det högsta lagliga påstående som inte är en bluff, alltså
        # ``shown`` om det är lagligt, annars minsta lagliga höjning.
        safe = shown if shown in legal else legal[-1]

        # Ett sant påstående kan synas utan att synaren vinner: då förlorar synaren
        # livet och jag vinner det. Värdet är därför synsannolikheten gånger
        # synarens förlust. Utan den termen jämfördes bluffen mot noll och vann
        # över ett påstående som i själva verket är bättre.
        safe_p_called = self._p_called(safe, opponent_factor)
        safe_gain = safe_p_called * CALL_ODDS[safe].l_lose

        best_bluff: int | None = None
        best_gain = safe_gain
        for cand in legal:
            if rules.compare(cand, shown) <= 0:
                continue
            p_called = self._p_called(cand, opponent_factor)
            # Synas bluffen förlorar jag mina egna liv, alltså ``l_win``. ``l_lose``
            # är synarens förlust, det vill säga min vinst.
            gain = (1.0 - p_called) * BLUFF_GAIN - p_called * CALL_ODDS[cand].l_win
            if gain > best_gain:
                best_gain, best_bluff = gain, cand

        # En oförutsägbar spelare tar ibland den säkra vägen även när en bluff
        # räknas som marginellt bättre, så att motståndaren inte kan läsa
        # mönstret "bluffar bara på höga påståenden".
        if best_bluff is not None:
            if self.rng.random() < self.params.unpredictability * 0.25:
                best_bluff = None

        if best_bluff is not None:
            return Decision(
                "påstå",
                claim=best_bluff,
                reason=(
                    f"Visar {rules.name(shown)}; bluffar {rules.name(best_bluff)} "
                    f"(vinst {best_gain:+.2f} liv)."
                ),
            )
        return Decision(
            "påstå",
            claim=safe,
            reason=f"Visar {rules.name(shown)}; påstår {rules.name(safe)}.",
        )

    def _p_called(self, claim: int, opponent_factor: float = 1.0) -> float:
        """Uppskattad sannolikhet att ett påstående blir synat.

        Fryst heuristik, kalibrerad mot empirin: högre påståenden synas oftare eftersom
        de är billigare att syna (synaren vinner oftare). Låga påståenden synas sällan
        men aldrig *aldrig* — därför ett golv. Utan golvet ser en bluff till ett
        lågt påstående ut att vara gratis, och agenten bluffar ihjäl sig.

        ``opponent_factor`` skalar uppskattningen med motståndarens kända
        synbenägenhet (se :meth:`OpponentTracker.call_factor`). Den som möter en
        synbenägen motståndare räknar med att bli synad oftare — och bluffar
        därför mindre.
        """
        base = min(1.0, CALL_FLOOR + CALL_SLOPE * _strength(claim))
        return min(1.0, base * opponent_factor)

    # -- Beslut 4: tvingad höjning (titta eller inte titta) ------------------
    def decide_forced(self, claim: int) -> Decision:
        """Titta på de nya tärningarna eller påstå utan att titta? Fattas utan att titta.

        Att titta är tryggare: då kan spelaren påstå något tärningarna faktiskt
        bär. Att påstå utan att titta döljer informationen för bordet. En försiktig spelare
        väljer det trygga, en oförutsägbar väljer ibland det som inte går att läsa.
        """
        if not rules.higher_options(claim):
            return Decision("syna", reason="Meier är högst; kan inte höja.")
        if self.params.unpredictability > 0.0:
            if self.rng.random() < self.params.unpredictability * 0.5:
                return Decision("unseen", reason="Oförutsägbar profil: påstår utan att titta.")
        return Decision("titta", reason="Försiktig profil: tittar på tärningarna.")
