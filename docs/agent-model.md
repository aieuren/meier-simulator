# Teknisk spec: agentmodell för Meier-simulatorn

Status: fas 1 avtalad (deterministisk policy-kärna + BASE). CFR är en senare
fas och ingår inte här.

---

## BASE i korthet

BASE är spelets fasta måttstock — en motståndare som alltid spelar likadant:
lugn, nykter och utan minne. Hon har ingen egen profil, läser ingen enskild
spelare och ändrar sig aldrig. Hon har bara en enda fast gissning om hur ofta
folk i allmänhet bluffar.

Varje gång det är hennes tur väger hon två saker: hur sannolikt draget är att
hjälpa henne överleva, och hur stor risken är att hon åker ut direkt. Hon tar
det drag som väger tyngst, men är rädd om sina liv — ett drag som kan kosta ett
liv måste vara klart bättre än alternativen för att hon ska våga.

De fyra situationerna:

1. Hon ser tärningarna och påstår. Oftast påstår hon precis det tärningarna
   visar — det är säkert, för synar någon förlorar den som synade. Bara en
   tillräckligt billig högre bluff tar hon.
2. Hon slår utan att titta. Eftersom hon inte vet vad tärningarna visar tar
   hon minsta tillåtna höjning. Är hon oförutsägbar kan hon ta ett större kliv.
3. Hon svarar på ett påstående. Hon synar om chansen att vinna är tillräckligt
   stor, annars skickar hon vidare. Ett Meier-påstående synar hon alltid, annars tar
   rundan aldrig slut.
4. Hon tvingas höja. Hon väljer mellan att titta (och kunna påstå nära
   sanningen) eller påstå blint (och dölja information).

Det viktigaste: hon gör alltid exakt samma sak i samma läge. Slumpen finns bara
i tärningarna, aldrig i hennes beslut.

Hon är inte bäst, och det är meningen. Hon är en referens som de andra slår
genom att lägga till sådant hon inte har: en egen profil, läsning av
motståndare och anpassning. Kravet på henne är att taktiken saknar
språkmodell, inte att varje drag är reproducerbart ner på slumpnivå.

---

Målet är att kunna mäta vilka taktiker som vinner Meier, både speltekniskt
och mot motståndare med olika beteende. Därför är besluten LLM:ens och
reglerna kodens: modellen väljer fritt bland de lagliga dragen, och koden avgör
vilka drag som är lagliga. Ingen av dem gör den andras jobb.

Grundidén bygger på opponent modeling: en agent uppskattar motståndarens
beteende ur observerade handlingar och anpassar sitt val därefter
[Borghetti et al., 2009]. För LLM-agenter är strukturerade prompts med
spelregler, observation, historik och tillåtna drag en etablerad metod för att
göra besluten tolkbara och körbara [Suspicion-Agent, 2023].

---

## 1. Grundmodell

```
Agent = LLM som spelar en person (caution, statistics, unpredictability, reading)
```

| Parameter | Intervall | Betydelse |
|---|---:|---|
| `caution` | 0–1 | Hur gärna agenten undviker risk. Hög försiktighet höjer tröskeln för att syna |
| `statistics` | 0–1 | Hur mycket sannolikheterna får styra tron. Noll ger en enda fast tro |
| `unpredictability` | 0–1 | Hur mycket agenten varierar sitt spel för att vara svår att läsa |
| `reading` | 0–1 | Hur mycket motståndarnas tidigare beteende får styra |

Parametrarna är underlag för en personlighet, inte indata till en formel. De
beskriver hur en människa brukar spela, och beskrivningen går in i prompten
(`meier/agents/personality.py`). Modellen får sedan spela som den personen.

Bluffandet är **inte** en parameter. I Meier måste den som slår alltid höja över
det som står, så en del påståenden blir lögner vad spelaren än vill. Bluffen är
ett nödvändigt ont i spelet, inte en personlighetsegenskap att skruva på.

Det är en medveten ändring. En tidigare version lät `BasePolicy` räkna fram
draget ur parametrarna och lät LLM:en formulera repliken. Då blev varje spelare
samma algoritm med olika konstanter. Nu är måtten ett *underlag* — något att
simulera en verklig spelare med — och inte en dom över vad som är rätt drag.

### Ansvarsfördelning (lager)

| Lager | Ansvar | Deterministiskt? |
|---|---|---|
| **Regler** (`meier/legality.py`) | Räknar upp lagliga drag, avvisar olagliga | **Ja** |
| **Personlighet** (`meier/agents/personality.py`) | Beskriver spelaren i ord | **Ja** |
| **Sekreterare** (`meier/opponents.py`) | Bokför offentligt spel i siffror | **Ja** |
| **Läsare** (`meier/agents/reader.py`) | **LLM:en** tolkar siffrorna → motståndarprofil | Nej (profilen) |
| **Spelaren** (`meier/agents/strategic.py`) | **LLM:en väljer drag** bland de lagliga | Nej |

Tre saker hålls isär:

1. Reglerna — vilka påståenden och svar som är lagliga. Koden äger dem, och ett
   olagligt svar från modellen når aldrig bordet. Modellen får en omfrågning
   med besked om felet; sedan tar reservpolicyn över.
2. Personligheten — vem spelaren är, i ord. Parametrarna blir en människa
   att spela som, inte en tabell att räkna ur.
3. Beslutet — vad spelaren gör. Det är modellens.

Repliken — raden spelaren "säger" — är däremot inte modellens. Den byggs
lokalt ur draget (`StrategicAgent._say` och `_say_action`), så att modellen bara
behöver ta fram påståendet eller svaret. Modellen får alltså aldrig hitta på vad
spelaren säger, och ett JSON-svar med `"line"` ignoreras. Det håller repliken
kort, förutsägbar och fri från påhittade termer.

Konsekvensen är praktisk: en match kan köras utan LLM (`--no-llm`). Då faller
varje spelare tillbaka på `BasePolicy`, som väljer bland samma lagliga drag.
Det läget används av `axel` (referensen utan språkmodell) samt av tester som ska
gå på millisekunder utan nätverk. Det är en referens, inte en beskrivning av hur
de andra spelarna fungerar. Kravet på Axel är att taktiken inte innehåller någon
LLM — inte att varje drag är reproducerbart in i minsta slumpval.

---

## 2. Målet: förväntad överlevnad

Meier har inga poäng per steg. Det finns bara liv. Formeln

```
värde = E[poäng nästa steg] − λ · P(omedelbar utslagning)      ← FEL
```

är därför fel och används inte. Målet är i stället:

```
värde(drag) = förväntade kvarvarande liv för agenten efter draget
              − risk_vikt · P(agenten slås ut av draget)
```

- `E[kvarvarande liv]` är beräkningsbart ur den exakta sannolikhetsmodellen
  (avsnitt 3) och ställningen.
- `P(utslagning)` är sannolikheten att draget leder till att agenten förlorar
  sina sista liv. Den viktas av `caution`: högre `caution` höjer tröskeln för att
  ta en chans.

`E[kvarvarande liv]` är en approximation av vinstsannolikhet. Att beräkna
vinstsannolikhet exakt kräver att man modellerar hela resten av matchen
(framtida motståndare, framtida tärningar). Det är en senare förbättring; fas 1
använder förväntade liv, vilket är monotont relaterat till överlevnad.

---

## 3. Exakt sannolikhetsmodell

Tärningarna är avlånga. `rules.FACE_WEIGHTS` ger vikten per sida 1–6, och
vikterna räknas fram ur sidans rymdvinkel.

### 3.0 Rymdvinkeln

`DIE_ELONGATION` är tärningens längd delad med dess bredd: 1,3 mot 1,0.
Vikterna sätts efter hur stor rymdvinkel varje sida täcker från tärningens
masscentrum. Det är den vanligaste modellen för en kropp som kastas
slumpmässigt: sidorna ligger på olika avstånd från centrum, och en yta längre
bort täcker en mindre rymdvinkel och blir mindre sannolik.

För en rektangel med halva sidorna `a` och `b` på avståndet `d` är rymdvinkeln

```
Ω = 4·atan( a·b / (d·√(a² + b² + d²)) )
```

Ändytorna (1, 2) är `w` gånger `w` och ligger `L/2` från centrum. Långytorna
(3–6) är `w` gånger `L` och ligger `w/2` från centrum. Med `w` = 1 och `L` = 1,3
blir förhållandet mellan en långsida och en ändyta 1,5620. Vikterna är
normaliserade så att de summerar till 1.

Att areamodellen ger 1,3 rakt av är frestande enkelt, men den underskattar hur
mycket längden spelar in. Rymdvinkeln är den modell som gäller här.

| Modell | Vikt 3–6 / 1–2 | P(21 Meier) |
|---|---:|---:|
| Kub | 1,000 | 5,56 % |
| Area | 1,300 | 3,86 % |
| Rymdvinkel (koden) | 1,562 | 2,94 % |

Kuben är med bara som jämförelse: den visar hur mycket formen flyttar
sannolikheterna. Koden använder rymdvinkeln.

Vad vi inte vet: om Meiers faktiska tärningar har exakt längd 1,3. Vikterna
härleds ur `DIE_ELONGATION` i `meier/rules.py`, så en annan längd slår igenom
överallt utan att någon tabell behöver röras.

Sannolikheten för ett utfall `v` (ett av de 21 talen) är

```
P(v) = Σ_{a,b : read_dice(a,b)=v}  w_a · w_b  /  (Σ w)²
```

Detta är exakt (inte skattat) och räknas en gång vid import. Tabellen
(`meier/policy.py`) är alltså en härledd konstant, inte en kalibrerad gissning.

### 3.1 Nyckeltabeller

`P(shown ≥ B)` är sannolikheten att tärningarna visar minst `B`. Om
någon synar påståendet `B` gäller: synaren förlorar när `shown ≥ B`, annars förlorar
hållaren. `L_win(B)` / `L_lose(B)` är förväntat antal liv som förloras i vardera
utfallet (Meier kostar dubbelt, på båda sidor).

| påstående | P(shown ≥ B) | L_win(B) | L_lose(B) | q*(B) |
|---|---:|---:|---:|---:|
| 21 – Meier | 0.0294 | 2.000 | 2.000 | 0.500 |
| 11 | 0.0441 | 1.000 | 1.667 | 0.625 |
| 22 | 0.0588 | 1.000 | 1.500 | 0.600 |
| 33 | 0.0947 | 1.000 | 1.311 | 0.567 |
| 44 | 0.1305 | 1.000 | 1.225 | 0.551 |
| 55 | 0.1664 | 1.000 | 1.177 | 0.541 |
| 66 | 0.2023 | 1.000 | 1.145 | 0.534 |
| 65 | 0.2740 | 1.000 | 1.107 | 0.525 |
| 64 | 0.3457 | 1.000 | 1.085 | 0.520 |
| 63 | 0.4174 | 1.000 | 1.070 | 0.517 |
| 62 | 0.4634 | 1.000 | 1.063 | 0.515 |
| 61 | 0.5093 | 1.000 | 1.058 | 0.514 |
| 54 | 0.5810 | 1.000 | 1.051 | 0.512 |
| 53 | 0.6527 | 1.000 | 1.045 | 0.511 |
| 52 | 0.6987 | 1.000 | 1.042 | 0.510 |
| 51 | 0.7446 | 1.000 | 1.039 | 0.510 |
| 43 | 0.8163 | 1.000 | 1.036 | 0.509 |
| 42 | 0.8622 | 1.000 | 1.034 | 0.508 |
| 41 | 0.9082 | 1.000 | 1.032 | 0.508 |
| 32 | 0.9541 | 1.000 | 1.031 | 0.508 |
| 31 | 1.0000 | 0.000 | 1.029 | 1.000 |

Två saker att lägga märke till:

- Låga påståenden (54 och nedåt) är dyra att syna. `L_lose` ≈ 1,05 och
  `q*` ≈ 0,51: synaren måste tro att hållaren bluffar mer än hälften av gångerna
  för att synen ska löna sig.
- Meier är speciellt. `q* = 0,50` och båda sidor kostar 2 liv. Att syna Meier är
  break-even redan vid q = 0,5, eftersom dubbelstraffet slår åt båda håll.

---

## 4. De fyra besluten

Detta är kärnan, och den punkt där den ursprungliga specen var fel: agenten
ser inte alltid sina egna tärningar. Informationstillgången skiljer sig mellan
besluten.

| # | Beslut | Ser agenten sina tärningar? | Metod i koden |
|---|---|---|---|
| 1 | **Första påståendet** | **Ja** (tittat i smyg) | `announce()` |
| 2 | **Slå** (mot ett påstående) | **Nej** — nytt, stängt slag | `announce_blind()` |
| 3 | **Syna / skicka** | **Nej** — har inte tittat | `decide()` |
| 4 | **Tvingad höjning** | **Väljer själv**: titta eller blint | `announce_forced()` |

### Beslut 1 — Första påståendet (ser tärningarna)

Agenten ser `shown`. Den ska säga ett påstående. Två val: säga sanningen (`shown`) eller
ljuga (högre eller lägre).

Policy:

```
bästa_bud = argmax_B  V(B, shown)
```

där `V` är värdet i avsnitt 2, utvärderat över de tillåtna påståendena. Ett påstående är
tillåtet om det är ett giltigt utfall (alla 21). Att påstå under `shown` är
tillåtet men oftast dåligt: påståendet är lätt att syna, och du blir hållare.

Parametrarna styr:

- `unpredictability` gör att agenten ibland tar den säkra vägen även när en bluff
  räknas som marginellt bättre, så att mönstret inte går att läsa.
- `caution` höjer tröskeln för att syna, vilket gör bluffen billigare att komma
  undan med.

Bluffen i sig är inte en parameter. Vikten av att motståndaren lägger sig är den
fasta `BLUFF_GAIN`: ett påstående över `shown` jämförs med det säkra
grundpåståendet, och agenten tar bluffen när den räknas som lönsam.

### Beslut 2 — Slå (ser dem inte)

Spelaren skakar en ny bägare och får inte lyfta locket. Det nya påståendet måste vara
strikt högre än det förra. Agenten vet alltså inte vad tärningarna visar — men
vet att motståndaren kommer att se dem vid en syn.

Policy: `decide_raise` lägger påståendet på den minsta lagliga höjningen, som är
säkrast (minst chans att tärningarna visar lägre). En oförutsägbar agent hoppar
ibland högre ändå, just för att den inte ska gå att läsa: en motståndare som vet
att påståendet alltid är det minsta kan planera efter det.

```python
steps = rng.randint(1, len(higher) − 1)   # bara om rng.random() < unpredictability
new_bid = higher[−(steps + 1)]            # 0 steg = minsta höjningen
```

`unpredictability = 0` ger alltså alltid minsta lagliga höjning. Det finns ingen
parameter som väljer hur långt över det lägsta påståendet agenten går.

Skilj detta från beslut 1 (`decide_bid`), där spelaren *har* sett
tärningarna. Där är bluffen alltid exakt ett steg över det visade utfallet:
`min(higher_options(shown))`. Där finns ingen styrning alls, eftersom den
kalkylen (sann påståendenivå + ett steg) inte har någon motsvarighet när nivån är
okänd.

### Beslut 3 — Syna eller skicka (ser dem inte)

Här vet agenten inte vad tärningarna visar. Den kan bara använda:

- påståendet `B` som signal,
- sin tro på hur ofta `B` är en bluff,
- ställningen (egna liv, antal spelare kvar).

Detta är den svagaste punkten för en icke-läsande agent, och det är därför
`q`-modellen (avsnitt 5) behövs.

Policy:

```
syna om   P(bluff | B) · L_win(B)  >  (1 − P(bluff | B)) · L_lose(B)
```

Det vill säga: syna när förväntade livsöverskottet är positivt. Med den fasta
tron `P(bluff | B) = q` blir villkoret exakt `q > q*(B)` (tabellen i 3.1).
`caution` höjer tröskeln (synar mer sällan); `reading` ersätter `q` med den
motståndarspecifika uppskattningen (avsnitt 6).

### Beslut 4 — Tvingad höjning (väljer själv)

Bägaren har gått ett helt varv. Tärningarna slås om. Agenten får titta eller
påstå blint.

Policy: jämför de två vägarna och välj den med högst `V`.

- Titta är bättre när de nya tärningarna är starka (du kan påstå nära
  sanningen och slippa risken).
- Blint är bättre när du ändå måste höja högt och tärningarna sannolikt är
  svaga — då slipper du ljuga med vetskap, och motståndaren får ingen
  läsvinst från din tvekan.

Beslutet fattas utan att titta (agenten väljer först, ser sedan). Det är
regelmässigt korrekt: valet är gjort innan locket lyfts.

---

## 5. q-modellen: BASE:s fasta tro

BASE är icke-läsande: den bygger ingen modell av enskilda motståndare. Men en
agent som överväger att syna måste anta något om sannolikheten att påståendet är
en bluff. Två ytterligheter är oanvändbara:

- Anta alltid en ärlig motståndare → syn förlorar alltid → BASE synar aldrig →
  matcher tar aldrig slut via syn.
- Anta slumpade tärningar → BASE synar allt över 62 → naivt mot en bluffare.

Nyckeln är att sannolikheten att en syn vinner inte är en enda siffra — den
beror starkt på påståendenivån. Det följer direkt ur tärningarna: synaren vinner
om utfallet är *lägre* än påståendet, så

```
P(synaren vinner | B) = P(shown < B)
```

Kolumnen `P(shown ≥ B)` i tabellen i avsnitt 3 är komplementet. Där syns
formen: på 31 vinner synaren alltid, på 66 ungefär fyra gånger av fem, och på
Meier nästan aldrig — bara om tärningarna också visar Meier, och då förlorar
synaren två liv.

I en spelad serie är fördelningen ojämn: agenterna synar sällan på låga
påståenden, de skickar vidare eller slår över i stället. De nivåer som faktiskt
synas är därför få, och en mätning på dem säger mer om *vem som valde att syna*
än om tärningarna. Tabellen härleds därför ur `FACE_WEIGHTS`, inte ur en serie.

Att bara ha en global `q` (ett enda tal) är därför för grovt: det gör att
BASE synar låga påståenden (där en syn nästan alltid förlorar) och skickar vidare höga
(där en syn nästan går jämnt upp). BASE har därför en fryst tabell `CALL_PRIOR`
per påståendenivå:

```
CALL_PRIOR[B] = P(synaren vinner | påstående = B)
```

- Tabellen är global — samma för alla motståndare (uppfyller "icke-läsande").
- Den kalibreras mot färsk data och fryses sedan under experimenten.
- Den används i beslut 3 som `P(vinst | B)`. Vid en läsning justeras den
  relativt (se avsnitt 6), aldrig genom att bytas ut mot ett absolut tal.

### 5.1 Kalibrering och frysning

`CALL_PRIOR[B]` är en **halvvägs-sammandragning** mellan två tal: den
riskjusterade försiktiga nivån och tärningarnas sanna `P(shown < B)`. Den första
fångar att en förlorad syn kostar mer än en vunnen syn ger; den andra fångar
formen. Sammandragningen gör tabellen försiktigare än rå sannolikhet utan att
tappa kurvan.

Tabellen byggdes när tärningarna följde areamodellen. När `FACE_WEIGHTS` byttes
till rymdvinkelmodellen räknades den om med samma recept: areamodellens andel
bakas ut ur de gamla värdena, och rymdvinkelns sanna sannolikhet sätts in i
stället. Ändringen är liten (störst 0,009 på nivå 65) eftersom de två modellerna
ligger nära varandra, men den ska göras — annars bär tabellen kvar en
tärningsmodell som koden inte längre använder.

Två tal hör dit:

- `DEFAULT_Q = 0,715` — populationens bluff-frekvens bland **avslöjade**
  påståenden (frivilliga väger fullt, blinda halvt). Tvingade höjningar räknas
  aldrig, eftersom de är mekaniska för alla. Används som förhandstro innan en
  spelare avslöjats, och som nämnare när en motståndares benägenhet mäts relativt
  populationen. Observera att `bluff_ratio` delar med samma tal, så det absoluta
  värdet till stor del förkortas bort — det som spelar roll är förhållandet
  mellan spelaren och populationen.
- `CALL_PRIOR` — den påståendespecifika tabellen ovan.

`DEFAULT_Q` rördes inte av tärningarna: samma mätning ger 0,048 med areamodellen
och 0,040 med rymdvinkeln. Talet är alltså inte en tärningsrest, och det lämnas
fryst.

Ett närbesläktat tal är andelen överbud bland **alla** synliga påståenden
(omkring 0,52). Det är större än `DEFAULT_Q` därför att det räknar in de tvingade
höjningarna, som är överbud för alla. Används det som nämnare får varje normal
spelare ratio över 1,0, och en läsande agent synar i onödan.

Frysningen är ett krav, inte en detalj. Om `CALL_PRIOR` (eller BASE i övrigt)
förbättras medan AI-experimenten pågår, rör sig jämförelsepunkten, och "A3 blev
bättre över tid" kan lika gärna betyda att BASE blev sämre. BASE:s taktik och
tabellen låses därför innan profilerna mäts, och ändras inte under en serie.
Ett byte av tärningsmodell är ett undantag: då ändras förutsättningen för hela
spelet, och tabellen måste följa med.

### 5.2 Meier — ett dyrt påstående, inte ett påtvingat

Ett Meier-påstående har en egenhet i spelets mekanik: om ingen synar går bägaren ett
helt varv, och den som påstår får då slå om och börja en ny runda i stället för
att höja. En runda kan därför ta slut utan att någon förlorat ett liv.

BASE har ingen regel som tvingar fram en syn på Meier. Valet är ett vanligt
EV-val bland de tre lagliga svaren. Att Meier ändå syns i praktiken beror på
priset: att bära påståendet är dyrt, eftersom tärningarna oftast visar lägre och
hållaren då förlorar två liv. Hållarvärdet för Meier ligger kring −0,92 liv.
Att skicka vidare är alltså inte förbjudet — det är bara sämre.

Det är skillnaden mellan en regel och en konsekvens, och den är
avgörande för maskinen: en regel tar bort ett lagligt val, en konsekvens låter
värderingen styra. Samma sak gäller de andra två svaren.

Terminering. Utan tvångsregel måste termineringen vila på något annat.
Den gör det: påståendet är monotont stigande inom en runda, och varje höjning närmar
sig Meier. När Meier väl står på bordet är en syn så pass mycket bättre än att
lägga sig att den blir vald. Uppmätt över 200 matcher (1 855 livsförluster)
kom alla livsförluster ur en syn — ingen runda tog slut på annat sätt. Motorn har
dessutom ett skyddsnät som tvingar fram en syn om en runda drar ut på tiden.

### 5.3 En ärlig konsekvens av designen

Med den påståendespecifika tabellen synar BASE selektivt: låga påståenden (≤ 54) skickas
vidare, höga påståenden (61–66) synas när EV går jämnt upp, och Meier syns eftersom
priset att bära det är så högt. Detta är starkare än både "syna allt" och "syna
aldrig", och BASE vinner ca 32 % mot de fyra preseterna (baslinje 25 %, fyra
spelare). En läsande agent (högre `reading`) kan slå BASE genom att skjuta tron
rätt per motståndare.

BASE svarar alltså på ett påstående med tre lagliga val — syna, skicka vidare eller
slå — och värderar dem på samma skala (mitt förväntade livsöverskott). Vilket som
vinner beror på påståendet: låga påståenden inbjuder till att slå, mellanpåståenden till
att skicka vidare, höga påståenden till att syna. Det är spelets egen textur, inte en
pålagd regel.

---

## 6. Motståndarprofil (läsande agenter)

`reading` avgör hur mycket agenten låter en motståndarprofil styra sina
beslut. Arbetet är delat i två roller med skarp gräns:

- Sekreteraren (`OpponentTracker`) bokför vad som hänt vid bordet: antal påståenden,
  hur många som avslöjats genom en syn, hur många av dem som var lögner, hur
  spelaren svarat. Rena siffror, ingen tolkning.
- Läsaren (`OpponentReader`) tolkar siffrorna och sätter profilen. Här är
  LLM:en den som dömer — den avgör helt själv vad beteendet betyder
  ("bluffbenägen", "försiktig", "oförutsägbar").

Motståndarprofilen innehåller:

- `call_tendency` – hur ofta motståndaren synar,
- `bluff_tendency` – hur ofta motståndaren bluffar,
- `predictability` – hur förutsägbar motståndaren är,
- `kind` – en kort etikett,
- `confidence` – hur säker uppskattningen är.

Agenten får aldrig veta motståndarens verkliga parametrar — bara gissa ur
offentligt beteende. Det är inte bara en konvention: sammanställningen byggs av
`OpponentTracker`, som per konstruktion bara tar emot offentliga händelser.

Utan LLM (utvärderingsläget) faller läsaren tillbaka på sekreterarens aritmetik,
så en match kan alltid spelas klart utan nätverk.

### 6.03 Konfidensen mäts i facit, inte i självförtroende

Agenterna får dra snabba slutsatser om varandra — det är meningen. Men de
gissar, och en gissning byggd på en enda syn är inte värd lika mycket som en
byggd på tjugo. Därför sätter bordets facit ett tak på hur säker bilden får
bli:

```
underlag = antal avgjorda synar vid bordet (alla spelare, hela matchen)
styrka   = underlag / (underlag + 3)
konfidens = min(LLM:ens egen konfidens, styrka)
```

Tre synar ger alltså styrka 0,50 — modellen får inte påstå sig vara mer än
halvsäker. Nio synar ger 0,75. Taket gäller även reservprofilen utan LLM.

Poängen är att konfidensen ska spegla hur tidig gissningen är, inte hur
tvärsäker modellen råkar låta. Modellen får alltid be om 1,0; taket håller emot.

En session med en låtsas-LLM som ständigt svarar 1,0 visar kurvan:

| Synar vid bordet | Underlag | Konfidens |
|---|---|---|
| 0 | 0,00 | 0,00 |
| 1 | 0,25 | 0,25 |
| 3 | 0,50 | 0,50 |
| 5 | 0,62 | 0,62 |

Samma siffror skickas med i sammanställningen till modellen, så den vet hur tunt
underlaget är när den dömer.

### 6.05 Klartext för människan

Profilen är tekniska tal. För att en människa ska kunna läsa vad agenten *tror*
översätter `OpponentProfile.describe()` dem till en mening, med siffrorna kvar i
parentes:

> Försiktig: bluffar nästan aldrig, synar sällan och är mycket förutsägbar
> (bluff 10 %, syn 20 %, förutsägbarhet 90 %; gott underlag).

Översättningen är ren presentation — den påverkar aldrig ett beslut. Samma idé
används för spelarens egen kända karaktär i spelarlistan (`describe_params`), så
att en profil med hög försiktighet blir "Försiktig, håller sig till
sannolikheterna och varierar sig sällan; läser motståndarna lite (försiktighet
80 %, statistik 50 %, oförutsägbarhet 20 %, läsning 50 %)".

I webbappen syns motståndarbilderna i spelfliken under Motståndarbilder.
Rutan växer fram när agenterna får underlag och kan ändras när matchen fortsätter.

### 6.0 Hur profilen får användas: relativt, aldrig absolut

Detta är den subtilaste punkten i hela modellen. En läsande agent får inte
byta ut den påståendespecifika tron `CALL_PRIOR[B]` mot motståndarens *absoluta*
bluff-frekvens. Skälet:

- `CALL_PRIOR[41] ≈ 0,28`. Nästan ingen bluffar till ett lågt påstående.
- En motståndare som bluffar dubbelt så ofta som normalt har frekvens ≈ 1,2 —
  men det säger inget om påståendenivån. Sätter man in 1,2 (eller ens 0,4) som
  `P(vinst | 41)` synar agenten påståenden som nästan alltid är sanna, och förlorar.

Rätt konstruktion är en relativ justering: profilens benägenhet skalas in i
tabellen som en faktor kring 1,0. Faktorn är centrerad kring
`bluff_tendency = 0,5` och dämpas av LLM:ens konfidens, så en osäker gissning
inte slår över populationstron.

```
raw    = 1 + (profil.bluff_tendency − 0,5) / (1 − 0,5)   # 0,5 → 1,0; 0,9 → 1,8
faktor = 1 + profil.confidence · (raw − 1)               # osäker gissning → 1,0
signal = 1 + reading · (faktor − 1)                      # agentens egen ovilja
P(vinst | B, spelare) = CALL_PRIOR[B] · signal
```

- `reading = 0` ger exakt `CALL_PRIOR[B]` (ingen läsning, oavsett motståndare).
- `reading = 1` ger motståndarens benägenhet fullt ut.
- Resultatet klipps vid 0,95 så ett litet urval inte kan slå över.

En spelare utan data bedöms som populationen (`bluff_tendency = 0,5`), så en
läsande agent drar aldrig för stora slutsatser ur litet underlag.

### 6.07 Synbenägenheten styr hur mycket agenten bluffar

Samma relativa konstruktion används för `call_tendency`, men med omvänt tecken.
`bluff_tendency` säger hur ofta motståndaren ljuger; `call_tendency` säger hur
ofta hon synar. En motståndare som gärna synar gör varje bluff dyrare, så
agenten ska bluffa mindre mot henne.

```
raw    = 1 + (profil.call_tendency − 0,5) / (1 − 0,5)    # 0,5 → 1,0; 0,9 → 1,8
faktor = 1 + profil.confidence · (raw − 1)
P(syn | påstående) = min(1, CALL_PRIOR_syn · faktor)
```

Faktorn går in i `BasePolicy.decide_bid(shown, opponent_factor=...)` och vidare
till `_p_called`, som räknar ut hur sannolikt det är att påståendet blir synat. Ett
högre `opponent_factor` gör bluffen mindre lönsam, och agenten lägger sig närmare
sanningen.

Mätt i ett kontrollerat läge (agent med full läsning mot en motståndare med känd
synfrekvens, alla 21 tärningsutfall prövade):

| Motståndaren synar | Faktor | Agenten bluffar i |
|---|---|---|
| 5 % | 0,25 | 20 av 21 lägen |
| 26 % (normalt) | 1,00 | 16 av 21 lägen |
| 45 % | 1,70 | 8 av 21 lägen |

Skalan måste vara relativ, inte absolut. Den råa synfrekvensen ligger kring
26 % för alla roller. Sätter man in den rakt på 0–1-skalan (där 0,5 är neutral)
ser *varje* motståndare extremt försiktig ut, och agenten bluffar vilt mot alla.
Därför finns `POPULATION_CALL_RATE = 0,265` och `OpponentTracker.call_ratio()`:
ratio 1,0 betyder "synar som folk mest". Samma fälla som för `bluff_tendency` — se 6.0.

Båda faktorerna kan vara aktiva samtidigt. `bluff_tendency` justerar tron på att ett visst
påstående är sant (`_opponent_prior`), `call_tendency` justerar chansen att påståendet blir synat
(`_p_called`). De rör alltså olika led i samma uträkning.

### 6.1 Den läckagefria regeln (obligatorisk)

Profilen får aldrig använda information som inte var offentlig vid
beslutstillfället. I synnerhet:

- Bluffar kan bara räknas ur avslutade rundor, där en syn avslöjade
  tärningarna. Den pågående rundan får aldrig bidra.
- Motståndarens dolda tärningar och framtida drag får aldrig ingå.
- Ett blint påstående är inget löfte och räknas aldrig som en bluff.

Anledningen är subtil men avgörande: `session.py` loggar `shown` (de faktiska
tärningarna) för varje påstående. Bygger man profilen ur hela loggen läcker framtiden
in i nuet — agenten "vet" då att ett påstående *var* en bluff, fast ingen kunde veta
det än. Det gör resultaten ogiltiga.

Modulen är byggd så att regeln inte kan brytas av misstag:
`OpponentTracker` tar emot enbart offentliga observationer via
`observe_bid`/`observe_decision`, och de faktiska tärningarna kommer in bara
via `reveal`, som motorn anropar *efter* att en syn avgjorts. Läsaren matas
därför bara med `tracker.evidence(...)` — aldrig med sessionens logg.

### 6.2 Invariant att testa

Vi kör om en match med motståndarnas dolda tärningar ändrade och verifierar att
agentens beslut vid varje beslutspunkt är identiska. Ändras de, läcker
information in. Testet är en del av fas 1.

---

## 7. BASE — den starka, icke-läsande referensagenten

BASE är en stark, fryst, motståndaroberoende referens. Den:

- maximerar förväntad överlevnad/slutplacering (avsnitt 2), inte poäng per steg,
- har en fast påståendespecifik tro `CALL_PRIOR` (avsnitt 5) och läser inte enskilda
  motståndare,
- deltar i matcherna och är samtidigt jämförelsenivå för AI-agenterna.

Att BASE deltar (inte bara räknar offline) ger interaktionseffekter: vi kan se om
en profil vinner för att den är bra, eller för att den stör BASE specifikt.

Skillnaden mellan en läsande profil och BASE är exakt värdet av läsning.

BASE:s egna parametrar är `caution = 0,5, statistics = 0,5,
unpredictability = 0,2, reading = 0,0`. Att `unpredictability` inte är noll gör
att BASE också varierar sitt spel — en referens som spelar exakt samma drag varje
gång vore för lätt att läsa.

### 7.1 Kalibrering: härled, validera

BASE:s *sannolikhetsmodell* härleds analytiskt ur `FACE_WEIGHTS` (avsnitt 3) — den
är exakt och behöver ingen data. Det som kalibreras mot data är den påståendespecifika
tron `CALL_PRIOR` och `DEFAULT_Q`. Ordningen är:

1. Härled den exakta sannolikhetsmodellen (görs i kod, en gång).
2. Skatta `CALL_PRIOR[B]` per påståendenivå, utjämnad mot tärningarnas egen
   sannolikhet — så att tabellen följer den tärningsmodell koden använder.
3. Frys `CALL_PRIOR`, `DEFAULT_Q` och BASE:s taktik.
4. Validera att BASE vinner över de fyra befintliga rollerna. Gör den inte det
   har vi hittat ett fel i härledningen — vilket är precis vad en kontrollgrupp
   ska avslöja. (Efter kalibreringen vinner BASE ca 32 % mot 25 % baslinje.)

Varför färsk data och inte de gamla loggarna: de 18 befintliga matcherna
spelades av LLM-personas, som bluffar mer (Meier 0,44–0,53) än de strategiska
agenterna. Kalibrerar man BASE mot dem blir den för synbenägen mot
strategiska motståndare och vinner sämre. Detta upptäcktes under fas 1 och är ett
konkret exempel på varför frysning + färsk kalibrering är ett krav.

---

## 8. Fallback och felvägar

- Ogiltigt påstående från modellen: motorn korrigerar (`_coerce_higher`,
  `_enforce_bid`). Policyn räknar alltid fram ett lagligt påstående, så inget olagligt
  påstående kan nå bordet.
- Ingen höjning finns (påståendet är Meier): `slå` är omöjligt. Policyn väljer
  `syna` eller `skicka` — och synar alltid (avsnitt 5.2).
- Saknad motståndardata: med för få observationer faller den läsande agenten
  tillbaka på `CALL_PRIOR`. `reading` skalar hur snabbt profilen får genomslag.
- Tom historik (första rundan): alla agenter spelar som BASE tills data finns.
- LLM otillgänglig: reservpolicyn tar över och väljer bland samma lagliga
  drag. Repliken blir mekanisk ("Jag säger 62."), och `corrected` sätts så att
  loggen visar att modellen inte svarade.

### 8.1 Fall: livelock när ingen synade

Symptom: matcher med flera agenter tog aldrig slut (9 999 passningar, 1 478
rundor) och avbröts först av en hård gräns. Orsak: med `q` strax under
syn-tröskeln synade ingen agent. påståendet nådde Meier, gick ett varv, och
den som påstår slog om och började en ny runda — utan att någon förlorade liv.

Åtgärd: Meier-regeln (avsnitt 5.2). Den är inte en heuristik utan en direkt följd
av spelets mekanik, och den gör terminering till en garanterad egenskap. Testet
`test_matches_always_terminate` låser den.

### 8.2 Fall: läsande agent blev för passiv

Symptom: en agent med hög `reading` skickade vidare allt och synade aldrig.
Orsak: `effective_q` kollapsade den påståendespecifika tron till ett enda tal. Mot en
motståndare som bedömdes "ärlig" (låg absolut frekvens) blev `P(vinst)` djupt
negativ för alla påstående — även höga, där en syn i själva verket går jämnt upp.

Åtgärd: relativ justering (avsnitt 6.0). Motståndarens benägenhet skalas in i
tabellen i stället för att ersätta den. Testet `test_a_reading_agent_still_calls`
låser den.

### 8.3 Fall: kvarglömd absolut läsning

Symptom: `cecilia` och `david` (hög `reading` + synbenägen motståndarbild) förlorade nästan alltid.
Orsak: samma absoluta läsning som 8.2 gjorde att de synade låga påstående, där
`CALL_PRIOR ≈ 0,05` och en syn nästan alltid förlorar.

Åtgärd: samma som 8.2 (relativ justering). Efter fixen ligger spelarna
balanserat i självspelning: se tabellen i avsnitt 9.

---

## 9. Spelarna i registret

Spelarna bor i `meier/agents/roster.py`. Namnen är neutrala med flit. En
värderande etikett som "Rackar-Rakel" säger åt modellen vem den *ska vara*, och
då spelar den en karikatyr i stället för att spela spelet — och det går inte att
veta om profilen vinner på sin taktik eller på sin etikett. Beteendet styrs av
explicita parametrar, aldrig av namnet.

| Namn | Roll | Förs. | Stat. | Oförut. | Läsn. | LLM | Kort beskrivning |
|---|---|---:|---:|---:|---:|---|---|
| Axel | `axel` | 0,50 | 0,50 | 0,20 | 0,00 | nej | Grundtaktiken; referens utan LLM |
| Berit | `berit` | 0,50 | 0,50 | 0,20 | 0,00 | ja | Samma taktik som Axel, men med språkmodell |
| Cecilia | `cecilia` | 0,80 | 0,50 | 0,20 | 0,50 | ja | Försiktig; undviker risk |
| David | `david` | 0,50 | 0,80 | 0,20 | 0,50 | ja | Statistisk; håller sig till sannolikheterna |
| Elsa | `elsa` | 0,50 | 0,50 | 0,80 | 0,50 | ja | Oförutsägbar; varierar sitt spel |

Axel är basmodellen (BASE): icke-läsande och utan LLM. Han är referensen — de
andra jämförs mot honom, och han får förlora ofta. Han är avsiktligt "good
enough", inte optimerad. Hans taktik innehåller ingen språkmodell; däremot
behöver hans enskilda drag inte vara reproducerbara ner på slumpnivå.

Berit spelar exakt samma taktik som Axel. Skillnaden är bara att hennes beslut
fattas av en språkmodell i stället för direkt av kärnan. Paret Axel/Berit mäter
alltså värdet av språkmodellen och inget annat.

Cecilia, David och Elsa är samma kärna med **en** dimension lyft var, och samma
läsförmåga. Deras inbördes jämförelse handlar därför bara om den dimension de
lyfter: försiktighet, statistik eller oförutsägbarhet.

Värdena är startpunkter. De kalibreras när vi utvärderar tillsammans. En
självspelning utan LLM (400 matcher, fem spelare, baslinje 20 %) gav:
Axel 31 %, Berit 28 %, Cecilia 22 %, David 19 %. Siffrorna gäller de fem
nuvarande profilerna, med Axel och Berit på samma parametrar.

---

## 10. Gränssnitt mot agenten

Vid varje beslutspunkt får agenten:

- aktuellt speltillstånd (runda, påstående, hållare, antal aktiva spelare),
- egna tärningar endast när de är kända (beslut 1 och 4-titta),
- senaste annonserade värde,
- antal aktiva spelare,
- tillgängliga drag (lagliga påståenden),
- begränsad, läckagefri historik om motståndarnas tidigare beteende.

Agenten returnerar ett strukturerat svar:

```json
{
  "action": "raise",
  "claimed_value": 51,
  "confidence": 0.7,
  "reason": "Motståndaren har ofta accepterat höga anspråk."
}
```

`confidence` loggas för analys men påverkar inte draget i fas 1 (draget ägs av
policyn). `reason` är LLM:ens fritext och sparas som `reasoning` i loggen.

---

## 11. Källor

- Borghetti m.fl.: opponent modeling och värdet av motståndarinformation i spel.
- Suspicion-Agent: strukturerade prompts för LLM-agenter i
  ofullständig-informationsspel.

*(Borghetti-referensen verifieras mot originalet innan den skrivs in i en
publicerad text; Suspicion-Agent = Guo et al., 2023.)*

---

## 12. Faser

| Fas | Innehåll | LLM behövs? |
|---|---|---|
| **1** | Exakt sannolikhetsmodell, BASE, parametrar + presets, läckagefri motståndarmodell | Nej |
| 2 | LLM-lager: persona, `reasoning`, A1–A4 i prompten; LLM:en väljer draget | Ja |
| 3 | Batchkörning + statistik per parameter (roterande start) | Nej |
| 4 | Web-UI för de nya profilerna | Nej |
| 5 | Kalibrering av presets och `q` mot färsk serie | Nej |
| senare | CFR / approximativ lösning som teoretisk baslinje | Nej |
