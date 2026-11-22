# Granskning: följer maskinen reglerna?

Kontroll gjord mot `docs/regler/meier-regler.md` och originalet
`docs/regler/meier-regler.pdf`. Varje punkt är mätt i körande kod, inte läst ur
källfilerna.

## Källan

PDF:en (en sida, 190 559 byte) lästes in och jämfördes med koden:

- Brödtexten är ordagrant samma regler som projektet redan utgick från.
  Inga skillnader i sak.
- Poängtabellen ligger som bild. Den lästes av och jämfördes rad för rad
  mot `rules.RANKING`: alla 21 rader stämmer, inklusive att 21 är Meier och
  att 31 är sämst.
- Stavning: PDF:en skriver Meier, inte "Mejer". Koden skrev redan Meier.
  Den nya regeltexten rättades till Meier.

## Sammanfattning

Maskinen följer reglerna på alla punkter som går att mäta. En avvikelse
finns, och den är ett strategival, inte ett regelbrott: den mekaniska policyn
påstår aldrig *lägre* än tärningarna, trots att reglerna tillåter det. Motorn
tillåter det, och LLM-agenten kan göra det.

## Punkt för punkt

| # | Regel | Status | Bevis |
|---|---|---|---|
| 1 | Högsta tärningen först: 2+5 blir 52 | ✅ | `read_dice(2,5) == 52` |
| 2 | Rangordningen exakt som tabellen | ✅ | `RANKING` identisk med tabellen, 21 värden |
| 3 | Meier är högst | ✅ | `compare(21,11) > 0`, `higher_options(21) == []` |
| 4 | Meier kostar dubbelt (påstående) | ✅ | `resolve_call(21,31).lives == 2` |
| 5 | Meier kostar dubbelt (visat) | ✅ | `resolve_call(43,21).lives == 2` |
| 6 | Vanligt påstående kostar ett liv | ✅ | `resolve_call(43,31).lives == 1` |
| 7 | Visar lägre än påståendet → den som påstår förlorar | ✅ | `resolve_call(52,43).caller_loses is False` |
| 8 | Visar samma → synaren förlorar | ✅ | `resolve_call(43,43).caller_loses is True` |
| 9 | Visar högre → synaren förlorar | ✅ | `resolve_call(43,52).caller_loses is True` |
| 10 | Tre liv, ute vid noll | ✅ | liv: 2 → 1 → 0, `out=True` vid noll |
| 11 | Sist kvar vinner | ✅ | 100 matcher, alltid minst en kvar |
| 12 | Skicka vidare behåller påstående och tärningar | ✅ | 3448 skicka-händelser, tärningarna oförändrade |
| 13 | Påståendet stiger strikt inom rundan | ✅ | 0 brott på 60 matcher |
| 14 | Bägaren till föregående aktiva spelare | ✅ | 1727/1727 kontroller (100 %) |
| 15 | Helt varv → måste höja | ✅ | 743 tvingade höjningar på 40 matcher |
| 16 | Meier-varv → slå om, ingen livsförlust | ✅ | `higher_options(21) == []`, mätt 0 av 1158 rundor |
| 17 | En runda slutar vid syn | ✅ | 0 rundor utan syn på 1158 |
| 18 | **Första påståendet får vara lägre än tärningarna** | ⚠️ | Motorn: ja. Policyn: nej. Se nedan. |
| 19 | **Skicka vidare är blint – tärningarna läcker inte** | ✅ | `decide()` tar `bid` och `lives`, aldrig tärningsvärdet. 4 anropsställen, 0 läckor. |

## Avvikelsen: lägre påståenden

Reglerna säger att första spelaren får säga "det sanna, ett högre eller ett
lägre" resultat. Bluffen går alltså åt båda hållen.

Motorn följer regeln. Ett lägre påstående accepteras:

```
Tärningarna visar 52, LLM säger 31  ->  accepterat påstående: 31
```

Den mekaniska policyn gör det aldrig. Av 21 möjliga utfall lägger
`BasePolicy` ett lägre påstående i 0 fall. Det finns ingen `lower_options` i `rules`, bara
`higher_options`.

Detta är ett strategival, inte ett regelbrott – maskinen *får* påstå lägre,
den *väljer* att inte göra det. Men det är värt att veta, eftersom:

- Mätningarna i `docs/om-meier.md` gäller en maskin som aldrig påstår under
  tärningarna.
- En mänsklig spelare kan påstå 31 på 52. Simulatorn gör det aldrig.
- LLM-agenten *kan* göra det, eftersom prompten tillåter det. LLM- och
  policy-spelare är alltså inte helt jämförbara.

Att göra om man vill täppa till det: antingen lägga till `lower_options` och
låta policyn välja ibland, eller skriva i `docs/om-meier.md` att simulatorn
medvetet avstår från lägre påståenden. Det senare är billigare och bör göras först.

## Så här återskapas mätningarna

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q
```

Siffrorna ovan kommer från 40–200 matcher med `make_players(["axel", "berit",
"cecilia", "david"])` och stigande `seed`. De är deterministiska.
