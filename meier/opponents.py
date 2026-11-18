"""Motståndarmodell för Meier — läckagefri per konstruktion.

Agenten får bara använda information som var **offentlig vid beslutstillfället**.
Den här modulen är byggd så att det inte går att bryta mot den regeln av misstag:
``OpponentTracker`` tar emot enbart offentliga observationer, och de faktiska
tärningarna kommer in **bara** via :meth:`OpponentTracker.reveal`, som motorn
anropar *efter* att en syn avgjorts.

Varför det spelar roll: ``session.py`` loggar ``shown`` (de faktiska tärningarna)
för varje bud. Bygger man profilen ur hela loggen läcker framtiden in i nuet —
agenten "vet" då att ett bud *var* en bluff, fast ingen kunde veta det än. Det
gör resultaten ogiltiga. Här kan det inte hända.

En bluff kan alltså bara räknas **efter** att rundan avslöjats genom en syn.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .policy import DEFAULT_Q

#: Styrka på förhandstron. Med ``alpha`` "låtsas" vi ha sett ``alpha`` bud som
#: betett sig som den globala tron. Högre värde = trögare inlärning.
PRIOR_STRENGTH = 4.0

#: Hur mycket ett avslöjat **blint** bud väger mot ett avslöjat frivilligt bud.
#: Ett slag är ett svagare löfte (spelaren såg inte tärningarna), men det är
#: fortfarande en lögn motståndarna ser, så det väger mer än noll.
BLIND_WEIGHT = 0.5

#: Namnet på den nominella spelaren i motståndarprofilen. Profilens tal är
#: **relativa** mot detta: ``press = 0,5`` betyder "bluffar som folk gör mest".
#: Talet är medvetet inte samma som ``DEFAULT_Q`` (0,715) — ``DEFAULT_Q`` är en
#: uppmätt *bluff-frekvens*, medan profilens tal är en *benägenhet* på en
#: neutral skala där 0,5 är mitten. Översättningen sker i
#: :meth:`OpponentTracker.profile_factor`.
NEUTRAL_PRESS = 0.5


@dataclass(frozen=True)
class OpponentProfile:
    """En agents **uppskattning** av en annan spelare.

    Detta är en gissning byggd ur offentligt observerbart beteende — aldrig ur
    motståndarens verkliga parametrar. Varje tal ligger mellan 0 och 1.

    ``risk``           – hur gärna motståndaren tar en osäker chans.
    ``press``          – hur ofta motståndaren bluffar och pressar.
    ``predictability`` – hur förutsägbar motståndaren är.
    ``kind``           – kort etikett, t.ex. "bluffbenägen" eller "försiktig".
    ``confidence``     – hur säker uppskattningen är.
    ``source``         – varifrån profilen kommer: ``"llm"``, ``"statistik"``
                         (sekreterarens sammanställning utan LLM) eller
                         ``"population"`` (ingen data alls).
    """

    risk: float = 0.5
    press: float = NEUTRAL_PRESS
    predictability: float = 0.5
    kind: str = "okänd"
    confidence: float = 0.0
    source: str = "population"

    def __post_init__(self) -> None:
        for name in ("risk", "press", "predictability", "confidence"):
            object.__setattr__(self, name, _clamp01(getattr(self, name)))

    def to_dict(self) -> dict:
        return {
            "risk": round(self.risk, 3),
            "press": round(self.press, 3),
            "predictability": round(self.predictability, 3),
            "kind": self.kind,
            "confidence": round(self.confidence, 3),
            "source": self.source,
        }

    def describe(self) -> str:
        """Motståndarbilden i klartext, med siffrorna i parentes.

        Tanken är att en människa ska kunna läsa vad agenten *tror* om en
        motståndare utan att tolka råa tal. Siffrorna står kvar i parentesen så
        att beskrivningen går att kontrollera.
        """
        if self.source == "population":
            return (
                "Ingen bild än — spelaren har inte sett tillräckligt av den här "
                "motståndaren."
            )
        return (
            f"{self.kind.capitalize()}: {_press_words(self.press)}, "
            f"{_risk_words(self.risk)} och {_predict_words(self.predictability)} "
            f"(risk {pct(self.risk)}, press {pct(self.press)}, "
            f"förutsägbarhet {pct(self.predictability)}; "
            f"{_confidence_words(self.confidence)})."
        )


def pct(value: float) -> str:
    """Ett tal 0–1 som procenttext, för läsbara beskrivningar."""
    return f"{round(value * 100)} %"


def describe_params(risk: float, press: float, reading: float) -> str:
    """En spelares **egen** karaktär i klartext, med siffrorna i parentes.

    Används i spelarlistan. Detta är spelarens kända inställning, till skillnad
    från :meth:`OpponentProfile.describe`, som är en *gissning* om någon annan.
    """
    if reading <= 0.0:
        reading_words = "läser ingen motståndare"
    elif reading < 0.35:
        reading_words = "läser motståndarna lite"
    elif reading < 0.6:
        reading_words = "läser motståndarna"
    else:
        reading_words = "läser motståndarna noga"
    return (
        f"{_risk_words(risk).capitalize()}, {_press_words(press)} och "
        f"{reading_words} "
        f"(risk {pct(risk)}, press {pct(press)}, läsning {pct(reading)})."
    )


def _risk_words(risk: float) -> str:
    if risk < 0.25:
        return "synar nästan aldrig"
    if risk < 0.45:
        return "synar sällan"
    if risk < 0.6:
        return "synar ibland"
    if risk < 0.75:
        return "synar ofta"
    return "synar nästan alltid"


def _press_words(press: float) -> str:
    if press < 0.25:
        return "bluffar nästan aldrig"
    if press < 0.45:
        return "bluffar sällan"
    if press < 0.6:
        return "bluffar lagom mycket"
    if press < 0.75:
        return "bluffar ofta"
    return "bluffar nästan jämt"


def _predict_words(predictability: float) -> str:
    if predictability < 0.35:
        return "är svår att läsa"
    if predictability < 0.65:
        return "är ganska förutsägbar"
    return "är mycket förutsägbar"


def _confidence_words(confidence: float) -> str:
    if confidence < 0.25:
        return "litet underlag"
    if confidence < 0.6:
        return "måttligt underlag"
    return "gott underlag"


def _clamp01(value: float) -> float:
    """Klämm ett tal till [0, 1]; tål skräp från en LLM."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.5
    if x != x:  # NaN
        return 0.5
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass
class OpponentStats:
    """Vad vi vet om en motståndare, allt ur offentlig information.

    ``visible_bids``       – antal icke-blinda *frivilliga* bud (initialbud) vi sett.
    ``forced_bids``        – antal tvingade höjningar (mekaniska, säger inget om personen).
    ``revealed``           – hur många frivilliga bud som avslöjats genom en syn.
    ``revealed_bluffs``    – hur många av de avslöjade som var lögner.
    ``decisions``          – antal svar mot ett bud (slå/skicka/syna).
    ``passes``             – hur ofta spelaren skickade vidare (ger upp under press).
    ``raises``             – hur ofta spelaren slog (pressade tillbaka).
    ``calls``              – hur ofta spelaren synade.
    ``calls_won``          – hur ofta synen gick hem.
    """

    visible_bids: int = 0
    forced_bids: int = 0
    revealed: int = 0
    revealed_bluffs: int = 0
    revealed_blind: int = 0
    revealed_blind_bluffs: int = 0
    decisions: int = 0
    passes: int = 0
    raises: int = 0
    calls: int = 0
    calls_won: int = 0

    def to_dict(self) -> dict:
        return {
            "visible_bids": self.visible_bids,
            "forced_bids": self.forced_bids,
            "revealed": self.revealed,
            "revealed_bluffs": self.revealed_bluffs,
            "revealed_blind": self.revealed_blind,
            "revealed_blind_bluffs": self.revealed_blind_bluffs,
            "decisions": self.decisions,
            "passes": self.passes,
            "raises": self.raises,
            "calls": self.calls,
            "calls_won": self.calls_won,
        }


@dataclass
class OpponentTracker:
    """Bygger motståndarprofiler ur enbart offentlig information.

    Anropas av motorn i takt med att händelser blir offentliga:

    - :meth:`observe_bid` när en spelare säger ett bud (offentligt direkt).
    - :meth:`observe_decision` när en spelare svarar på ett bud (offentligt direkt).
    - :meth:`reveal` **endast efter** att en syn avgjorts, med facit.

    Ingen metod tar emot dolda tärningar eller framtida drag.
    """

    global_q: float = DEFAULT_Q
    prior_strength: float = PRIOR_STRENGTH
    stats: dict[str, OpponentStats] = field(default_factory=dict)

    def _bucket(self, player: str) -> OpponentStats:
        return self.stats.setdefault(player, OpponentStats())

    # -- Offentliga observationer ---------------------------------------
    def observe_bid(self, player: str, *, blind: bool, forced: bool = False) -> None:
        """En spelare säger ett bud. Blinda bud är inga löften — räknas inte.

        ``forced`` markerar en **tvingad höjning** (bägaren har gått ett helt
        varv). En sådan är mekanisk: budgivaren måste höja vad tärningarna än
        visar, så den säger inget om personen. Räknas separat och används aldrig
        i bluffprofilen — annars dränks varje spelares profil av de ~78 %
        tvingade bud som *alla* tvingas till, och en försiktig spelare ser ut som
        en värre bluffare än en riktig bluffare.
        """
        if forced:
            self._bucket(player).forced_bids += 1
        elif not blind:
            self._bucket(player).visible_bids += 1
        # Ett blint bud skapar ingen profil: det är inget löfte, och en spelare
        # som bara har slagit ska fortfarande ligga på den globala förhandstron.

    def observe_decision(self, player: str, action: str) -> None:
        """En spelare svarar på ett bud: ``slå``, ``skicka`` eller ``syna``."""
        bucket = self._bucket(player)
        bucket.decisions += 1
        if action == "skicka":
            bucket.passes += 1
        elif action == "slå":
            bucket.raises += 1
        elif action == "syna":
            bucket.calls += 1

    def reveal(
        self, player: str, *, was_bluff: bool, blind: bool = False, forced: bool = False
    ) -> None:
        """Facit efter en syn: var spelarens bud en bluff?

        Anropas **bara** när tärningarna redan är avslöjade och rundan är avgjord.
        Attribueras till den som *sa* budet (den som synen gällde), inte till den
        som eventuellt skickade vidare.

        En **tvingad höjning** (``forced``) räknas aldrig: budgivaren måste höja
        vad tärningarna än visar, så den säger inget om personen. Utan detta blev
        varje spelares profil en spegel av de ~78 % tvingade bud *alla* tvingas
        till — och en försiktig spelare såg ut som en värre bluffare än en riktig
        bluffare.

        Ett **blint** bud (ett slag) räknas, men väger hälften: spelaren lovade
        inget den kunde se, men lögnen syns för motståndarna.
        """
        if forced:
            return
        bucket = self._bucket(player)
        if blind:
            bucket.revealed_blind += 1
            if was_bluff:
                bucket.revealed_blind_bluffs += 1
        else:
            bucket.revealed += 1
            if was_bluff:
                bucket.revealed_bluffs += 1

    def record_call_outcome(self, caller: str, *, won: bool) -> None:
        """Facit för en syn: vann den som synade? Attribueras till synaren."""
        bucket = self._bucket(caller)
        if won:
            bucket.calls_won += 1

    # -- Uppskattningar --------------------------------------------------
    def bluff_estimate(self, player: str) -> float:
        """Skattad bluff-frekvens för spelaren, eller den globala tron.

        Använder bara bud som **avslöjats** genom en syn. Frivilliga bud (där
        spelaren såg tärningarna) väger tyngst; blinda slag väger hälften så
        mycket, eftersom spelaren då inte lovade något den kunde se. Finns inga
        avslöjade bud är svaret den globala frekvensen — agenten vet inget än.
        """
        bucket = self.stats.get(player)
        if bucket is None:
            return self.global_q
        n = bucket.revealed + BLIND_WEIGHT * bucket.revealed_blind + self.prior_strength
        if n <= self.prior_strength:
            return self.global_q
        hits = (
            bucket.revealed_bluffs
            + BLIND_WEIGHT * bucket.revealed_blind_bluffs
            + self.prior_strength * self.global_q
        )
        return hits / n

    def bluff_ratio(self, player: str) -> float:
        """Spelarens bluffbenägenhet **relativt** populationen, kring 1,0.

        Detta är nyckeln till läsningen. Att byta ut den budspecifika tron mot
        spelarens *absoluta* bluff-frekvens vore ett fel: ett lågt bud (där
        nästan ingen bluffar, ``CALL_PRIOR[bid] ≈ 0,05``) skulle då plötsligt
        bedömas med t.ex. 0,4 och agenten skulle syna bud som nästan alltid är
        sanna. I stället skalas tron **relativt** populationens nivå: en spelare
        som bluffar dubbelt så ofta som normalt får ratio 2,0, och då dubblas
        synsannolikheten för varje budnivå.
        """
        if self.global_q <= 0.0:
            return 1.0
        return self.bluff_estimate(player) / self.global_q

    def effective_prior(self, bid: int, player: str, *, reading: float) -> float:
        """Budspecifik tro på att en syn vinner, justerad för spelaren.

        ``reading = 0`` ger den frysta populationstabellen (ingen läsning).
        ``reading = 1`` ger spelarens relativa benägenhet fullt ut. Resultatet
        hålls inom rimliga gränser så en liten urvalsstorlek inte kan slå över.
        """
        from .policy import CALL_PRIOR

        base = CALL_PRIOR[bid]
        ratio = self.bluff_ratio(player) ** reading
        return min(0.95, base * ratio)

    def give_up_rate(self, player: str) -> float | None:
        """Hur ofta spelaren ger upp (skickar) i stället för att slå eller syna."""
        bucket = self.stats.get(player)
        if bucket is None or bucket.decisions == 0:
            return None
        return bucket.passes / bucket.decisions

    def call_rate(self, player: str) -> float | None:
        """Hur ofta spelaren synar i stället för att skicka/slå. Riskbenägenhet."""
        bucket = self.stats.get(player)
        if bucket is None or bucket.decisions == 0:
            return None
        return bucket.calls / bucket.decisions

    # -- Sekreterarens sammanställning ----------------------------------
    def evidence(self, player: str) -> dict:
        """Rå, **offentlig** sammanställning om ``player``. Ingen tolkning.

        Detta är vad sekreteraren har skrivit i protokollet: antal synliga bud,
        hur många som avslöjats, hur många av dem som var lögner, hur spelaren
        svarat på bud. Motståndarprofilen byggs ur detta — men tolkningen görs
        av LLM:en, inte här. Alla tal är sådana en åskådare vid bordet hade
        kunnat räkna upp; inga dolda tärningar ingår.
        """
        bucket = self.stats.get(player)
        if bucket is None:
            return {
                "visible_bids": 0,
                "revealed": 0,
                "revealed_bluffs": 0,
                "decisions": 0,
                "passes": 0,
                "raises": 0,
                "calls": 0,
                "calls_won": 0,
                "bluff_rate": None,
                "pass_rate": None,
                "call_rate": None,
            }
        revealed = bucket.revealed + bucket.revealed_blind
        bluffs = bucket.revealed_bluffs + bucket.revealed_blind_bluffs
        return {
            "visible_bids": bucket.visible_bids,
            "revealed": revealed,
            "revealed_bluffs": bluffs,
            "decisions": bucket.decisions,
            "passes": bucket.passes,
            "raises": bucket.raises,
            "calls": bucket.calls,
            "calls_won": bucket.calls_won,
            "bluff_rate": (bluffs / revealed) if revealed else None,
            "pass_rate": (bucket.passes / bucket.decisions) if bucket.decisions else None,
            "call_rate": (bucket.calls / bucket.decisions) if bucket.decisions else None,
        }

    def has_evidence(self, player: str) -> bool:
        """Finns något alls att tolka? Annars är profilen bara populationen."""
        bucket = self.stats.get(player)
        if bucket is None:
            return False
        return (bucket.revealed + bucket.revealed_blind) > 0 or bucket.decisions > 0

    def statistical_profile(self, player: str) -> OpponentProfile:
        """Deterministisk fallback-profil ur sekreterarens siffror.

        Används när ingen LLM finns (utvärderingsläget) eller när LLM:en inte
        svarar. Den läser samma offentliga historik som LLM:en får se, men med
        enkel aritmetik i stället för tolkning. Utan data: populationen.
        """
        ev = self.evidence(player)
        if not self.has_evidence(player):
            return OpponentProfile()
        n = ev["revealed"] + ev["decisions"]
        confidence = min(1.0, n / 10.0)
        # Skalan är centrerad kring NEUTRAL_PRESS = "bluffar som folk gör mest".
        # En rå bluff-frekvens (~0,72 för en vanlig spelare) skulle annars lägga
        # varje spelare över mitten och skruva upp tron i onödan. Därför skalas
        # benägenheten **relativt** populationen, precis som ``bluff_ratio``.
        press = (
            NEUTRAL_PRESS * self.bluff_ratio(player)
            if ev["bluff_rate"] is not None
            else NEUTRAL_PRESS
        )
        risk = ev["call_rate"] if ev["call_rate"] is not None else 0.5
        if ev["bluff_rate"] is None and ev["call_rate"] is None:
            return OpponentProfile()
        return OpponentProfile(
            risk=risk,
            press=press,
            predictability=0.5,
            kind="okänd",
            confidence=confidence,
            source="statistik",
        )

    def profile_factor(self, profile: OpponentProfile) -> float:
        """Översätt en motståndarprofils ``press`` till en **relativ** faktor.

        Faktorn är kring 1,0 och multipliceras på den budspecifika tron, precis
        som :meth:`bluff_ratio`. ``press = 0,5`` (neutralt) ger 1,0; en spelare
        som bedöms bluffa dubbelt så ofta ger 2,0. Faktorn dämpas av profilens
        konfidens, så en osäker gissning inte får slå över populationstron.
        """
        span = max(1e-9, 1.0 - NEUTRAL_PRESS)
        raw = 1.0 + (profile.press - NEUTRAL_PRESS) / span
        raw = max(0.25, min(4.0, raw))
        c = profile.confidence
        return 1.0 + c * (raw - 1.0)

    def to_dict(self) -> dict:
        return {
            "global_q": self.global_q,
            "players": {name: s.to_dict() for name, s in self.stats.items()},
        }
