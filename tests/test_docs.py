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
        risk, press, reading = cells[2], cells[3], cells[4]
        assert risk == f"{profile.params.risk:.2f}".replace(".", ","), (
            f"risk för {profile.name}: README {risk} mot kod {profile.params.risk}"
        )
        assert press == f"{profile.params.press:.2f}".replace(".", ",")
        assert reading == f"{profile.params.reading:.2f}".replace(".", ",")


def test_readme_plain_language_matches_generated_text():
    """Klartextraderna ska vara den text som describe_params() faktiskt ger."""
    text = _flat(_text())
    for profile in ROSTER.values():
        expected = _flat(
            describe_params(
                profile.params.risk, profile.params.press, profile.params.reading
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


# -- docs/om-meier.md: kompisversionen --------------------------------------

OM_MEIER = README.parent / "docs" / "om-meier.md"
AGENT_MODEL = README.parent / "docs" / "agent-model.md"


def _om() -> str:
    return OM_MEIER.read_text(encoding="utf-8")


def test_om_meier_exists_and_is_linked_from_readme():
    assert OM_MEIER.is_file(), "docs/om-meier.md saknas"
    assert "docs/om-meier.md" in _text(), "README länkar inte till Om Meier"


def test_om_meier_has_no_technical_installation_instructions():
    """Kompisversionen ska inte innehålla kommandon och installationssteg."""
    text = _om()
    for noise in ("pip install", "uvicorn", "pytest", "curl ", "export "):
        assert noise not in text, f"Om Meier innehåller teknik: {noise!r}"


def test_om_meier_player_table_matches_the_roster():
    """Siffertabellen i Om Meier ska visa samma parametrar som koden."""
    text = _om()
    for profile in ROSTER.values():
        row = next(
            (ln for ln in text.splitlines() if f"**{profile.name}**" in ln and "|" in ln),
            None,
        )
        assert row is not None, f"Om Meier saknar tabellrad för {profile.name}"
        cells = [c.strip() for c in row.split("|")[1:-1]]
        for cell, value in zip(cells[1:4], (
            profile.params.risk, profile.params.press, profile.params.reading
        )):
            assert cell == f"{value:.2f}".replace(".", ","), (
                f"{profile.name}: Om Meier visar {cell}, koden har {value}"
            )


def test_om_meier_describes_the_machine_not_its_results():
    """Om Meier ska beskriva vad vi satt upp, inte vad simuleringarna gav.

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
            f"Om Meier har en utfallstabell ({header!r}). Flytta mätvärden till "
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
            f"Om Meier innehåller mätvärdesmarkören {marker!r}. "
            "Dokumentet ska beskriva maskinen, inte resultaten."
        )

    # Ett påstående om vem som vinner mest/minst är en slutsats om utfall.
    for claim in ("vinner mest", "vinner minst", "förlorade nästan varje"):
        assert claim not in flat, f"Om Meier drar en slutsats om utfall: {claim!r}"

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
        "risk",
        "press",
    )
    for line in text.splitlines():
        if "%" not in line:
            continue
        low = line.lower()
        ok = line.strip().startswith("|") or any(ctx in low for ctx in allowed)
        assert ok, f"procenttal utan konstruktionssammanhang: {line!r}"


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
        assert row is not None, f"Om Meier saknar tärningsraden {label}"
        assert shown in row, f"{label}: Om Meier borde visa {shown}, fick {row}"


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
    from meier.agents.roster import make_player

    for key in ROSTER:
        agent = make_player(key)
        for value in rules.RANKING:
            hi, lo = divmod(value, 10)
            bid = agent.announce((hi, lo)).bid
            if bid == value:
                continue
            smallest = rules.higher_options(value)[-1]
            assert bid == smallest, (
                f"{agent.name} bjöd {rules.name(bid)} på {rules.name(value)}, "
                f"men minsta höjning är {rules.name(smallest)}"
            )


def test_om_meier_round_terminology_matches_the_engine():
    """En runda tar slut vid syn, inte vid matchslut.

    Dokumentet säger: "En runda är från första budet till dess att någon
    synar." Testet spelar riktiga matcher och kontrollerar att varje runda
    slutar med en livsförlust (undantaget Meier-varvet, som startar en ny
    runda utan syn). Det fångar både feldelade rundor och en text som lovar
    fel slut på rundan.
    """
    from meier.agents.roster import make_players
    from meier.game import Game

    text = _om()
    assert "till dess att någon **synar**" in text, (
        "Om Meier måste definiera att en runda slutar vid syn"
    )
    assert "En **match** är många rundor" in text, (
        "Om Meier måste skilja runda från match"
    )

    rounds_without_call = 0
    total_rounds = 0
    for seed in range(40):
        players, _ = make_players(["axel", "berit", "cecilia", "david"])
        game = Game.new(players, seed=seed)
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


def test_regeltexten_finns_och_ar_kanonisk():
    assert REGLER.exists(), "docs/regler/meier-regler.md saknas"
    text = _flat(REGLER.read_text(encoding="utf-8"))
    assert "kanoniska regeltexten" in text
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
        "det sanna, ett högre eller ett lägre",
        "Den som slår måste alltid säga ett högre bud",
        "går bägaren till föregående spelare",
        "Meier kostar dubbelt",
        "Kommer bägaren ett helt varv tillbaka",
    ):
        assert regel in flat, f"PDF:en saknar regeln: {regel}"

    # PDF:en skriver Meier. Felstavningen får inte smyga in i regeltexten.
    assert "Mejer" not in flat
    regler = REGLER.read_text(encoding="utf-8")
    assert "Mejer" not in regler, "regeltexten stavar Meier fel"


def test_regeltexten_citerar_pdf_ordalydelsen():
    text = _flat(REGLER.read_text(encoding="utf-8"))
    assert "PDF:ens ordalydelse" in text
    assert "meier-regler.pdf" in text
    assert "Vid tvekan gäller" in text


def test_skicka_vidare_ar_blint_i_regeltext_och_prompt():
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

    ``decide_bid`` (sedda tärningar) höjer exakt ett steg, men ``decide_raise``
    (blint) skalar med ``press`` och kan hoppa ända till Meier. Ett påstående om
    att höjningen "alltid" är ett steg beskriver bara det första beslutet.
    """
    text = _om()
    flat = " ".join(text.split()).lower()
    for claim in (
        "höjningen är alltid ett steg",
        "alltid ett steg, aldrig flera",
        "alltid på den minsta möjliga höjningen",
    ):
        assert claim not in flat, (
            f"Om Meier påstår {claim!r}. Minsta höjning gäller bluffen över sedda "
            "tärningar; blind höjning styrs av press."
        )


def test_agent_model_has_no_forced_meier_call_rule():
    """Agentmodellen får inte beskriva synen på Meier som en påtvingad regel.

    Meier syns för att det är dyrt att bära budet, inte för att en regel säger
    det. Dokumentet måste skilja på regel och konsekvens.
    """
    text = AGENT_MODEL.read_text(encoding="utf-8")
    flat = " ".join(text.split()).lower()
    for claim in (
        "meier synas alltid",
        "ett meier-bud synas alltid",
        "**obligatoriskt**",
    ):
        assert claim not in flat, (
            f"agent-model.md påstår {claim!r}. Ingen regel tvingar fram en syn på "
            "Meier; valet styrs av hållarvärdet."
        )


def test_agent_model_describes_three_legal_responses():
    """Dokumentet ska räkna upp alla tre lagliga svar på ett bud."""
    text = AGENT_MODEL.read_text(encoding="utf-8")
    flat = " ".join(text.split()).lower()
    for word in ("syna", "skicka vidare", "slå"):
        assert word in flat
