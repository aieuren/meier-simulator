"""Vaktar att README och koden beskriver samma spelare.

README drev iväg en gång: den beskrev rollerna "Ärlig-Adolf" och
"Rackar-Rakel" långt efter att registret bytt till Axel, Berit, Cecilia och
David. Exempelkommandona gick inte att köra. De här testerna läser README som
text och jämför mot registret, så glidningen upptäcks direkt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from meier.agents.roster import ROSTER
from meier.opponents import describe_params

README = Path(__file__).resolve().parent.parent / "README.md"


def _text() -> str:
    return README.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Radbrytningar i README ska inte kunna bryta en jämförelse."""
    return " ".join(text.split())


def test_readme_lists_exactly_the_registered_players():
    text = _text()
    for key, profile in ROSTER.items():
        assert f"`{key}`" in text, f"README saknar rollnyckeln {key}"
        assert profile.name in text, f"README saknar namnet {profile.name}"


def test_readme_has_no_dead_role_keys():
    """Gamla rollnamn får inte ligga kvar och se ut som om de fungerade."""
    text = _text()
    for dead in ("arling", "rackar", "kalkyl", "trygg"):
        assert dead not in text, f"README nämner den borttagna rollen '{dead}'"


def test_readme_parameters_match_the_roster():
    """Siffertabellen i README ska visa samma värden som registret."""
    text = _text()
    for profile in ROSTER.values():
        row = next(
            (ln for ln in text.splitlines() if ln.startswith(f"| `{profile.key}` |")),
            None,
        )
        assert row is not None, f"README saknar tabellrad för {profile.name}"
        cells = [c.strip() for c in row.split("|")[1:-1]]
        shown = cells[2:6]
        expected = [
            f"{profile.params.caution:.2f}".replace(".", ","),
            f"{profile.params.statistics:.2f}".replace(".", ","),
            f"{profile.params.unpredictability:.2f}".replace(".", ","),
            f"{profile.params.reading:.2f}".replace(".", ","),
        ]
        assert shown == expected, (
            f"{profile.name}: README visar {shown}, koden har {expected}"
        )


def test_readme_plain_language_matches_generated_text():
    """Klartextraderna ska vara den text som describe_params() faktiskt ger."""
    text = _flat(_text())
    for profile in ROSTER.values():
        expected = _flat(
            describe_params(
                profile.params.caution,
                profile.params.statistics,
                profile.params.unpredictability,
                profile.params.reading,
            )
        )
        assert expected in text, (
            f"README:s klartext för {profile.name} stämmer inte med koden. "
            f"Koden ger: {expected}"
        )


def test_readme_cli_examples_use_real_roles():
    """Varje --role och varje rollargument i README måste finnas i registret."""
    text = _text()
    for match in re.finditer(r"--role\s+(\w+)", text):
        assert match.group(1) in ROSTER, f"README använder okänd roll: {match.group(1)}"
    for match in re.finditer(r"meier\.cli play ([\w\s]+)", text):
        for word in match.group(1).split():
            assert word in ROSTER, f"README spelar med okänd roll: {word}"
    for match in re.finditer(r'"role":\s*"(\w+)"', text):
        assert match.group(1) in ROSTER, f"README-API-exempel: okänd roll {match.group(1)}"


def test_readme_links_to_the_full_model():
    assert "docs/agent-model.md" in _text()


# -- docs/om-meier-simulatorn.md: kompisversionen ---------------------------

OM_MEIER = README.parent / "docs" / "om-meier-simulatorn.md"
AGENT_MODEL = README.parent / "docs" / "agent-model.md"


def _om() -> str:
    return OM_MEIER.read_text(encoding="utf-8")


def test_om_meier_exists_and_is_linked_from_readme():
    assert OM_MEIER.is_file(), "docs/om-meier-simulatorn.md saknas"
    assert "docs/om-meier-simulatorn.md" in _text(), "README länkar inte till Om meier-simulatorn"


def test_om_meier_has_no_technical_installation_instructions():
    """Kompisversionen ska inte innehålla kommandon och installationssteg."""
    text = _om()
    for noise in ("pip install", "uvicorn", "pytest", "curl ", "export "):
        assert noise not in text, f"Om meier-simulatorn innehåller teknik: {noise!r}"


def test_om_meier_player_table_matches_the_roster():
    """Siffertabellen i Om meier-simulatorn ska visa samma parametrar som koden."""
    text = _om()
    for profile in ROSTER.values():
        row = next(
            (ln for ln in text.splitlines() if f"**{profile.name}**" in ln and "|" in ln),
            None,
        )
        assert row is not None, f"Om meier-simulatorn saknar tabellrad för {profile.name}"
        cells = [c.strip() for c in row.split("|")[1:-1]]
        for cell, value in zip(cells[1:5], (
            profile.params.caution,
            profile.params.statistics,
            profile.params.unpredictability,
            profile.params.reading,
        )):
            assert cell == f"{value:.2f}".replace(".", ","), (
                f"{profile.name}: Om meier-simulatorn visar {cell}, koden har {value}"
            )


def test_om_meier_describes_the_machine_not_its_results():
    """Om meier-simulatorn ska beskriva vad vi satt upp, inte vad simuleringarna gav.

    Mätvärden hör hemma i en rapport, inte i en beskrivning av maskinen. De
    åldras, de kräver en mätning för att verifieras, och de lockar till
    slutsatser om strategi som projektet inte är ute efter. Dokumentet får
    beskriva konstruktionen (vikter, trösklar, parametrar) men inte utfall
    (vinstfrekvens, blufffrekvens, synfrekvens, matchlängd).
    """
    text = _om()
    flat = _flat(text).lower()

    # Utfallstabeller: rubriker som sammanställer vad spelarna gjorde.
    for header in ("vinster", "bluffar i", "synar i"):
        assert header not in flat, (
            f"Om meier-simulatorn har en utfallstabell ({header!r}). Flytta mätvärden till "
            "en rapport – dokumentet ska beskriva maskinen."
        )

    # Mätvärdesmarkörer som bara hör hemma i en rapport.
    for marker in (
        "mätt över",
        "i snitt",
        "av 20 lägen",
        "av 20 utfall",
        "slumpmässig spelare skulle vinna",
        "ligger inom felmarginalen",
        "inga säkra slutsatser",
    ):
        assert marker not in flat, (
            f"Om meier-simulatorn innehåller mätvärdesmarkören {marker!r}. "
            "Dokumentet ska beskriva maskinen, inte resultaten."
        )

    # Ett påstående om vem som vinner mest/minst är en slutsats om utfall.
    for claim in ("vinner mest", "vinner minst", "förlorade nästan varje"):
        assert claim not in flat, f"Om meier-simulatorn drar en slutsats om utfall: {claim!r}"

    # Procenttal får bara stå i konstruktionsbeskrivningar: tärningarnas vikter,
    # läsningstaket och spelarnas parametrar. Utfall ur en spelad match hör inte
    # hit. Listan är skiftlägesokänslig så att "Arean" räknas som "area".
    allowed = (
        "avlång",
        "vanlig kub",
        "hur mycket får läsningen väga",
        "rymdvinkel",
        "area",
        "vikt",
    )
    for line in text.splitlines():
        if "%" not in line:
            continue
        low = line.lower()
        ok = line.strip().startswith("|") or any(ctx in low for ctx in allowed)
        assert ok, f"procenttal utan konstruktionssammanhang: {line!r}"


def test_om_meier_cumulative_dice_table_matches_the_rules():
    """Den kumulativa kolumnen ska räknas ur FACE_WEIGHTS, inte ur en kub.

    Kolumnen visar chansen att slå påståendet eller högre, eftersom det är
    synarens villkor: tärningarna ska nå upp till påståendet.
    """
    from meier import rules

    weights = dict(zip(range(1, 7), rules.FACE_WEIGHTS))

    def exact(value: int, w: dict[int, float]) -> float:
        total = sum(w.values()) ** 2
        hi, lo = divmod(value, 10)
        return w[hi] * w[lo] / total * (1 if hi == lo else 2)

    def cum(value: int, w: dict[int, float]) -> float:
        return sum(exact(v, w) for v in rules.RANKING if rules.compare(v, value) >= 0)

    kub = {i: 1.0 for i in range(1, 7)}
    text = _om()
    for value in rules.RANKING:
        label = "21 (Meier)" if value == 21 else str(value)
        row = next((ln for ln in text.splitlines() if ln.startswith(f"| {label} |")), None)
        assert row is not None, f"Om meier-simulatorn saknar raden {label}"
        cells = [c.strip() for c in row.split("|")[1:-1]]
        for cell, p in (
            (cells[1], exact(value, weights)),
            (cells[2], cum(value, weights)),
            (cells[3], cum(value, kub)),
        ):
            assert cell == f"{p * 100:.1f}".replace(".", ",") + " %", (
                f"{label}: dokumentet visar {cell}, koden ger {p * 100:.1f} %"
            )


def test_om_meier_explains_that_bluffing_comes_from_the_forced_raise():
    """Bluffens grund är tvånget att höja, inte psykologi.

    Dokumentet sa förut att en avslöjad bluff inte ger något, som om bluffen
    vore ett fritt val. I Meier måste varje påstående vara högre än det förra,
    så den som får tärningar under bordets nivå tvingas bluffa. Psykologin
    kommer ovanpå. Tabellen ska stämma med den regeln.
    """
    from meier import rules

    weights = dict(zip(range(1, 7), rules.FACE_WEIGHTS))
    total = sum(weights.values()) ** 2

    def p(v: int) -> float:
        hi, lo = divmod(v, 10)
        return weights[hi] * weights[lo] / total * (1 if hi == lo else 2)

    text = _om()
    flat = _flat(text).lower()

    for fel in (
        "en bluff som avslöjas ger dig alltså ingenting",
        "en bluff som avslöjas ger dig ingenting",
    ):
        assert fel not in flat, (
            f"Om meier-simulatorn säger {fel!r}. En bluff är ofta påtvingad av "
            "regeln att varje påstående måste vara högre."
        )

    assert "tvingas" in flat, "dokumentet ska säga att höjningstvånget tvingar fram bluffar"

    # Tabellen för tvingad bluff, avgränsad så att tärningstabellen inte blandas in.
    # Påståendet måste vara strikt högre, så även tärningar på bordets egen nivå
    # tvingar fram en bluff. Därför räknas "eller lägre".
    start = text.index("### Bluffen börjar med tvånget att höja")
    avsnitt = text[start : text.index("### Vad ett påstående kostar")]
    for prev in (43, 52, 63, 66):
        tvingad = sum(p(v) for v in rules.RANKING if rules.compare(v, prev) <= 0)
        rad = next(
            (ln for ln in avsnitt.splitlines() if ln.startswith(f"| {prev}")),
            None,
        )
        assert rad is not None, f"dokumentet saknar tvingad-bluff-raden {prev}"
        assert f"{tvingad * 100:.0f} %" in rad, (
            f"{rules.name(prev)}: dokumentet visar {rad!r}, koden ger {tvingad * 100:.0f} %"
        )


def test_om_meier_describes_axel_without_the_vague_phrase():
    """Axel ska beskrivas med vad som faktiskt gäller: fast räkneregel, ingen inlärning."""
    flat = _flat(_om()).lower()
    assert "spelar alltid likadant och ändrar sig aldrig" not in flat, (
        "Beskriv Axel konkret: fast räkneregel, lär sig inget om motståndarna"
    )
    assert "fast räkneregel" in flat, "dokumentet ska säga att Axel spelar en fast räkneregel"
    assert "lär sig inget" in flat, "dokumentet ska säga att Axel inte lär sig om motståndarna"


def test_om_meier_says_the_model_makes_the_move():
    """Kompisversionen ska beskriva arkitekturen som den är: modellen väljer draget.

    ``StrategicAgent`` låter LLM:en välja bland de lagliga dragen. En tidigare
    version av dokumentet sa motsatsen, att en gemensam beräkning tog beslutet
    och att modellen bara formulerade sig. Det stämde inte då och stämmer inte nu.
    """
    flat = _flat(_om()).lower()
    for fel in (
        "modellen får inte bestämma draget",
        "själva beslutet tas av en beräkning",
        "beräkning som är densamma för alla spelare",
    ):
        assert fel not in flat, (
            f"Om meier-simulatorn påstår {fel!r}. Modellen väljer draget i "
            "StrategicAgent; koden räknar bara upp de lagliga dragen."
        )
    assert "modellen bestämmer draget" in flat, (
        "Om meier-simulatorn måste säga att modellen bestämmer draget"
    )
    assert "repliken" in flat and "byggs i koden" in flat, (
        "Dokumentet ska skilja på draget (modellen) och repliken (koden)"
    )


def test_om_meier_dice_table_matches_the_rules():
    """Tärningstabellen ska stämma med FACE_WEIGHTS, inte med en kub."""
    from meier import rules

    weights = {i: w for i, w in zip(range(1, 7), rules.FACE_WEIGHTS)}
    total = sum(weights.values()) ** 2
    text = _om()
    for value, label in ((21, "21 (Meier)"), (11, "11"), (65, "65")):
        hi, lo = divmod(value, 10)
        p = weights[hi] * weights[lo] / total * (1 if hi == lo else 2)
        shown = f"{p * 100:.1f}".replace(".", ",") + " %"
        row = next((ln for ln in text.splitlines() if ln.startswith(f"| {label}")), None)
        assert row is not None, f"Om meier-simulatorn saknar tärningsraden {label}"
        assert shown in row, f"{label}: Om meier-simulatorn borde visa {shown}, fick {row}"


def test_agents_md_examples_use_real_roles():
    """Även AGENTS.md ska bara nämna roller som finns."""
    agents = README.parent / "AGENTS.md"
    if not agents.is_file():
        return
    text = agents.read_text(encoding="utf-8")
    for match in re.finditer(r"--role\s+(\w+)", text):
        assert match.group(1) in ROSTER, f"AGENTS.md använder okänd roll: {match.group(1)}"
    for match in re.finditer(r"meier\.cli play ([\w\s]+)", text):
        for word in match.group(1).split():
            assert word in ROSTER, f"AGENTS.md spelar med okänd roll: {word}"


def test_om_meier_bluffs_are_always_the_smallest_raise():
    """Dokumentet säger att en bluff läggs på minsta möjliga höjning.

    Stämmer det inte längre är resonemanget i "Spelaren väger risk mot vinst"
    fel, inte bara siffran.
    """
    from meier import rules
    from meier.agents.roster import make_rule_player

    # Påståendet gäller regelspelaren. En LLM-spelare väljer fritt bland de
    # lagliga påståendena och är inte bunden till minsta höjning.
    for key in ROSTER:
        agent = make_rule_player(key)
        for value in rules.RANKING:
            hi, lo = divmod(value, 10)
            claim = agent.announce((hi, lo)).claim
            if claim == value:
                continue
            smallest = rules.higher_options(value)[-1]
            assert claim == smallest, (
                f"{agent.name} bjöd {rules.name(claim)} på {rules.name(value)}, "
                f"men minsta höjning är {rules.name(smallest)}"
            )


def test_om_meier_round_terminology_matches_the_engine():
    """En runda tar slut vid syn, inte vid matchslut.

    Dokumentet säger: "En runda går från första påståendet till dess att någon
    synar." Testet spelar riktiga matcher och kontrollerar att varje runda
    slutar med en livsförlust (undantaget Meier-varvet, som startar en ny
    runda utan syn). Det fångar både feldelade rundor och en text som lovar
    fel slut på rundan.
    """
    from meier.agents.roster import make_players
    from meier.game import Game

    text = _om()
    assert "till dess att någon synar" in text, (
        "Om meier-simulatorn måste definiera att en runda slutar vid syn"
    )
    assert "En match är många rundor" in text, (
        "Om meier-simulatorn måste skilja runda från match"
    )

    rounds_without_call = 0
    total_rounds = 0
    for _ in range(40):
        players, _ = make_players(["axel", "berit", "cecilia", "david"])
        game = Game.new(players)
        game.play()
        for line in game.log:
            if line.startswith("Runda "):
                total_rounds += 1
            if "slår om och börjar ny runda" in line:
                rounds_without_call += 1

    assert total_rounds > 300, "för få rundor för att testet ska betyda något"
    # Meier-varvet är det enda undantaget, och det är sällsynt.
    assert rounds_without_call / total_rounds < 0.05, (
        f"{rounds_without_call} av {total_rounds} rundor slutade utan syn; "
        "då är 'en runda slutar vid syn' fel"
    )


REGLER = Path(__file__).resolve().parent.parent / "docs" / "regler" / "meier-regler.md"
GRANSKNING = Path(__file__).resolve().parent.parent / "docs" / "regler" / "granskning.md"


def test_regeltexten_finns():
    assert REGLER.exists(), "docs/regler/meier-regler.md saknas"
    text = _flat(REGLER.read_text(encoding="utf-8"))
    assert "regeltexten för Meier" in text
    assert "Sist kvar vinner" in text


def test_regeltextens_tabell_ar_identisk_med_rules_ranking():
    """Regeltabellen får inte glida ifrån koden."""
    from meier import rules

    text = REGLER.read_text(encoding="utf-8")
    # Hämta sifferraden ur tabellen, i ordning.
    rader = re.findall(r"^\|\s*\d+\s*\|\s*[⚀-⚅]\s*[⚀-⚅]\s*\|\s*\*{0,2}(\d{2})", text, re.M)
    assert rader, "kunde inte läsa poängordningen ur regeltabellen"
    assert [int(v) for v in rader] == list(rules.RANKING)


def test_regeltexten_namner_alla_tre_handlingar():
    text = _flat(REGLER.read_text(encoding="utf-8"))
    for handling in ("Slå", "Syna", "Skicka vidare"):
        assert handling in text, f"regeltexten saknar handlingen {handling}"


def test_regeltexten_tillater_lagre_forsta_bud():
    """Reglerna säger 'det sanna, ett högre eller ett lägre'."""
    text = _flat(REGLER.read_text(encoding="utf-8"))
    assert "lägre" in text
    assert "båda hållen" in text


def test_granskningen_redovisar_lagre_bud_avvikelsen():
    """Avvikelsen ska stå skriven, inte upptäckas på nytt varje gång."""
    assert GRANSKNING.exists(), "docs/regler/granskning.md saknas"
    text = _flat(GRANSKNING.read_text(encoding="utf-8"))
    assert "lägre" in text.lower()
    assert "strategival" in text.lower()


PDF = Path(__file__).resolve().parent.parent / "docs" / "regler" / "meier-regler.pdf"


def test_regel_pdf_finns_i_repot():
    assert PDF.exists(), "docs/regler/meier-regler.pdf saknas"
    assert PDF.stat().st_size > 50_000, "PDF:en ser trunkerad ut"


def test_regel_pdf_sager_samma_som_regeltexten():
    """PDF:en är originalet. Brödtexten ska stämma med den.

    Kräver pypdf. Saknas det hoppas testet över i stället för att falla, så att
    en mager testmiljö inte ger falskt larm.
    """
    pypdf = pytest.importorskip("pypdf")
    pdf_text = " ".join(" ".join(p.extract_text().split()) for p in pypdf.PdfReader(PDF).pages)
    flat = _flat(pdf_text)

    for regel in (
        "21 kallas Meier och är högst",
        "det sanna, ett högre värde eller ett lägre",
        "Den som slår måste alltså alltid påstå ett högre värde",
        "går bägaren till föregående spelare",
        "Meier kostar dubbelt",
        "Kommer bägaren ett helt varv tillbaka",
    ):
        assert regel in flat, f"PDF:en saknar regeln: {regel}"

    # PDF:en säger påstående, inte bud. Ordvalet är bestämt från 2026-11-24.
    assert "bud" not in flat.lower().replace("budget", "")
    # Ordningen i PDF:en är Syna, Slå, Skicka vidare – den ordningen gäller.
    syna = flat.index("Syna: lyfter locket")
    sla = flat.index("Slå: avstår från att syna")
    skicka = flat.index("Skicka vidare: skickar bägaren")
    assert syna < sla < skicka, "PDF:ens ordning mellan syna, slå och skicka har ändrats"

    # PDF:en skriver Meier. Felstavningen får inte smyga in i regeltexten.
    assert "Mejer" not in flat
    regler = REGLER.read_text(encoding="utf-8")
    assert "Mejer" not in regler, "regeltexten stavar Meier fel"


def test_regeltexten_lankar_till_pdf_originalet():
    """PDF:en är originalet, men dess text upprepas inte i regeltexten."""
    text = _flat(REGLER.read_text(encoding="utf-8"))
    assert "meier-regler.pdf" in text
    assert "Vid tvekan gäller" in text
    assert "PDF:ens ordalydelse" not in text


def test_tolkningarna_ar_fa_och_utan_kodnamn():
    """Bryggan i slutet ska vara kort och handla om spelet, inte om koden."""
    text = REGLER.read_text(encoding="utf-8")
    assert "Några tolkningar för denna simulator" in text, (
        "regeltexten behöver en kort brygga till simulatorn"
    )
    avsnitt = text[text.index("Några tolkningar för denna simulator") :]
    punkter = [ln for ln in avsnitt.splitlines() if ln.startswith("- ")]
    assert 2 <= len(punkter) <= 6, (
        f"bryggan har {len(punkter)} punkter; håll den kort"
    )
    for namn in ("DIE_ELONGATION", "rules.", ".py", "`claim`", "BasePolicy"):
        assert namn not in avsnitt, f"bryggan läcker implementationsdetaljen {namn}"


def test_skicka_vidare_ar_utan_titt_i_regeltext_och_prompt():
    """Att titta är att syna. Regeln ska stå i både regeltext och LLM-prompt."""
    regler = _flat(REGLER.read_text(encoding="utf-8"))
    assert "tittar inte på tärningarna" in regler
    assert "gratis syn" in regler

    from meier.agents.player import MeierPlayerAgent

    prompt = MeierPlayerAgent._decide_context(
        None, 52, [61, 62, 63, 64, 65, 66], 3
    )
    assert "Du ser inte tärningarna" in prompt


def test_om_meier_does_not_claim_raises_are_always_one_step():
    """Dokumentet får inte påstå att *alla* höjningar är ett steg.

    ``decide_claim`` (sedda tärningar) höjer exakt ett steg, men ``decide_raise``
    (utan att titta) skalar med ``unpredictability`` och kan hoppa ända till Meier. Ett
    påstående om att höjningen "alltid" är ett steg beskriver bara det första
    beslutet.
    """
    text = _om()
    flat = " ".join(text.split()).lower()
    for claim in (
        "höjningen är alltid ett steg",
        "alltid ett steg, aldrig flera",
        "alltid på den minsta möjliga höjningen",
    ):
        assert claim not in flat, (
            f"Om meier-simulatorn påstår {claim!r}. Minsta höjning gäller bluffen över sedda "
            "tärningar; den som valt bort titten styr höjningen med unpredictability."
        )


def test_agent_model_has_no_forced_meier_call_rule():
    """Agentmodellen får inte beskriva synen på Meier som en påtvingad regel.

    Meier syns för att det är dyrt att bära påståendet, inte för att en regel säger
    det. Dokumentet måste skilja på regel och konsekvens.
    """
    text = AGENT_MODEL.read_text(encoding="utf-8")
    flat = " ".join(text.split()).lower()
    for claim in (
        "meier synas alltid",
        "ett meier-påstående synas alltid",
        "obligatoriskt",
    ):
        assert claim not in flat, (
            f"agent-model.md påstår {claim!r}. Ingen regel tvingar fram en syn på "
            "Meier; valet styrs av hållarvärdet."
        )


def test_agent_model_describes_three_legal_responses():
    """Dokumentet ska räkna upp alla tre lagliga svar på ett påstående."""
    text = AGENT_MODEL.read_text(encoding="utf-8")
    flat = " ".join(text.split()).lower()
    for word in ("syna", "skicka vidare", "slå"):
        assert word in flat


def test_agent_model_does_not_claim_the_policy_makes_the_decisions():
    """Dokumentet får inte påstå att draget ägs av policyn.

    Arkitekturen är att LLM:en väljer bland de lagliga dragen och att koden bara
    avgör legaliteten. Ett dokument som säger motsatsen beskriver en äldre
    version och lurar den som läser.
    """
    text = AGENT_MODEL.read_text(encoding="utf-8")
    flat = " ".join(text.split()).lower()
    for claim in (
        "draget ägs helt av policyn",
        "draget som spelas ägs av policyn",
        "llm:en är persona och motivering, inte den som avgör draget",
    ):
        assert claim not in flat, (
            f"agent-model.md påstår {claim!r}. LLM:en fattar besluten; koden äger "
            "bara reglerna."
        )


def test_agent_model_names_the_legality_layer():
    """Dokumentet ska peka ut var reglerna bor."""
    text = AGENT_MODEL.read_text(encoding="utf-8")
    assert "meier/legality.py" in text


# -- Om meier-simulatorn: avsnittet om Axels speltaktik ---------------------

def test_axel_section_tables_match_the_policy():
    """Tabellerna om Axels speltaktik ska visa vad koden faktiskt gör.

    Avsnittet är skrivet för en människa, men siffrorna kommer ur ``BasePolicy``.
    Glider de isär är det dokumentet som ljuger, inte koden.
    """
    from meier import policy, rules

    text = _om()
    assert "### En spelare utan AI-inblandning" in text, (
        "Om meier-simulatorn saknar avsnittet om spelaren utan språkmodell"
    )

    axel = policy.BasePolicy(
        policy.AgentParams(caution=0.5, statistics=0.5, unpredictability=0.0, reading=0.0)
    )

    # Öppningspåståendet: tabellen säger att agenten säger vad tärningarna visar.
    for shown in rules.RANKING:
        claim = axel.decide_claim(shown).claim
        assert claim == shown, (
            f"tabellen påstår sanning på {rules.name(shown)}, koden säger {rules.name(claim)}"
        )

    # Svaren: tabellen delar in påståendena i syna / skicka / slå.
    for claim in (21, 11, 22, 33, 44, 55, 66, 65, 64):
        assert axel.decide_response(claim).action == "syna", f"koden synar inte {rules.name(claim)}"
    for claim in (63, 62, 61, 54, 53, 52, 51, 43, 42):
        assert axel.decide_response(claim).action == "skicka", f"koden skickar inte {rules.name(claim)}"
    for claim in (41, 32, 31):
        assert axel.decide_response(claim).action == "slå", f"koden slår inte på {rules.name(claim)}"

    # Slag utan att titta: alltid minsta lagliga höjning.
    for claim in (31, 32, 41, 42, 43, 51, 52, 53, 54, 61, 62, 63, 64, 65, 66):
        assert axel.decide_raise(claim).claim == rules.next_higher(claim), (
            f"koden höjer inte minimalt över {rules.name(claim)}"
        )


def test_axel_section_says_there_is_no_voluntary_bluff():
    """Avsnittet ska säga att Axel inte bluffar frivilligt.

    Han säger vad tärningarna visar. Lögn förekommer bara när regeln tvingar
    fram en höjning som tärningarna inte täcker. Texten måste stämma med koden.
    """
    from meier import policy, rules

    text = _om()
    flat = " ".join(text.split())

    axel = policy.BasePolicy(
        policy.AgentParams(caution=0.5, statistics=0.5, unpredictability=0.0, reading=0.0)
    )
    for shown in rules.RANKING:
        assert axel.decide_claim(shown).claim == shown, (
            f"koden påstår inte tärningarna på {rules.name(shown)}"
        )

    assert "säger vad tärningarna visar" in flat.lower(), (
        "Avsnittet förklarar inte att Axel säger tärningarnas värde."
    )
    # Det får inte stå kvar att han höjer ett steg på låga tärningar.
    for stale in (
        "Har du 43 eller lägre, säg ett steg över",
        "säger han ett steg över tärningarna",
    ):
        assert stale not in flat, f"Avsnittet beskriver fortfarande en frivillig bluff: {stale!r}"


def test_docs_say_the_shaker_may_always_look():
    """Reglerna låter spelaren lyfta på locket på sitt eget slag.

    Det får inte finnas en enda mening i dokumentationen som säger att den som
    slår är förbjuden att titta. Att avstå är ett eget val och ska beskrivas som
    fintaktik, inte som ett tvång.
    """
    from meier.agents.player import MeierPlayerAgent

    for path in (REGLER, OM_MEIER, AGENT_MODEL, README):
        flat = _flat(path.read_text(encoding="utf-8"))
        for forbud in (
            "får inte lyfta på locket",
            "får inte titta",
            "måste inte titta",
        ):
            assert forbud not in flat, f"{path.name} förbjuder titten: {forbud!r}"

    regler = _flat(REGLER.read_text(encoding="utf-8"))
    assert "får alltså alltid lyfta på locket och se sina egna tärningar" in regler
    assert "eget val" in regler

    # Prompten för själva slaget ska erbjuda titten.
    agent = MeierPlayerAgent.__new__(MeierPlayerAgent)
    shake = MeierPlayerAgent._shake_choice_context(agent, 44)
    assert "får lyfta på det" in shake
    assert "Valet är ditt" in shake


def test_unseen_prompt_says_the_choice_is_already_made():
    """Utan att titta ska prompten säga att spelaren redan valt bort titten.

    Annars läser modellen de två situationerna som samma och tror att den kan
    titta även när den redan avstått.
    """
    from meier.agents.player import MeierPlayerAgent

    unseen = MeierPlayerAgent._unseen_announce_context(None, 44, [51, 52, 53])
    assert "har valt att inte lyfta på locket" in unseen
    assert "Du har redan valt bort titten" in unseen


def test_ordet_bud_finns_inte_i_dokumentationen():
    """Spelet säger påstående. Det gamla ordet "bud" ska bort ur all prosa.

    "bjuda", "erbjuda", "inbjuda" och "förbjuda" är andra ord och rörs inte.
    """
    rot = Path(__file__).resolve().parent.parent
    falska = re.compile(r"\b(bjud\w*|erbjud\w*|inbjud\w*|förbjud\w*|utbjud\w*)\b", re.I)
    kvar = []
    for path in sorted(rot.glob("*.md")) + sorted(rot.glob("docs/**/*.md")):
        text = path.read_text(encoding="utf-8")
        # Historiska kodnamn i backticks är litterala och får stå kvar.
        text = re.sub(r"`[^`\n]*`", " ", text)
        text = falska.sub(" ", text)
        for match in re.finditer(r"\b(bud|budet|buden|buds|över bud)\b", text, re.I):
            rad = text.count("\n", 0, match.start()) + 1
            kvar.append(f"{path.relative_to(rot)}:{rad}: {match.group(0)}")
    assert not kvar, "ordet 'bud' finns kvar:\n" + "\n".join(kvar)


def test_koden_sager_pastaende_inte_bud():
    """Handlingsetiketten ska heta "påstå" i både motor, analys och UI."""
    rot = Path(__file__).resolve().parent.parent
    for rel in ("meier/session.py", "meier/match.py", "meier/policy.py", "meier/analysis.py"):
        text = (rot / rel).read_text(encoding="utf-8")
        assert '"bud"' not in text, f"{rel} använder fortfarande handlingsetiketten 'bud'"
    app_js = (rot / "meier/web/static/app.js").read_text(encoding="utf-8")
    assert 'e.action === "påstå"' in app_js


def test_axel_section_call_odds_are_real_numbers():
    """Texten säger att synen vinner i 96 fall av 100 på 11 och 65 på 64.

    Siffrorna ska komma ur ``CALL_ODDS``, inte ur lösa antaganden. Glider de
    isär ska testet falla.
    """
    from meier import policy

    text = _om()
    flat = " ".join(text.split())

    p11 = round(policy.CALL_ODDS[11].p_win * 100)
    p22 = round(policy.CALL_ODDS[22].p_win * 100)
    p64 = round(policy.CALL_ODDS[64].p_win * 100)

    assert f"vinner synen i {p11} fall av 100" in flat, (
        f"Texten anger inte att synen vinner i {p11} fall av 100 på 11."
    )
    assert f"vinner synen i {p22}" in flat, (
        f"Texten anger inte att synen vinner i {p22} fall på 22."
    )
    assert f"Vid 64 vinner synen fortfarande i {p64} fall av 100" in flat, (
        f"Texten anger inte att synen vinner i {p64} fall av 100 på 64."
    )


def test_axel_section_says_63_is_a_coin_flip():
    """63 ska beskrivas som i praktiken jämnt mellan syna och skicka."""
    from meier import policy, rules

    text = _om()
    flat = " ".join(text.split())

    axel = policy.BasePolicy(
        policy.AgentParams(caution=0.5, statistics=0.5, unpredictability=0.0, reading=0.0)
    )
    ev_call = policy.CALL_ODDS[63].ev_call(axel.belief(63)) + axel.inertia()
    hold = axel._hold_value(63)
    assert abs(ev_call - hold) < 0.002, (
        f"63 är inte längre ett gränsfall: syna {ev_call:+.4f} mot håll {hold:+.4f}"
    )
    assert "63 är i praktiken ett myntkast" in flat
    assert axel.decide_response(63).action == "skicka"
    assert rules.name(63) == "63"


def test_axel_section_marks_the_example_part_as_constructed():
    """Exempelpartiet ska stå som iscensatt.

    Alla tre spelarna följer Axels regel i exemplet, men i en riktig match
    fattar Berit och Cecilia sina beslut med en språkmodell. Utan den
    upplysningen läser man exemplet som en vanlig match.
    """
    flat = " ".join(_om().split())
    assert "Partiet nedan är iscensatt" in flat
    assert "Alla tre spelar efter Axels regel" in flat
    assert "i en riktig match fattar Berit och Cecilia sina beslut med en språkmodell" in flat


def test_axel_section_says_the_bluff_ban_is_a_design_choice():
    """Att Axel inte bluffar är ett val i konstruktionen, inte en upptäckt.

    Avsnittet får inte påstå att en bluff vore olönsam i största allmänhet.
    """
    flat = " ".join(_om().split())
    assert "Därför att vi byggde honom så" in flat
    assert "Bluffen" in flat and "bortvald i konstruktionen" in flat
    assert "inte upptäckt som olönsam" in flat


def test_axel_section_example_part_moves_match_the_policy():
    """Varje drag i exempelpartiet ska vara det regeln faktiskt väljer."""
    from meier import policy, rules

    axel = policy.BasePolicy(
        policy.AgentParams(caution=0.5, statistics=0.5, unpredictability=0.0, reading=0.0)
    )
    assert axel.decide_response(31).action == "slå"
    assert axel.decide_response(64).action == "syna"
    assert axel.decide_response(63).action == "skicka"
    assert axel.decide_claim(31, previous_claim=63).claim == 64
    # Runda 1: lika -> synaren förlorar. Runda 2: lägre -> påståendet förlorar.
    assert not rules.is_higher(64, 64)
    assert rules.is_higher(64, 31)
