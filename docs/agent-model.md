# Teknisk spec: agentmodell för Meier-simulatorn

Status: **fas 1 avtalad** (deterministisk policy-kärna + BASE). CFR är en senare
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

1. **Hon ser tärningarna och påstår.** Oftast påstår hon precis det tärningarna
   visar — det är säkert, för synar någon förlorar den som synade. Bara en
   tillräckligt billig högre bluff tar hon.
2. **Hon slår utan att titta.** Eftersom hon inte vet vad tärningarna visar tar
   hon minsta tillåtna höjning. På presshumör kan hon ta ett större kliv.
3. **Hon svarar på ett påstående.** Hon synar om chansen att vinna är tillräckligt
   stor, annars skickar hon vidare. Ett Meier-påstående synar hon alltid, annars tar
   rundan aldrig slut.
4. **Hon tvingas höja.** Hon väljer mellan att titta (och kunna påstå nära
   sanningen) eller påstå blint (och dölja information).

Det viktigaste: hon gör alltid exakt samma sak i samma läge. Slumpen finns bara
i tärningarna, aldrig i hennes beslut. Därför kan en match köras om med samma
resultat, och därför kan de andra agenterna jämföras mot henne och veta att
skillnaden beror på dem.

Hon är inte bäst, och det är meningen. Hon är en fast mätsticka som de andra
slår genom att lägga till sådant hon inte har: en egen profil, läsning av
motståndare och anpassning.

---

Målet är att kunna mäta **vilka taktiker som vinner Meier**, både speltekniskt
och mot motståndare med olika beteende. Därför är besluten **LLM:ens** och
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
Agent = LLM som spelar en person (risk, press, reading) inom spelets regler
```

| Parameter | Intervall | Betydelse |
|---|---:|---|
| `risk` | 0–1 | Hur mycket agenten offrar säkerhet för chansen att vinna mer |
| `press` | 0–1 | Hur ofta agenten bluffar, höjer eller pressar |
| `reading` | 0–1 | Hur mycket agenten använder motståndarnas tidigare beteende |

Parametrarna är **underlag för en personlighet**, inte indata till en formel. De
beskriver hur en människa brukar spela, och beskrivningen går in i prompten
(`meier/agents/personality.py`). Modellen får sedan spela som den personen.

Det är en medveten ändring. En tidigare version lät `BasePolicy` räkna fram
draget ur parametrarna och lät LLM:en formulera repliken. Då blev varje spelare
samma algoritm med olika konstanter, och `press` styrde ett påståendeval som modellen
aldrig fick påverka. Nu är måtten ett *underlag* — något att simulera en
verklig spelare med — och inte en dom över vad som är rätt drag.

### Ansvarsfördelning (lager)

| Lager | Ansvar | Deterministiskt? |
|---|---|---|
| **Regler** (`meier/legality.py`) | Räknar upp lagliga drag, avvisar olagliga | **Ja** |
| **Personlighet** (`meier/agents/personality.py`) | Beskriver spelaren i ord | **Ja** |
| **Sekreterare** (`meier/opponents.py`) | Bokför offentligt spel i siffror | **Ja** |
| **Läsare** (`meier/agents/reader.py`) | **LLM:en** tolkar siffrorna → motståndarprofil | Nej (profilen) |
| **Spelaren** (`meier/agents/strategic.py`) | **LLM:en väljer drag** bland de lagliga | Nej |

Tre saker hålls isär:

1. **Reglerna** — vilka påståenden och svar som är lagliga. Koden äger dem, och ett
   olagligt svar från modellen når aldrig bordet. Modellen får en omfrågning
   med besked om felet; sedan tar reservpolicyn över.
2. **Personligheten** — vem spelaren är, i ord. Parametrarna blir en människa
   att spela som, inte en tabell att räkna ur.
3. **Beslutet** — vad spelaren gör. Det är modellens.

Repliken — raden spelaren "säger" — är däremot **inte** modellens. Den byggs
lokalt ur draget (`StrategicAgent._say` och `_say_action`), så att modellen bara
behöver ta fram påståendet eller svaret. Modellen får alltså aldrig hitta på vad
spelaren säger, och ett JSON-svar med `"line"` ignoreras. Det håller repliken
kort, förutsägbar och fri från påhittade termer.

Konsekvensen är praktisk: en match kan köras **utan LLM** (`--no-llm`). Då faller
varje spelare tillbaka på `BasePolicy`, som väljer bland samma lagliga drag. Det
läget är deterministiskt och används av `axel` (den fasta mätstickan) samt av
tester som ska gå på millisekunder utan nätverk. Det är en **referens**, inte en
beskrivning av hur de andra spelarna fungerar.

---

## 2. Målet: förväntad överlevnad

**Meier har inga poäng per steg.** Det finns bara liv. Formeln

```
värde = E[poäng nästa steg] − λ · P(omedelbar utslagning)      ← FEL
```

är därför **fel** och används inte. Målet är i stället:

```
värde(drag) = förväntade kvarvarande liv för agenten efter draget
              − risk_vikt · P(agenten slås ut av draget)
```

- `E[kvarvarande liv]` är beräkningsbart ur den exakta sannolikhetsmodellen
  (avsnitt 3) och ställningen.
- `P(utslagning)` är sannolikheten att draget leder till att agenten förlorar
  sina sista liv. Den viktas av `risk`: högre `risk` → lägre `risk_vikt` → agenten
  tar större chans.

`E[kvarvarande liv]` är en approximation av vinstsannolikhet. Att beräkna
**vinstsannolikhet** exakt kräver att man modellerar hela resten av matchen
(framtida motståndare, framtida tärningar). Det är en senare förbättring; fas 1
använder förväntade liv, vilket är monotont relaterat till överlevnad.

---

## 3. Exakt sannolikhetsmodell

Tärningarna är avlånga. `rules.FACE_WEIGHTS` ger vikten per sida 1–6:
långsidorna 3–6 har vikten `DIE_ELONGATION` = 1,3 och ändsidorna 1–2 vikten 1,0.

### 3.0 Varför arean, och vad den kostar

`DIE_ELONGATION` är tärningens **längd delad med dess bredd**. Vikterna sätts
sedan som sidans area: ändytan har arean `w·w`, långytan `w·L`. Därför blir
viktförhållandet exakt `L/w` = 1,3. Modellen är alltså internt konsistent — den
gör vad den säger.

Men area är ett **val**, inte en fysikalisk lag. För en kropp som kastas
slumpmässigt och landar på en sida är den vanligaste modellen att sidans chans
följer dess **rymdvinkel** från masscentrum. Sidorna ligger på olika avstånd
från centrum, och en yta längre bort täcker en mindre rymdvinkel. För `L/w` =
1,3 ger rymdvinkelmodellen ett viktförhållande på **1,562**, inte 1,300.

Räknat på de två modellerna:

| Modell | Vikt 3–6 / 1–2 | P(21 Meier) |
|---|---:|---:|
| Kub | 1,000 | 5,56 % |
| Area (koden) | 1,300 | 3,86 % |
| Rymdvinkel, `L/w` = 1,3 | 1,562 | 2,94 % |

Skillnaden mellan area och rymdvinkel flyttar P(21) med ungefär en procentenhet.
Den är liten jämfört med steget från en kub, men den är större än
avrundningsfel.

Om man i stället vill att koden ska betyda "viktförhållande 1,3" och inte
"`L/w` = 1,3", är det ofarligt: då är 1,3 rätt tal, och formen är i stället
`L/w` ≈ 1,169. De två tolkningarna kan inte skiljas utan att mäta en riktig
tärning.

**Vad vi inte vet:** vilken modell som gäller för Meiers faktiska tärningar.
Area är vald för att den är enkel att förklara och kontrollera. Byter man modell
ska `FACE_WEIGHTS` ändras på ett ställe — `meier/rules.py` — och testerna i
`tests/test_session.py` säger till vad som går sönder.

Sannolikheten för ett utfall `v` (ett av de 21 talen) är

```
P(v) = Σ_{a,b : read_dice(a,b)=v}  w_a · w_b  /  (Σ w)²
```

Detta är **exakt** (inte skattat) och räknas en gång vid import. Tabellen
(`meier/policy.py`) är alltså en härledd konstant, inte en kalibrerad gissning.

### 3.1 Nyckeltabeller

`P(shown ≥ B)` är sannolikheten att tärningarna visar **minst** `B`. Om
någon synar påståendet `B` gäller: synaren förlorar när `shown ≥ B`, annars förlorar
hållaren. `L_win(B)` / `L_lose(B)` är förväntat antal liv som förloras i vardera
utfallet (Meier kostar dubbelt, på båda sidor).

| påstående | P(shown ≥ B) | L_win(B) | L_lose(B) | q*(B) |
|---|---:|---:|---:|---:|
| 21 – Meier | 0.0386 | 2.000 | 2.000 | 0.500 |
| 11 | 0.0579 | 1.000 | 1.667 | 0.625 |
| 22 | 0.0772 | 1.000 | 1.500 | 0.600 |
| 33 | 0.1098 | 1.000 | 1.351 | 0.575 |
| 44 | 0.1424 | 1.000 | 1.271 | 0.560 |
| 55 | 0.1750 | 1.000 | 1.221 | 0.550 |
| 66 | 0.2076 | 1.000 | 1.186 | 0.543 |
| 65 | 0.2728 | 1.000 | 1.141 | 0.533 |
| 64 | 0.3380 | 1.000 | 1.114 | 0.527 |
| 63 | 0.4032 | 1.000 | 1.096 | 0.523 |
| 62 | 0.4533 | 1.000 | 1.085 | 0.520 |
| 61 | 0.5035 | 1.000 | 1.077 | 0.518 |
| 54 | 0.5687 | 1.000 | 1.068 | 0.516 |
| 53 | 0.6339 | 1.000 | 1.061 | 0.515 |
| 52 | 0.6840 | 1.000 | 1.056 | 0.514 |
| 51 | 0.7342 | 1.000 | 1.053 | 0.513 |
| 43 | 0.7994 | 1.000 | 1.048 | 0.512 |
| 42 | 0.8495 | 1.000 | 1.045 | 0.511 |
| 41 | 0.8997 | 1.000 | 1.043 | 0.510 |
| 32 | 0.9498 | 1.000 | 1.041 | 0.510 |
| 31 | 1.0000 | 0.000 | 1.039 | 1.000 |

Två saker att lägga märke till:

- **Låga påståenden (54 och nedåt) syns aldrig.** `L_lose` ≈ 1,04 och `q*` ≈ 0,51: en syn
  är nästan alltid förlust. Detta syns också i loggarna (0 synar av 250 beslut
  vid påstående 54 och lägre).
- **Meier är speciellt.** `q* = 0,50` och båda sidor kostar 2 liv. Att syna Meier
  är break-even redan vid q = 0,5. Empiriskt synas Meier i 45,8 % av fallen.

---

## 4. De fyra besluten

Detta är kärnan, och den punkt där den ursprungliga specen var fel: **agenten
ser inte alltid sina egna tärningar.** Informationstillgången skiljer sig mellan
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
tillåtet om det är ett giltigt utfall (alla 21). Att påstå **under** `shown` är
tillåtet men oftast dåligt: påståendet är lätt att syna, och du blir hållare.

Parametrarna styr:

- **`press`** höjer sannolikheten att påstå över `shown` (bluffa).
- **`risk`** avgör hur nära `shown` agenten vågar ligga (lägre risk → närmare
  sanningen).

### Beslut 2 — Slå (ser dem inte)

Spelaren skakar en **ny** bägare och får inte lyfta locket. Det nya påståendet måste vara
strikt högre än det förra. Agenten vet alltså inte vad tärningarna visar — men
vet att **motståndaren** kommer att se dem vid en syn.

Policy: `decide_raise` lägger påståendet på en nivå som styrs av `press`. Låg
`press` väljer den **minsta lagliga höjningen** — den är säkrast, eftersom
chansen att tärningarna visar mindre än påståendet är som minst där. Hög `press` tar
ett språng uppåt: ett högre påstående är dyrare för motståndaren att syna, men också
större risk om det blir synat.

Formeln är `steps = round(press · (len(higher) − 1))`, så `press` = 1,0 kan
hoppa ända till Meier. Det är alltså **inte** en regel om att höjningen alltid
är ett steg — bara om att ett steg är minimum, och om att `press` väljer hur
långt över det lägsta lagliga påståendet.

Skilj detta från **beslut 1** (`decide_bid`), där spelaren *har* sett
tärningarna. Där är bluffen alltid **exakt ett steg** över det visade utfallet:
`min(higher_options(shown))`. Där finns ingen `press`-styrning, eftersom den
kalkylen (sann påståendenivå + ett steg) inte har någon motsvarighet när nivån är
okänd.

### Beslut 3 — Syna eller skicka (ser dem inte)

Här vet agenten **inte** vad tärningarna visar. Den kan bara använda:

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
`risk` sänker tröskeln (synar hellre); `reading` ersätter `q` med den
motståndarspecifika uppskattningen (avsnitt 6).

### Beslut 4 — Tvingad höjning (väljer själv)

Bägaren har gått ett helt varv. Tärningarna slås om. Agenten får titta eller
påstå blint.

Policy: jämför de två vägarna och välj den med högst `V`.

- **Titta** är bättre när de nya tärningarna är starka (du kan påstå nära
  sanningen och slippa risken).
- **Blint** är bättre när du ändå måste höja högt och tärningarna sannolikt är
  svaga — då slipper du ljuga med vetskap, och motståndaren får ingen
  läsvinst från din tvekan.

Beslutet fattas **utan att titta** (agenten väljer först, ser sedan). Det är
regelmässigt korrekt: valet är gjort innan locket lyfts.

---

## 5. q-modellen: BASE:s fasta tro

BASE är **icke-läsande**: den bygger ingen modell av enskilda motståndare. Men en
agent som överväger att syna måste anta **något** om sannolikheten att påståendet är
en bluff. Två ytterligheter är oanvändbara:

- Anta alltid en ärlig motståndare → syn förlorar alltid → BASE synar aldrig →
  matcher tar aldrig slut via syn.
- Anta slumpade tärningar → BASE synar allt över 62 → naivt mot en bluffare.

Nyckeln är att sannolikheten att en **syn vinner** inte är en enda siffra — den
**beror starkt på påståendenivån**. Mätt ur en färsk strategisk serie (500 matcher):

| påstående | P(synaren vinner) | | påstående | P(synaren vinner) |
|---|---|---|---|---|
| 66 | 0,19 | | 54 | 0,20 |
| 65 | 0,47 | | 44 | 0,21 |
| 64 | 0,43 | | 43 | 0,07 |
| 61 | 0,37 | | 41 | 0,06 |
| 21 (Meier) | 0,31 | | 32 | 0,04 |

Att bara ha en global `q` (ett enda tal) är därför **för grovt**: det gör att
BASE synar låga påståenden (där en syn nästan alltid förlorar) och skickar vidare höga
(där en syn nästan går jämnt upp). BASE har därför **en fryst tabell `CALL_PRIOR`
per påståendenivå**:

```
CALL_PRIOR[B] = P(synaren vinner | påstående = B)
```

- Tabellen är **global** — samma för alla motståndare (uppfyller "icke-läsande").
- Den **kalibreras mot färsk data** och **fryses** sedan under experimenten.
- Den används i beslut 3 som `P(vinst | B)`. Vid en läsning justeras den
  **relativt** (se avsnitt 6), aldrig genom att bytas ut mot ett absolut tal.

### 5.1 Kalibrering och frysning

`CALL_PRIOR[B]` skattas ur empirin som

```
P(vinst | B) ≈ antal påståenden på nivå B som var falska / antal synliga påståenden på nivå B
```

där **synliga påståenden** = `påstående` och `höja` som inte är blinda (blinda påståenden är inga
löften och räknas aldrig som bluffar). Skattningen **utjämnas mot tärningarnas
egen sannolikhet** (priorvikt 15) eftersom varje påståendenivå har begränsat underlag,
och sedan **fryses** den.

Två tal hör dit:

- `DEFAULT_Q = 0,586` — andelen synliga påståenden som är falska över hela populationen.
  Används som nämnare när en motståndares benägenhet mäts **relativt** populationen,
  och som förhandstro innan en spelare avslöjats.
- `CALL_PRIOR` — den påståendespecifika tabellen ovan.

Båda kalibrerades mot en **färsk** strategisk serie. Det gamla LLM-underlaget gav
`q ≈ 0,52` och Meier-vinst 0,53 — men strategiska agenter är **ärligare** (Meier
0,31), så den gamla tabellen gjorde BASE för synbenägen. Detta är precis varför
tabellen måste byggas om mot färsk data: se avsnitt 5.3.

**Frysningen är ett krav, inte en detalj.** Om `CALL_PRIOR` (eller BASE i övrigt)
förbättras medan AI-experimenten pågår, rör sig jämförelsepunkten, och "A3 blev
bättre över tid" kan lika gärna betyda att BASE blev sämre. BASE:s taktik och
tabellen låses därför innan profilerna mäts, och ändras inte under en serie.

### 5.2 Meier — ett dyrt påstående, inte ett påtvingat

Ett Meier-påstående har en egenhet i spelets mekanik: om ingen synar går bägaren ett
helt varv, och den som påstår får då slå om och börja en **ny runda** i stället för
att höja. En runda kan därför ta slut utan att någon förlorat ett liv.

BASE har **ingen regel** som tvingar fram en syn på Meier. Valet är ett vanligt
EV-val bland de tre lagliga svaren. Att Meier ändå syns i praktiken beror på
priset: att bära påståendet är dyrt, eftersom tärningarna oftast visar lägre och
hållaren då förlorar två liv. Hållarvärdet för Meier ligger kring −0,92 liv.
Att skicka vidare är alltså inte förbjudet — det är bara sämre.

Det är skillnaden mellan en **regel** och en **konsekvens**, och den är
avgörande för maskinen: en regel tar bort ett lagligt val, en konsekvens låter
värderingen styra. Samma sak gäller de andra två svaren.

**Terminering.** Utan tvångsregel måste termineringen vila på något annat.
Den gör det: påståendet är monotont stigande inom en runda, och varje höjning närmar
sig Meier. När Meier väl står på bordet är en syn så pass mycket bättre än att
lägga sig att den blir vald. Uppmätt över 200 matcher (1 804 rundor) slutade
**alla** rundor med en syn — ingen via Meier-varv. Motorn har dessutom ett
skyddsnät som tvingar fram en syn om en runda drar ut på tiden.

### 5.3 En ärlig konsekvens av designen

Med den påståendespecifika tabellen synar BASE **selektivt**: låga påståenden (≤ 54) skickas
vidare, höga påståenden (61–66) synas när EV går jämnt upp, och Meier syns eftersom
priset att bära det är så högt. Detta är starkare än både "syna allt" och "syna
aldrig", och BASE vinner ca 31 % mot de fyra preseterna (baslinje 20 %, fem
spelare). En läsande agent (högre `reading`) kan slå BASE genom att skjuta tron
**rätt** per motståndare.

BASE svarar alltså på ett påstående med **tre** lagliga val — syna, skicka vidare eller
slå — och värderar dem på samma skala (mitt förväntade livsöverskott). Vilket som
vinner beror på påståendet: låga påståenden inbjuder till att slå, mellanpåståenden till
att skicka vidare, höga påståenden till att syna. Det är spelets egen textur, inte en
pålagd regel.

---

## 6. Motståndarprofil (läsande agenter)

`reading` avgör hur mycket agenten låter en **motståndarprofil** styra sina
beslut. Arbetet är delat i två roller med skarp gräns:

- **Sekreteraren** (`OpponentTracker`) bokför vad som hänt vid bordet: antal påståenden,
  hur många som avslöjats genom en syn, hur många av dem som var lögner, hur
  spelaren svarat. Rena siffror, ingen tolkning.
- **Läsaren** (`OpponentReader`) tolkar siffrorna och sätter profilen. Här är
  **LLM:en** den som dömer — den avgör helt själv vad beteendet betyder
  ("bluffbenägen", "försiktig", "oförutsägbar").

Motståndarprofilen innehåller:

- `risk` – hur gärna motståndaren tar en osäker chans,
- `press` – hur ofta motståndaren bluffar och pressar,
- `predictability` – hur förutsägbar motståndaren är,
- `kind` – en kort etikett,
- `confidence` – hur säker uppskattningen är.

**Agenten får aldrig veta motståndarens verkliga parametrar** — bara gissa ur
offentligt beteende. Det är inte bara en konvention: sammanställningen byggs av
`OpponentTracker`, som per konstruktion bara tar emot offentliga händelser.

Utan LLM (utvärderingsläget) faller läsaren tillbaka på sekreterarens aritmetik,
så en match kan alltid spelas klart utan nätverk.

### 6.03 Konfidensen mäts i facit, inte i självförtroende

Agenterna får dra snabba slutsatser om varandra — det är meningen. Men de
**gissar**, och en gissning byggd på en enda syn är inte värd lika mycket som en
byggd på tjugo. Därför sätter bordets facit ett **tak** på hur säker bilden får
bli:

```
underlag = antal avgjorda synar vid bordet (alla spelare, hela matchen)
styrka   = underlag / (underlag + 3)
konfidens = min(LLM:ens egen konfidens, styrka)
```

Tre synar ger alltså styrka 0,50 — modellen får inte påstå sig vara mer än
halvsäker. Nio synar ger 0,75. Taket gäller även reservprofilen utan LLM.

Poängen är att konfidensen ska spegla **hur tidig gissningen är**, inte hur
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
> (risk 20 %, press 10 %, förutsägbarhet 90 %; gott underlag).

Översättningen är ren presentation — den påverkar aldrig ett beslut. Samma idé
används för spelarens **egen** kända karaktär i spelarlistan
(`describe_params`), så att "risk 25 % · press 25 %" blir "synar sällan,
bluffar sällan och läser motståndarna lite (risk 25 %, press 25 %, läsning 15 %)".

I webbappen syns motståndarbilderna i spelfliken under **Motståndarbilder**.
Rutan växer fram när agenterna får underlag och kan ändras när matchen fortsätter.

### 6.0 Hur profilen får användas: relativt, aldrig absolut

Detta är den subtilaste punkten i hela modellen. En läsande agent får **inte**
byta ut den påståendespecifika tron `CALL_PRIOR[B]` mot motståndarens *absoluta*
bluff-frekvens. Skälet:

- `CALL_PRIOR[41] ≈ 0,28`. Nästan ingen bluffar till ett lågt påstående.
- En motståndare som bluffar dubbelt så ofta som normalt har frekvens ≈ 1,2 —
  men det säger inget om **påståendenivån**. Sätter man in 1,2 (eller ens 0,4) som
  `P(vinst | 41)` synar agenten påståenden som nästan alltid är sanna, och förlorar.

Rätt konstruktion är en **relativ justering**: profilens benägenhet skalas in i
tabellen som en faktor kring 1,0. Faktorn är centrerad kring `press = 0,5` och
**dämpas av LLM:ens konfidens**, så en osäker gissning inte slår över
populationstron.

```
raw    = 1 + (profil.press − 0,5) / (1 − 0,5)      # 0,5 → 1,0; 0,9 → 1,8
faktor = 1 + profil.confidence · (raw − 1)         # osäker gissning → 1,0
signal = 1 + reading · (faktor − 1)                # agentens egen ovilja
P(vinst | B, spelare) = CALL_PRIOR[B] · signal
```

- `reading = 0` ger exakt `CALL_PRIOR[B]` (ingen läsning, oavsett motståndare).
- `reading = 1` ger motståndarens benägenhet fullt ut.
- Resultatet klipps vid 0,95 så ett litet urval inte kan slå över.

En spelare utan data bedöms som populationen (`press = 0,5`), så en läsande
agent drar aldrig för stora slutsatser ur litet underlag.

### 6.07 Risk: synbenägenheten styr hur mycket agenten bluffar

Samma relativa konstruktion används för `risk`, men med **omvänt tecken**. `press`
säger hur ofta motståndaren ljuger; `risk` säger hur ofta hon **synar**. En
motståndare som gärna synar gör varje bluff dyrare, så agenten ska bluffa mindre
mot henne.

```
raw    = 1 + (profil.risk − 0,5) / (1 − 0,5)       # 0,5 → 1,0; 0,9 → 1,8
faktor = 1 + profil.confidence · (raw − 1)
P(syn | påstående) = min(1, CALL_PRIOR_syn · faktor)
```

Faktorn går in i `BasePolicy.decide_bid(shown, opponent_factor=...)` och vidare
till `_p_called`, som räknar ut hur sannolikt det är att påståendet blir synat. Ett
högre `opponent_factor` gör bluffen mindre lönsam, och agenten lägger sig närmare
sanningen.

Mätt i ett kontrollerat läge (agent med full läsning mot en motståndare med känd
synfrekvens, 20 möjliga tärningsutfall):

| Motståndaren synar | Faktor | Agenten bluffar i |
|---|---|---|
| 5 % | 0,31 | 20 av 20 lägen |
| 19 % (normalt) | 0,93 | 14 av 20 lägen |
| 45 % | 1,93 | 5 av 20 lägen |

**Skalan måste vara relativ, inte absolut.** Den råa synfrekvensen ligger kring
19 % för alla roller. Sätter man in den rakt på 0–1-skalan (där 0,5 är neutral)
ser *varje* motståndare extremt försiktig ut, och agenten bluffar vilt mot alla.
Därför finns `POPULATION_CALL_RATE = 0,19` och `OpponentTracker.call_ratio()`:
ratio 1,0 betyder "synar som folk mest". Samma fälla som för `press` — se 6.0.

Båda faktorerna kan vara aktiva samtidigt. `press` justerar tron på att ett visst
påstående är sant (`_opponent_prior`), `risk` justerar chansen att påståendet blir synat
(`_p_called`). De rör alltså olika led i samma uträkning.

### 6.1 Den läckagefria regeln (obligatorisk)

Profilen får **aldrig** använda information som inte var offentlig vid
beslutstillfället. I synnerhet:

- **Bluffar kan bara räknas ur avslutade rundor**, där en syn avslöjade
  tärningarna. Den **pågående** rundan får aldrig bidra.
- Motståndarens **dolda tärningar** och **framtida drag** får aldrig ingå.
- Ett **blint påstående** är inget löfte och räknas aldrig som en bluff.

Anledningen är subtil men avgörande: `session.py` loggar `shown` (de faktiska
tärningarna) för varje påstående. Bygger man profilen ur hela loggen läcker framtiden
in i nuet — agenten "vet" då att ett påstående *var* en bluff, fast ingen kunde veta
det än. Det gör resultaten ogiltiga.

Modulen är byggd så att regeln **inte kan brytas av misstag**:
`OpponentTracker` tar emot enbart offentliga observationer via
`observe_bid`/`observe_decision`, och de faktiska tärningarna kommer in **bara**
via `reveal`, som motorn anropar *efter* att en syn avgjorts. Läsaren matas
därför bara med `tracker.evidence(...)` — aldrig med sessionens logg.

### 6.2 Invariant att testa

Vi kör om en match med motståndarnas dolda tärningar ändrade och verifierar att
agentens beslut vid varje beslutspunkt är **identiska**. Ändras de, läcker
information in. Testet är en del av fas 1.

---

## 7. BASE — den starka, icke-läsande referensagenten

BASE är en **stark, fryst, motståndaroberoende** referens. Den:

- maximerar **förväntad överlevnad/slutplacering** (avsnitt 2), inte poäng per steg,
- har en fast påståendespecifik tro `CALL_PRIOR` (avsnitt 5) och läser inte enskilda
  motståndare,
- **deltar i matcherna** och är samtidigt jämförelsenivå för AI-agenterna.

Att BASE deltar (inte bara räknar offline) ger interaktionseffekter: vi kan se om
en profil vinner för att den är bra, eller för att den stör BASE specifikt.

Skillnaden mellan en läsande profil och BASE är **exakt värdet av läsning**.

BASE:s egna parametrar är `risk = 0,5, press = 0,5, reading = 0,0`. Att `press`
inte är noll gör att BASE **också bluffar** när det lönar sig — en referens som
aldrig bluffar vore inte en realistisk motståndare.

### 7.1 Kalibrering: härled, validera

BASE:s *sannolikhetsmodell* härleds analytiskt ur `FACE_WEIGHTS` (avsnitt 3) — den
är exakt och behöver ingen data. Det som kalibreras mot data är den **påståendespecifika
tron `CALL_PRIOR`** och `DEFAULT_Q`. Ordningen är:

1. Härled den exakta sannolikhetsmodellen (görs i kod, en gång).
2. Kör en **färsk** serie med fixerade seeds och skatta `CALL_PRIOR[B]` per påståendenivå,
   utjämnad mot tärningarnas egen sannolikhet.
3. **Frys** `CALL_PRIOR`, `DEFAULT_Q` och BASE:s taktik.
4. Validera att BASE vinner över de fyra befintliga rollerna. Gör den inte det
   har vi hittat ett fel i härledningen — vilket är precis vad en kontrollgrupp
   ska avslöja. (Efter kalibreringen vinner BASE ca 31 % mot 20 % baslinje.)

**Varför färsk data och inte de gamla loggarna:** de 18 befintliga matcherna
spelades av LLM-personas, som bluffar mer (Meier 0,44–0,53) än de strategiska
agenterna (0,31). Kalibrerar man BASE mot dem blir den **för synbenägen** mot
strategiska motståndare och vinner sämre. Detta upptäcktes under fas 1 och är ett
konkret exempel på varför frysning + färsk kalibrering är ett krav.

---

## 8. Fallback och felvägar

- **Ogiltigt påstående från modellen:** motorn korrigerar (`_coerce_higher`,
  `_enforce_bid`). Policyn räknar alltid fram ett lagligt påstående, så inget olagligt
  påstående kan nå bordet.
- **Ingen höjning finns (påståendet är Meier):** `slå` är omöjligt. Policyn väljer
  `syna` eller `skicka` — och synar alltid (avsnitt 5.2).
- **Saknad motståndardata:** med för få observationer faller den läsande agenten
  tillbaka på `CALL_PRIOR`. `reading` skalar hur snabbt profilen får genomslag.
- **Tom historik (första rundan):** alla agenter spelar som BASE tills data finns.
- **LLM otillgänglig:** reservpolicyn tar över och väljer bland samma lagliga
  drag. Repliken blir mekanisk ("Jag säger 62."), och `corrected` sätts så att
  loggen visar att modellen inte svarade.

### 8.1 Fall: livelock när ingen synade

Symptom: matcher med flera agenter tog aldrig slut (9 999 passningar, 1 478
rundor) och avbröts först av en hård gräns. Orsak: med `q` strax under
syn-tröskeln synade **ingen** agent. påståendet nådde Meier, gick ett varv, och
den som påstår slog om och började en ny runda — utan att någon förlorade liv.

Åtgärd: Meier-regeln (avsnitt 5.2). Den är inte en heuristik utan en direkt följd
av spelets mekanik, och den gör terminering till en garanterad egenskap. Testet
`test_matches_always_terminate` låser den.

### 8.2 Fall: läsande agent blev för passiv

Symptom: en agent med hög `reading` skickade vidare **allt** och synade aldrig.
Orsak: `effective_q` kollapsade den påståendespecifika tron till ett enda tal. Mot en
motståndare som bedömdes "ärlig" (låg absolut frekvens) blev `P(vinst)` djupt
negativ för **alla** påstående — även höga, där en syn i själva verket går jämnt upp.

Åtgärd: relativ justering (avsnitt 6.0). Motståndarens benägenhet skalas in i
tabellen i stället för att ersätta den. Testet `test_a_reading_agent_still_calls`
låser den.

### 8.3 Fall: kvarglömd absolut läsning

Symptom: `cecilia` och `david` (hög `risk` + läsning) förlorade nästan alltid.
Orsak: samma absoluta läsning som 8.2 gjorde att de synade **låga** påstående, där
`CALL_PRIOR ≈ 0,05` och en syn nästan alltid förlorar.

Åtgärd: samma som 8.2 (relativ justering). Efter fixen ligger spelarna
balanserat i självspelning: se tabellen i avsnitt 9.

---

## 9. Spelarna i registret

Spelarna bor i `meier/agents/roster.py`. Namnen är **neutrala** med flit. En
värderande etikett som "Rackar-Rakel" säger åt modellen vem den *ska vara*, och
då spelar den en karikatyr i stället för att spela spelet — och det går inte att
veta om profilen vinner på sin taktik eller på sin etikett. Beteendet styrs av
explicita parametrar, aldrig av namnet.

| Namn | Roll | Risk | Press | Läsning | LLM | Kort beskrivning |
|---|---|---:|---:|---:|---|---|
| Axel | `axel` | 0,50 | 0,50 | 0,00 | nej | Basmodellen; fast mätsticka |
| Berit | `berit` | 0,25 | 0,25 | 0,15 | ja | Försiktig; påstår nära sanningen |
| Cecilia | `cecilia` | 0,50 | 0,45 | 0,50 | ja | Kalkylerande; läser motståndaren |
| David | `david` | 0,65 | 0,60 | 0,35 | ja | Djärv; pressar påståendet högre |

**Axel** är basmodellen (BASE): deterministisk, icke-läsande, utan LLM. Han är
den fasta mätstickan — de andra jämförs mot honom, och han får förlora ofta. Han
är avsiktligt "good enough", inte optimerad.

De tre LLM-spelarna är samma policykärna med **milda** profiler ovanpå.
Ingen av dem är så extrem som de gamla rollerna var. De historiska loggarna
visade att en extremt pressande profil (`press` ≈ 0,9) förlorade nästan varje
match, eftersom hög press bluffar in i synar. Profilerna grundas i
logganalysen (avsnitt 8): vinnaren skickar vidare oftare och synar sällan men
träffsäkert — därför ligger `press` lågt och `reading` högt hos de som ska läsa
spelet.

Värdena är **startpunkter**. De kalibreras när vi utvärderar tillsammans. En
självspelning utan LLM (200 matcher, fyra spelare, baslinje 25 %) gav:
Berit 28 %, Cecilia 29,5 %, Axel 23,5 %, David 19 %. Balansen är god nog för att
gå vidare — David är svagast, vilket är väntat med högst press.

---

## 10. Gränssnitt mot agenten

Vid varje beslutspunkt får agenten:

- aktuellt speltillstånd (runda, påstående, hållare, antal aktiva spelare),
- **egna tärningar endast när de är kända** (beslut 1 och 4-titta),
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

`confidence` loggas för analys men **påverkar inte draget** i fas 1 (draget ägs av
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
| 3 | Batchkörning + statistik per parameter (fixerade seeds, roterande start) | Nej |
| 4 | Web-UI för de nya profilerna | Nej |
| 5 | Kalibrering av presets och `q` mot färsk serie | Nej |
| senare | CFR / approximativ lösning som teoretisk baslinje | Nej |
