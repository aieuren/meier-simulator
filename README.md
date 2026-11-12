# Mejer – LLM-baserade AI-spelare

En webapplikation och ett Python-bibliotek med **oberoende, LLM-baserade
AI-agenter** som spelar tärningsspelet **Mejer** (också kallat Mia, Mire,
Kuriki och Kunito).

Fokus för första versionen: en agent som simulerar en spelare. Givet utfallet av
ett tärningsslag med två tärningar bestämmer agenten hur spelaren svarar – den
säger sanningen, ett högre eller ett lägre resultat. Fler agenter med olika
roller kan spela hela spel mot varandra.

## Vad som finns

- **Webbapp med fem flikar:**
  - **Spelarna** – de fyra spelarna och deras karaktärsbeskrivningar.
  - **Enskild spelare** – skriv in tärningsutfallet (två tärningar) och se spelarens svar.
  - **Fyra spelare** – fyra spelare spelar mot varandra i ett fullt flöde fram till en syn.
  - **Matchserie** – kör många matcher och få statistik + ett JSONL-protokoll för analys.
  - **Analys** – ladda upp en eller flera JSONL-filer och ställ frågor mot materialet.
    Svaren kommer från en LLM och kan innehålla diagram (stapel, linje eller tabell).
- **Fyra spelarroller** – Ärlig-Adolf, Rackar-Rakel, Kalkylerande-Karin och Trygge-Tor.
- **Interaktiv spelsession** – fyra spelare spelar mot varandra i ett fullt flöde
  fram till en syn. Slumpen avgör ordningen och vem som börjar. Varje steg
  bekräftas med **Ett drag**, eller så körs flödet vidare med **Till syn**
  eller **Till slut på runda**. Varje svar sparas i en logg.
- **Matchserie och statistik** – spela N matcher mellan rollerna, se vinstfrekvens,
  bluffrekvens, höjningar och synar, och ladda ner hela protokollet som JSONL.
- **Spelmotor** – flera oberoende agenter spelar ett fullt Mejer-spel mot varandra.
- **Kommandoradsgränssnitt** – kör agenten, en session eller ett helt spel.
- **Regelmotor** – fullständig poängordning, budjämförelse, syn-avgörande och
  slumpade tärningsslag.

## Regler (sammanfattning)

- Två tärningar läses som ett tal med den högsta tärningen först: 2 och 5 blir 52.
- 21 kallas **Mejer** och är högst. Sedan faller ordningen ner till 31 (lägst).
- Spelaren skakar, tittar i smyg och säger ett resultat: sant, högre eller lägre.
- Nästa spelare kan **Slå** (säga ett högre bud), **Syna** (lyfta locket) eller
  **Skicka vidare** (samma bud).
- Vid syn: visar tärningarna lägre än budet förlorar budgivaren ett liv. Visar de
  samma eller högre förlorar den som synade ett liv.
- **Mejer kostar dubbelt** – om budet är Mejer, eller om tärningarna visar Mejer
  när någon synar, förlorar man två liv.
- När man mist tre liv är man ute. Sist kvar vinner.
- Kommer bägaren ett helt varv tillbaka till budgivaren måste denne höja.
  Tärningarna slås då om, och budgivaren får själv välja att titta på dem eller
  bjuda blint. Är budet Mejer får spelaren i stället slå om och börja en ny runda.

Poängordning (högst först):
21, 11, 22, 33, 44, 55, 66, 65, 64, 63, 62, 61, 54, 53, 52, 51, 43, 42, 41, 32, 31.

## Kom igång

Enklast: kör startskriptet. Det installerar beroenden om de saknas och startar
webbappen.

```bash
./run.sh                # startar i förgrunden (Ctrl-C stoppar)
./run.sh --background   # startar i bakgrunden, loggar till /tmp/mejer_web.log
./run.sh --check        # kontrollerar bara att beroenden och port är redo
```

Öppna sedan `http://localhost:12000`.

Manuellt, om du hellre vill:

```bash
pip install -r requirements.txt
python -m uvicorn mejer.web.app:app --host 0.0.0.0 --port 12000
```

> **Efter en omstart av miljön:** globalt installerade paket försvinner, och
> `python -m uvicorn` svarar då "No module named uvicorn". Kör `./run.sh` igen –
> skriptet upptäcker att paketen saknas och installerar om dem automatiskt.

### Kommandoradsgränssnitt

```bash
# Givet tärningsslaget 2 och 5: hur svarar spelaren?
python -m mejer.cli announce 2 5 --role rackar

# Om spelaren slår efter ett tidigare bud (måste höja)
python -m mejer.cli announce 2 5 --role kalkyl --previous-bid 43

# Spelaren möter en motståndares bud
python -m mejer.cli decide 43 --role trygg

# Spela ett helt spel med flera oberoende agenter
python -m mejer.cli play rackar kalkyl trygg

# Interaktiv session med steg-grind och logg
python -m mejer.cli session

# Spela många matcher och skriv ett JSONL-protokoll för analys
python -m mejer.cli match --count 20 --out matches.jsonl --workers 3

# Sammanfatta ett tidigare protokoll
python -m mejer.cli summarize matches.jsonl
```

### Roller

| Nyckel | Namn | Stil |
|---|---|---|
| `arling` | Ärlig-Adolf | Spelar rakt och ärligt |
| `rackar` | Rackar-Rakel | Bluffar högt, tar risker |
| `kalkyl` | Kalkylerande-Karin | Matematisk, väger risk mot vinst |
| `trygg` | Trygge-Tor | Feg och defensiv |

## Interaktiv spelsession

I webbappen finns sektionen **"Fyra spelare spelar mot varandra"**:

1. Klicka **Ny session**. Slumpen avgör spelordningen och vem som börjar.
2. Ett steg visas i taget. Klicka **Ett drag** för att utföra det,
   **Till slut på runda** för att köra fram till rundans slut (en syn eller en
   ny runda), **Till syn** för att spela hela vägen fram till en syn, eller
   **Hela matchen** för att spela klart tills en vinnare står kvar.
3. Flödet följer reglerna:
   - Den som börjar **slår och tittar i smyg**, sedan säger ett bud.
   - Nästa spelare **slår** (skakar sina egna tärningar på nytt, tittar inte på
     dem och säger ett högre bud — ett *blint bud*), **synar** eller **skickar
     vidare**.
   - Kommer bägaren ett helt varv tillbaka till budgivaren måste denne **höja**.
     Tärningarna slås då om, och budgivaren får själv välja att titta på dem eller
     bjuda blint. Är budet Mejer slår budgivaren i stället om och börjar en ny runda.
   - Vid en **syn** lyfts locket. Visar tärningarna lägre än budet förlorar
     den som ansvarar för budet ett liv (den som sa det senast, eller skickade
     vidare och tog över ansvaret), annars den som synade. Mejer kostar dubbelt.

Loggen byggs **nedåt**: äldst överst, nyast nederst. Varje runda börjar med en
rad för tärningsutfallet (indata) med tärningssymboler. Därefter följer en rad
per svar – bara siffran som sägs, eller **Synar** / **Skickar vidare** / **Slår**
/ **Höjer**. Inga repliker visas. Vid en syn visas resultatet och en egen rad om
vem som förlorade hur många liv. Direkt efter den raden visas en
**livsställning** med hur många liv varje spelare har kvar (och vilka som är
ute). När matchen är slut läggs en sista rad till i loggen som säger vem som
**vinner**, och en grön rad högst upp i sessionen visar vinnaren. Livsställningen
syns också fortlöpande i spelordningen.

**Knappen "Ett drag"** ligger i loggen, direkt under det senaste
tärningsutfallet. Den utför steget så att nästa rad läggs till.

> **Obs:** Grinden (att varje steg måste bekräftas) är till för att vi ska
> kunna kontrollera att allt fungerar. **Till syn**, **Till slut på runda** och
> **Hela matchen** kör flera steg utan att du behöver trycka. En hel match är
> många LLM-anrop, så **Hela matchen** kan ta en stund; knapparna är låsta
> medan anropet kör.

## Matchserie och statistik

Fliken **Matchserie** låter spelarna möta varandra i många matcher i följd. Varje
match körs från första slag till dess att en spelare står kvar som vinnare. Efter
serien visas en sammanställning per spelare: vinster, vinstprocent, bluffrekvens,
höjningar, synar och hur ofta synen lyckas. Under sammanställningen listas varje
match (klicka för detaljer) och hela protokollet kan laddas ner som JSONL.

Protokollet är byggt för efteranalys. Varje match innehåller:

- spelarna med roll och namn, spelordningen och vem som började,
- vinnaren, antalet rundor, kvarvarande liv och utslagsordningen,
- `events`: varje åtgärd med spelare, roll, tärningsutfall, bud, om spelaren hade
  tittat på tärningarna (och om budet då var sant eller en bluff), tidigare bud,
  livsställning och rundnummer,
- `player_stats`: per spelare antal bud, blinda slag, bluffar, sanningar, synar,
  höjningar, förlorade liv och om spelaren slogs ut.

Med ett fast basfrö blir en serie reproducerbar. JSONL-formatet (en match per rad)
gör att stora serier kan läsas och analyseras rad för rad utan att allt hålls i
minnet.

### Spara loggen automatiskt till GitHub

En lång serie kan avbrytas om miljön startar om. Kryssa därför i **Checka in
loggen till GitHub efter varje match** innan du startar serien. Då skrivs
protokollet i en separat klon av ett loggrepo och checkas in (commit + push)
efter varje färdig match. Filen heter `mejer-matcher-ÅÅÅÅ-MM-DD-TTMM.jsonl`, så
varje serie blir en egen fil med datum och klockslag. Även om servern dör mitt i
serien finns de färdiga matcherna kvar på GitHub.

Ett push-fel stoppar aldrig körningen; felet rapporteras i statusfältet och
nästa match försöker igen. Om ingen token finns sparas loggen lokalt i stället.

Ställ in servern med:

| Variabel | Betydelse | Standard |
|---|---|---|
| `MEJER_LOGS_DIR` | katalog för klonen av loggrepet | `/workspace/meier-logs` |
| `MEJER_LOGS_REPO` | loggrepet på GitHub | `aieuren/meier-simulator-logs` |
| `MEJER_LOGS_TOKEN_FILE` | fil med åtkomsttoken | `/workspace/mejer-secrets/logs.token` |
| `MEJER_LOGS_PUSH` | `0` stänger av automatisk push | `1` |

Använd en fine-grained token som bara har **Contents: Read and write** på
loggrepet. Lägg den i en fil utanför kodrepet (t.ex.
`/workspace/mejer-secrets/logs.token`, rättigheter `600`), så att den överlever
omstarter. Loggrepet är avsiktligt skilt från kodrepet, så att en token som
läcker via webbappen bara kan skriva loggar – aldrig kod.

### Få resultatet incheckat

Filen skrivs radvis medan serien spelas. Kryssa i **Checka in loggen till GitHub
efter varje match** innan du startar serien, så checkas loggen in i loggrepet
efter varje färdig match. Se avsnittet om loggrepet ovan.

## Analys

Fliken **Analys** låter dig borra vidare i insamlat material. Under
**1. Välj loggar** markerar du en eller flera loggar som redan checkats in i
loggrepet. De visas med datum och tid samt antal matcher. Knappen
**Uppdatera listan** hämtar nya loggar från fjärren. Under **2. Inlästa loggar**
ser du vad som är inläst, och där kan du tömma materialet eller ladda ner det.
Flera loggar sammanställs tillsammans, så att du kan bygga en stor datamängd över
tid, från flera körningar.

Därefter ställer du frågor i fritext under **3. Ställ en fråga**. Svaret bygger
på en kompakt sammanställning av materialet – aggregerade mått per roll,
fördelningar över bud och tärningsutfall, och en matchlista. Du kan också be om
ett diagram: stapel, linje eller tabell. Diagrammen ritas som ren SVG i
webbläsaren, utan externa bibliotek. Resultatet visas under **4. Resultat**.

Tre saker är värda att veta:

- Hela händelseloggarna ryms inte i modellens kontext. Därför skickas en
  **sammanställning** i stället för rådata. Du kan se exakt vad modellen får
  under **Visa sammanställningen som skickas till modellen**.
- Modellen får inte hitta på siffror; den ska räkna på det som finns. Ändå bör
  du behandla svaren som vägledning, inte som facit – särskilt vid litet
  underlag.
- Frågorna besvaras av samma LLM-uppkoppling som agenterna använder (se
  **LLM-konfiguration**). Varje fråga är alltså ett modellanrop.

## API

| Metod | Väg | Beskrivning |
|---|---|---|
| GET | `/api/roles` | Roller och poängordning |
| POST | `/api/announce` | Givet tärningsutfall: spelarens svar |
| POST | `/api/decide` | Givet ett bud: Slå, Syna eller Skicka vidare |
| GET | `/api/health` | Status och vald LLM-leverantör |
| POST | `/api/session/new` | Ny session: slumpad ordning, första slaget |
| GET | `/api/session` | Hela sessionens tillstånd och logg |
| POST | `/api/session/advance` | Ett drag: utför aktuellt steg |
| POST | `/api/session/round` | Kör flödet fram till rundans slut |
| POST | `/api/session/run` | Kör hela flödet fram till en syn |
| POST | `/api/session/end` | Spela hela matchen klart till en vinnare |
| POST | `/api/session/stop` | Avsluta sessionen |
| POST | `/api/matches/run` | Starta en serie matcher i bakgrunden |
| GET | `/api/matches/status` | Läge och hittills spelade matcher för serien |
| GET | `/api/matches/summary` | Statistik för den senaste matchserien |
| GET | `/api/matches/download` | Ladda ner protokollet (JSONL) |
| GET | `/api/matches/logrepo` | Om loggrepet är redo för automatisk incheckning |
| GET | `/api/analysis/data` | Inläst material: antal matcher, källor och sammanställning |
| GET | `/api/analysis/logs` | Lista loggar som finns incheckade i loggrepet |
| POST | `/api/analysis/load-logs` | Läs in valda loggar från loggrepet (fältet `names`) |
| POST | `/api/analysis/ask` | Ställ en fråga mot materialet (svar + ev. diagram) |
| GET | `/api/analysis/export` | Ladda ner allt inläst material som JSONL |
| POST | `/api/analysis/clear` | Töm allt inläst analysmaterial |

En match är hundratals LLM-anrop och tar minuter, så en serie körs i en
bakgrundstråd. `POST /api/matches/run` svarar direkt, och klienten följer
framdriften med `GET /api/matches/status` (fältet `running` är `false` när allt
är klart). Fliken **Matchserie** pollar status var tredje sekund och visar
matcherna vartefter de blir klara.

Fältet `workers` (1–8, standard 3) spelar flera matcher samtidigt, vilket kortar
en lång serie. Varje match har egna agenter och en egen LLM-klient, så de delar
ingen status.

### Långa körningar

En match tar några minuter, så en serie på tiotals matcher kan ta lång tid. Tre
saker avgör hur länge en körning får hålla på:

- **Serien körs i bakgrunden.** `POST /api/matches/run` svarar direkt och jobbet
  fortsätter i en tråd, oavsett om du stänger fliken. Du kan alltså starta en
  lång serie och komma tillbaka senare.
- **Sandlådan har en inaktivitetsgräns.** I Agent Canvas pausas en miljö som
  varit inaktiv en stund (runt 20 minuter). Pågående LLM-anrop och
  statuspollningen från en öppen flik håller den vaken. Lämna fliken öppen om du
  vill vara säker, och använd `workers` för att korta körtiden.
- **Protokollet skrivs medan serien spelas.** Varje klar match läggs till i
  JSONL-filen direkt, så ett avbrott mitt i serien förstör inte det som redan är
  klart. Ladda ner filen och fortsätt därifrån.

Behöver du en körning som garanterat får ta mer än en timme, kör du den utanför
Agent Canvas – koden är portabel. Sätt `ANTHROPIC_API_KEY` och kör kommandoraden
i en egen terminal (eller med `nohup`):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python -m mejer.cli match --count 60 --workers 4 \
  --out matcher.jsonl
```

Exempel:

```bash
curl -X POST http://localhost:12000/api/announce \
  -H "Content-Type: application/json" \
  -d '{"die1": 2, "die2": 5, "role": "rackar"}'

# Starta 10 matcher i bakgrunden (3 samtidigt) och följ dem
curl -X POST http://localhost:12000/api/matches/run \
  -H "Content-Type: application/json" -d '{"count": 10, "workers": 3}'
curl http://localhost:12000/api/matches/status
```

## LLM-konfiguration

Agenterna föredrar ditt **Anthropic-konto (Claude)**. Sätt nyckeln och kör:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export MEJER_MODEL=claude-sonnet-4-5   # valfritt
python -m uvicorn mejer.web.app:app --port 12000
```

Saknas `ANTHROPIC_API_KEY` faller klienten tillbaka på en OpenAI-liknande proxy
(OpenHands agent-server), som används i Agent Canvas-miljön. Se `mejer/llm.py`.

Miljövariabler:

| Variabel | Betydelse |
|---|---|
| `ANTHROPIC_API_KEY` | Claude-nyckel (föredras) |
| `ANTHROPIC_BASE_URL` | Egen Anthropic-bas-URL (valfritt) |
| `MEJER_MODEL` | Modellnamn |
| `MEJER_BASE_URL` | Bas-URL för OpenAI-liknande proxy |
| `MEJER_PROFILE_MODEL` | Konkret modell som profilen `openhands_<namn>` pekar på |

> **Obs (Agent Canvas):** agent-servern håller sina LLM-profiler i minnet. Startas
> containern om försvinner de, och modellnamnet `openhands_Default` slutar
> fungera (404 "Profile not found"). Klienten skapar då profilen på nytt och gör
> om anropet en gång. Startas miljön om försvinner också de globalt installerade
> paketen – kör `pip install -r requirements.txt` igen.

### Vad ett svar kostar i tokens

Klienten sparar tokenräkningen från senaste anropet i `LLMClient.last_usage`
(`prompt_tokens`, `completion_tokens`, `total_tokens`). Mätningar mot proxyn:

- Prompten har en **fast overhead på cirka 17 400 tokens** per anrop, oberoende
  av vår egen text (våra prompter är ~1 000–1 500 tecken).
- Att be modellen om fältet `reasoning` kostar extra **utdata-tokens**, ungefär
  200–600 fler, och mer när modellen resonerar längre.
- Ett vanligt Mejer-svar landar därför kring **17 900 prompt + 200–700
  completion ≈ 18 000–19 000 tokens totalt**.

## Tester

```bash
python -m pytest tests/ -q
```

Testerna täcker regelmotorn (poängordning, budjämförelse, syn-avgörande, Mejer
dubbelt) och agentens logik med en fejkad LLM – inga riktiga modellanrop behövs.

## Projektstruktur

```
mejer/
  rules.py            Regler: poängordning, jämförelse, syn, slumpat slag
  llm.py              LLM-klient (Anthropic + OpenHands-fallback)
  game.py             Spelmotor för flera oberoende agenter
  session.py          Interaktiv session: fullt flöde och logg
  match.py            Batchkörning av många matcher + statistik (JSONL)
  analysis.py         Analys: digest av protokoll + LLM-frågor med diagram
  cli.py              Kommandoradsgränssnitt
  agents/
    base.py           Agent-grundklass och roll
    player.py         Mejer-spelaragenten och rollerna
  web/
    app.py            FastAPI-app
    static/           Frontend (HTML/CSS/JS)
tests/                Enhetstester
```
