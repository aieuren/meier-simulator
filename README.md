# Meier – LLM-baserade AI-spelare

En webapplikation och ett Python-bibliotek med oberoende, LLM-baserade
AI-agenter som spelar tärningsspelet Meier (också kallat Mia, Mire,
Kuriki och Kunito).

Fokus för första versionen: en agent som simulerar en spelare. Givet utfallet av
ett tärningsslag med två tärningar bestämmer agenten hur spelaren svarar – den
säger sanningen, ett högre eller ett lägre resultat. Fler agenter med olika
roller kan spela hela spel mot varandra.

> Vill du bara veta vad det här är? Läs
> [Om meier-simulatorn](docs/om-meier-simulatorn.md) – en kort genomgång för den
> som är nyfiken men inte ska bygga vidare. Den här filen är för dig som ska
> köra och ändra i koden.
>
> Vill du veta vilka reglerna är? Läs
> [reglerna](docs/regler/meier-regler.md). [Granskningen](docs/regler/granskning.md)
> visar punkt för punkt att maskinen följer dem.

## Vad som finns

- Webbapp med fem flikar:
  - Rollerna – de fem spelarna och deras profilbeskrivningar.
  - Enskild spelare – skriv in tärningsutfallet (två tärningar) och se spelarens svar.
  - Spelarna möter varandra – spelarna spelar mot varandra i ett fullt flöde fram till en syn.
  - Matchserie – kör många matcher och få statistik + ett JSONL-protokoll för analys.
  - Analys – ladda upp en eller flera JSONL-filer och ställ frågor mot materialet.
    Svaren kommer från en LLM och kan innehålla diagram (stapel, linje eller tabell).
- Fem spelare – Axel, Berit, Cecilia, David och Elsa. Fyra av dem är
  LLM-agenter som fattar sina egna beslut inom spelets regler. Axel är
  referensen utan LLM.
- Interaktiv spelsession – spelarna möter varandra i ett fullt flöde
  fram till en syn. Slumpen avgör ordningen och vem som börjar. Varje steg
  bekräftas med Ett drag, eller så körs flödet vidare med Till syn
  eller Till slut på runda. Varje svar sparas i en logg.
- Matchserie och statistik – spela N matcher mellan rollerna, se vinstfrekvens,
  bluffrekvens, höjningar och synar, och ladda ner hela protokollet som JSONL.
- Spelmotor – flera oberoende agenter spelar ett fullt Meier-spel mot varandra.
- Kommandoradsgränssnitt – kör agenten, en session eller ett helt spel.
- Regelmotor – fullständig poängordning, påståendejämförelse, syn-avgörande och
  slumpade tärningsslag.

## Regler (sammanfattning)

- Två tärningar läses som ett tal med den högsta tärningen först: 2 och 5 blir 52.
- 21 kallas Meier och är högst. Sedan faller ordningen ner till 31 (lägst).
- Spelaren skakar, tittar i smyg och påstår vad tärningarna visar: sant, högre eller lägre.
- Nästa spelare kan Syna (lyfta locket), Slå (säga ett högre påstående; den som
  slår får alltid titta på sina egna tärningar) eller Skicka vidare (samma påstående).
- Vid syn: visar tärningarna lägre än påståendet förlorar den som påstår ett liv. Visar de
  samma eller högre förlorar den som synade ett liv.
- Meier kostar dubbelt – om påståendet är Meier, eller om tärningarna visar Meier
  när någon synar, förlorar man två liv.
- När man mist tre liv är man ute. Sist kvar vinner.
- Kommer bägaren ett helt varv tillbaka till den som påstår måste denne höja.
  Tärningarna slås då om, och den som påstår får själv välja att titta på dem eller
  påstå utan att titta. Är påståendet Meier får spelaren i stället slå om och börja en ny runda.

Poängordning (högst först):
21, 11, 22, 33, 44, 55, 66, 65, 64, 63, 62, 61, 54, 53, 52, 51, 43, 42, 41, 32, 31.

### Tärningens form

Tärningarna är avlånga, inte kubiska. Ändytorna (1 och 2) är kvadratiska,
långytorna (3–6) är längre. Längden är ungefär 1,3 gånger bredden
(`rules.DIE_ELONGATION`).

Vikten per sida följer sidans rymdvinkel från tärningens masscentrum
(`rules.FACE_WEIGHTS`). Det är den vanligaste modellen för en kropp som kastas
slumpmässigt: en yta längre bort från centrum täcker en mindre vinkel och blir
mindre sannolik. Med längden 1,3 mot bredden 1,0 blir en sida 3–6 därför 1,56
gånger så sannolik som en sida 1–2, inte 1,3. Se `docs/agent-model.md` §3.0.

Därför blir Meier (21) och 11 ovanligare än vid en kub, medan utfall som 65, 64
och 43 blir vanligare. Udda och jämn förblir ändå lika sannolika, eftersom 1 och
2 ligger på ändytorna (en udda, en jämn) och 3–6 på långytorna (två udda, två
jämna).

## Kom igång

Enklast: kör startskriptet. Det installerar beroenden om de saknas och startar
webbappen.

```bash
./run.sh                # startar i förgrunden (Ctrl-C stoppar)
./run.sh --background   # startar i bakgrunden, loggar till /tmp/meier_web.log
./run.sh --check        # kontrollerar bara att beroenden och port är redo
```

Öppna sedan `http://localhost:12000`.

Manuellt, om du hellre vill:

```bash
pip install -r requirements.txt
python -m uvicorn meier.web.app:app --host 0.0.0.0 --port 12000
```

> Efter en omstart av miljön: globalt installerade paket försvinner, och
> `python -m uvicorn` svarar då "No module named uvicorn". Kör `./run.sh` igen –
> skriptet upptäcker att paketen saknas och installerar om dem automatiskt.

### Kommandoradsgränssnitt

```bash
# Givet tärningsslaget 2 och 5: hur svarar spelaren?
python -m meier.cli announce 2 5 --role david

# Om spelaren slår efter ett tidigare påstående (måste höja)
python -m meier.cli announce 2 5 --role cecilia --previous-bid 43

# Spelaren möter en motståndares påstående
python -m meier.cli decide 43 --role berit

# Spela ett helt spel med flera oberoende agenter
python -m meier.cli play berit cecilia david

# Interaktiv session med steg-grind och logg
python -m meier.cli session

# Spela många matcher och skriv ett JSONL-protokoll för analys
python -m meier.cli match --count 20 --out matches.jsonl --workers 3

# Sammanfatta ett tidigare protokoll
python -m meier.cli summarize matches.jsonl
```

### Roller

Spelarens egen profil bor i fyra parametrar, inte i namnet. Skalan är 0–1.
Namnen på parametrarna är korta; här är vad de står för:

| Parameter | Enkelt namn | Betydelse |
|---|---|---|
| `caution` | Försiktighet | Hur gärna spelaren undviker risk. Hög försiktighet ger färre synar |
| `statistics` | Statistik | Hur mycket spelaren styr sina beslut av sannolikheter |
| `unpredictability` | Oförutsägbarhet | Hur mycket spelaren varierar sitt spel för att vara svår att läsa |
| `reading` | Läsförmåga | Hur mycket spelaren använder information om andras tidigare spel |

Bluffandet är **inte** en parameter, och grundtaktiken bluffar inte alls. Den
säger vad tärningarna visar. Lögner förekommer bara när regeln tvingar fram dem:
den som slår måste höja över det som står, och då blir en del påståenden osanna
vad spelaren än vill.

Skilj på tre saker:

- Egen profil — spelarens egna fyra parametrar.
- Motståndarprofil — spelarens *gissning* om en annan spelares benägenhet att
  syna och att bluffa, byggd enbart på offentligt beteende
  (`OpponentProfile`).
- Motståndartyp — kort etikett som sammanfattar motståndarprofilen,
  exempelvis "bluffbenägen".

En spelare får aldrig veta en motståndares verkliga parametrar. Läsaren
(`OpponentReader`) gissar, och gissningen kan vara fel.

`BASE` kallas grundtaktik: den kalla grundstrategin utan läsning.

Registret (`ROSTER`) sätter värdena. Det är två baslinjer och tre varianter:

| Nyckel | Namn | Försiktighet | Statistik | Oförutsägbarhet | Läsning | LLM | Profil |
|---|---|---:|---:|---:|---:|---|---|
| `axel` | Axel | 0,50 | 0,50 | 0,20 | 0,00 | nej | Grundtaktiken; referens utan LLM |
| `berit` | Berit | 0,50 | 0,50 | 0,20 | 0,00 | ja | Samma taktik som Axel, men med LLM |
| `cecilia` | Cecilia | 0,80 | 0,50 | 0,20 | 0,50 | ja | Lyfter försiktigheten |
| `david` | David | 0,50 | 0,80 | 0,20 | 0,50 | ja | Lyfter statistiken |
| `elsa` | Elsa | 0,50 | 0,50 | 0,80 | 0,50 | ja | Lyfter oförutsägbarheten |

Axel och Berit har exakt samma parametrar. Skillnaden mellan dem är bara
beslutsmotorn: regler mot språkmodell. Cecilia, David och Elsa har samma
läsförmåga som varandra, så deras inbördes jämförelse handlar bara om den
dimension de lyfter.

Samma tabell i klartext, som webbappen visar den:

- Axel – Väger risk mot vinst, väger in sannolikheter och spelar förutsägbart;
  läser ingen motståndare
  (försiktighet 50 %, statistik 50 %, oförutsägbarhet 20 %, läsning 0 %).
- Berit – Väger risk mot vinst, väger in sannolikheter och spelar förutsägbart;
  läser ingen motståndare
  (försiktighet 50 %, statistik 50 %, oförutsägbarhet 20 %, läsning 0 %).
- Cecilia – Undviker risk nästan alltid, väger in sannolikheter och spelar
  förutsägbart; läser motståndarna
  (försiktighet 80 %, statistik 50 %, oförutsägbarhet 20 %, läsning 50 %).
- David – Väger risk mot vinst, räknar hårt på sannolikheterna och spelar
  förutsägbart; läser motståndarna
  (försiktighet 50 %, statistik 80 %, oförutsägbarhet 20 %, läsning 50 %).
- Elsa – Väger risk mot vinst, väger in sannolikheter och byter spel hela
  tiden; läser motståndarna
  (försiktighet 50 %, statistik 50 %, oförutsägbarhet 80 %, läsning 50 %).

Klartexten räknas fram ur siffrorna av `describe_params()`. Den är en
presentation av tabellen, inte en egen sanning: ändrar du en parameter ändras
meningen.

Siffrorna är ett underlag för en personlighet, inte en formel. De beskriver
hur en människa brukar spela, och beskrivningen går in i LLM:ens prompt
(`meier/agents/personality.py`). Modellen väljer sedan själv bland de lagliga
dragen. Reglerna ägs av koden (`meier/legality.py`); taktiken ägs av modellen.

Axel har ingen LLM med flit — han är referensen som de andra mäts mot. Hans
taktik innehåller ingen språkmodell. Däremot behöver hans enskilda drag inte
vara reproducerbara ner på slumpnivå.

Hela modellen, med formler och mätvärden, står i
[`docs/agent-model.md`](docs/agent-model.md).

## Interaktiv spelsession

I webbappen finns sektionen "Spelarna möter varandra":

1. Klicka Ny session. Slumpen avgör spelordningen och vem som börjar.
2. Ett steg visas i taget. Klicka Ett drag för att utföra det,
   Till slut på runda för att köra fram till rundans slut (en syn eller en
   ny runda), Till syn för att spela hela vägen fram till en syn, eller
   Hela matchen för att spela klart tills en vinnare står kvar.
3. Flödet följer reglerna:
   - Den som börjar slår och tittar i smyg, sedan säger ett påstående.
   - Nästa spelare slår (skakar sina egna tärningar på nytt, **får lyfta på
     locket och titta på dem** och säger sedan ett högre påstående), synar eller
     skickar vidare. Att avstå från att titta är ett eget val, ett *påstående
     utan att titta*, som hör till fintaktiken.
   - Kommer bägaren ett helt varv tillbaka till den som påstår måste denne höja.
     Tärningarna slås då om, och den som påstår får själv välja att titta på dem eller
     påstå utan att titta. Är påståendet Meier slår den som påstår i stället om och börjar en ny runda.
   - Vid en syn lyfts locket. Visar tärningarna lägre än påståendet förlorar
     den som ansvarar för påståendet ett liv (den som sa det senast, eller skickade
     vidare och tog över ansvaret), annars den som synade. Meier kostar dubbelt.

Loggen byggs nedåt: äldst överst, nyast nederst. Varje runda börjar med en
rad för tärningsutfallet (indata) med tärningssymboler. Därefter följer en rad
per svar – bara siffran som sägs, eller Synar / Slår / Skickar vidare
/ Höjer. Inga repliker visas. Vid en syn visas resultatet och en egen rad om
vem som förlorade hur många liv. Direkt efter den raden visas en
livsställning med hur många liv varje spelare har kvar (och vilka som är
ute). När matchen är slut läggs en sista rad till i loggen som säger vem som
vinner, och en grön rad högst upp i sessionen visar vinnaren. Livsställningen
syns också fortlöpande i spelordningen.

Knappen "Ett drag" ligger i loggen, direkt under det senaste
tärningsutfallet. Den utför steget så att nästa rad läggs till.

> Obs: Grinden (att varje steg måste bekräftas) är till för att vi ska
> kunna kontrollera att allt fungerar. Till syn, Till slut på runda och
> Hela matchen kör flera steg utan att du behöver trycka. En hel match är
> många LLM-anrop, så Hela matchen kan ta en stund; knapparna är låsta
> medan anropet kör.

## Matchserie och statistik

Fliken Matchserie låter spelarna möta varandra i många matcher i följd. Varje
match körs från första slag till dess att en spelare står kvar som vinnare. Efter
serien visas en sammanställning per spelare: vinster, vinstprocent, bluffrekvens,
höjningar, synar och hur ofta synen lyckas. Under sammanställningen listas varje
match (klicka för detaljer) och hela protokollet kan laddas ner som JSONL.

Protokollet är byggt för efteranalys. Varje match innehåller:

- spelarna med roll och namn, spelordningen och vem som började,
- vinnaren, antalet rundor, kvarvarande liv och utslagsordningen,
- `events`: varje åtgärd med spelare, roll, tärningsutfall, påstående, om spelaren hade
  tittat på tärningarna (och om påståendet då var sant eller en bluff), tidigare påstående,
  livsställning och rundnummer,
- `player_stats`: per spelare antal påståenden, slag utan att titta (det valda
  undantaget), bluffar, sanningar, synar,
  höjningar, förlorade liv och om spelaren slogs ut,
- `reads`: vad spelarna trodde om varandra när matchen var slut. En rad per
  läsande spelare, med en profil per motståndare: benägenhet att syna och
  bluffa, förutsägbarhet, kort etikett, säkerhet och om bilden kom från
  språkmodellen eller från statistik. Bilder utan underlag sparas inte, och
  spelare som inte läser motståndare (Axel) får ingen rad. Klartexten byggs ur
  talen när matchen visas, så loggen bär bara siffrorna.

Med ett fast basfrö blir en serie reproducerbar. JSONL-formatet (en match per rad)
gör att stora serier kan läsas och analyseras rad för rad utan att allt hålls i
minnet.

### Spara loggen automatiskt till GitHub

En lång serie kan avbrytas om miljön startar om. Serien checkas därför in
automatiskt till GitHub efter varje match. Protokollet skrivs i en separat klon
av ett loggrepo och checkas in (commit + push) efter varje färdig match. Filen
heter `ÅÅÅÅ-MM-DD-TTMMSS.jsonl`, så varje serie blir en egen fil med datum och
klockslag. Även om servern dör mitt i serien finns de färdiga matcherna kvar på
GitHub.

Ett push-fel stoppar aldrig körningen; felet rapporteras i statusfältet och
nästa match försöker igen. Om ingen token finns sparas loggen lokalt i stället.

Ställ in servern med:

| Variabel | Betydelse | Standard |
|---|---|---|
| `MEIER_LOGS_DIR` | katalog för klonen av loggrepet | `/workspace/meier-logs` |
| `MEIER_LOGS_REPO` | loggrepet på GitHub | `aieuren/meier-simulator-logs` |
| `MEIER_LOGS_TOKEN_FILE` | fil med åtkomsttoken | `/workspace/meier-secrets/logs.token` |
| `MEIER_LOGS_PUSH` | `0` stänger av automatisk push | `1` |

Använd en fine-grained token som bara har Contents: Read and write på
loggrepet. Lägg den i en fil utanför kodrepet (t.ex.
`/workspace/meier-secrets/logs.token`, rättigheter `600`), så att den överlever
omstarter. Loggrepet är avsiktligt skilt från kodrepet, så att en token som
läcker via webbappen bara kan skriva loggar – aldrig kod.

### Få resultatet incheckat

Filen skrivs radvis medan serien spelas. Kryssa i Checka in loggen till GitHub
efter varje match innan du startar serien, så checkas loggen in i loggrepet
efter varje färdig match. Se avsnittet om loggrepet ovan.

## Analys

Fliken Analys låter dig borra vidare i insamlat material. Under
Välj datakällor markerar du de matchloggar som redan checkats in i
loggrepet. En markerad logg läses in direkt, och avmarkerar du den tas den ur
analysen igen. Varje rad visar datum och tid samt antal matcher. Knappen
Uppdatera listan hämtar nya loggar från fjärren. Flera loggar sammanställs
tillsammans, så att du kan bygga en stor datamängd över tid, från flera
körningar.

Varje rad har också en egen kryssruta, ta bort, som markerar loggen för
radering. Knappen Ta bort markerade frågar en gång extra och raderar sedan
filen på riktigt: den tas bort ur loggrepet, checkas in och pushas, alltså även
på GitHub. Borttagningen går inte att ångra. En lokal serie (som aldrig kom in i
loggrepet) raderas bara från disk. Serien som fliken Matchserie pekar på släpps
samtidigt, så att fliken inte letar efter en fil som är borta.

Därefter ställer du frågor i fritext under Ställ frågor. Svaret
bygger på en kompakt sammanställning av materialet – aggregerade mått per roll,
fördelningar över påstående och tärningsutfall, och en matchlista. Du kan också be om
ett diagram: stapel, linje eller tabell. Diagrammen ritas som ren SVG i
webbläsaren, utan externa bibliotek. Resultatet visas under Resultat.

Tre saker är värda att veta:

- Hela händelseloggarna ryms inte i modellens kontext. Därför skickas en
  sammanställning i stället för rådata. Du kan se exakt vad modellen får
  under Visa sammanställningen som skickas till modellen.
- Modellen får inte hitta på siffror; den ska räkna på det som finns. Ändå bör
  du behandla svaren som vägledning, inte som facit – särskilt vid litet
  underlag.
- Frågorna besvaras av samma LLM-uppkoppling som agenterna använder (se
  LLM-konfiguration). Varje fråga är alltså ett modellanrop.
- Om en fråga kräver detaljer som inte finns i sammanställningen (t.ex. enskilda
  tärningsslag eller rundsekvenser) visas en röd notis i resultatet: *Underlaget
  räcker inte*. Notisen säger vilken detalj som saknas, så att det går att avgöra
  om sammanställningen behöver byggas ut.

## API

| Metod | Väg | Beskrivning |
|---|---|---|
| GET | `/api/roles` | Roller och poängordning |
| POST | `/api/announce` | Givet tärningsutfall: spelarens svar |
| POST | `/api/decide` | Givet ett påstående: Syna, Slå eller Skicka vidare |
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
| GET | `/api/analysis/logs` | Lista loggar i loggrepet (med `games` och `loaded`) |
| POST | `/api/analysis/select` | Sätt inlästa loggar: valda läses in, övriga tas ur analysen (`names`) |
| POST | `/api/analysis/delete` | Ta bort loggar helt: ur loggrepet (commit + push) och från disk (`names`) |
| POST | `/api/analysis/ask` | Ställ en fråga mot materialet (svar + ev. diagram) |

En match är hundratals LLM-anrop och tar minuter, så en serie körs i en
bakgrundstråd. `POST /api/matches/run` svarar direkt, och klienten följer
framdriften med `GET /api/matches/status` (fältet `running` är `false` när allt
är klart). Fliken Matchserie pollar status var tredje sekund och visar
matcherna vartefter de blir klara.

Fältet `workers` (1–8, standard 3) spelar flera matcher samtidigt, vilket kortar
en lång serie. Varje match har egna agenter och en egen LLM-klient, så de delar
ingen status.

### Långa körningar

En match tar några minuter, så en serie på tiotals matcher kan ta lång tid. Tre
saker avgör hur länge en körning får hålla på:

- Serien körs i bakgrunden. `POST /api/matches/run` svarar direkt och jobbet
  fortsätter i en tråd, oavsett om du stänger fliken. Du kan alltså starta en
  lång serie och komma tillbaka senare.
- Sandlådan har en inaktivitetsgräns. I Agent Canvas pausas en miljö som
  varit inaktiv en stund (runt 20 minuter). Pågående LLM-anrop och
  statuspollningen från en öppen flik håller den vaken. Lämna fliken öppen om du
  vill vara säker, och använd `workers` för att korta körtiden.
- Protokollet skrivs medan serien spelas. Varje klar match läggs till i
  JSONL-filen direkt, så ett avbrott mitt i serien förstör inte det som redan är
  klart. Ladda ner filen och fortsätt därifrån.

Behöver du en körning som garanterat får ta mer än en timme, kör du den utanför
Agent Canvas – koden är portabel. Sätt `GEMINI_API_KEY` och kör kommandoraden
i en egen terminal (eller med `nohup`):

```bash
export GEMINI_API_KEY=...
python -m meier.cli match --count 60 --workers 4 \
  --out matcher.jsonl
```

Exempel:

```bash
curl -X POST http://localhost:12000/api/announce \
  -H "Content-Type: application/json" \
  -d '{"die1": 2, "die2": 5, "role": "david"}'

# Starta 10 matcher i bakgrunden (3 samtidigt) och följ dem
curl -X POST http://localhost:12000/api/matches/run \
  -H "Content-Type: application/json" -d '{"count": 10, "workers": 3}'
curl http://localhost:12000/api/matches/status
```

## LLM-konfiguration

Agenterna använder Google Gemini. Sätt nyckeln och kör:

```bash
export GEMINI_API_KEY=...                # Google Gemini
export MEIER_MODEL=gemini-3.1-flash-lite # valfritt
python -m uvicorn meier.web.app:app --port 12000
```

Nyckeln kan också ligga i en fil: `$MEIER_SECRETS_DIR/gemini.key` (standard
`MEIER_SECRETS_DIR` är `/workspace/meier-secrets`). Det är så `run.sh` gör.

Anropen går till det OpenAI-liknande `https://generativelanguage.googleapis.com/v1beta/openai`.

Gemini är den enda leverantören. Lägg inte till någon annan; se AGENTS.md.

Saknas nyckeln avbryts anropet med ett tydligt fel. Det finns ingen
återfallsväg till OpenHands agent-servern: varje anrop där startar en egen
konversation, vilket fyllde konversationskatalogen under en match.

Miljövariabler:

| Variabel | Betydelse |
|---|---|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini-nyckel |
| `MEIER_MODEL` | Modellnamn |
| `MEIER_FALLBACK_MODELS` | Reservmodeller, kommaseparerade. Används när den primära svarar 503 (överbelastad). `run.sh` sätter `gemini-flash-lite-latest,gemini-3.5-flash-lite` |
| `MEIER_BASE_URL` | Egen bas-URL för HTTP-anropet |
| `MEIER_SECRETS_DIR` | Katalog med nyckelfilen `gemini.key` |
| `MEIER_MAX_RPM` | Tak för anrop/minut (0 = av; standard 15) |

> Obs (Agent Canvas): startas miljön om försvinner de globalt installerade
> paketen – kör `pip install -r requirements.txt` igen.

### Vad ett svar kostar i tokens

Klienten sparar tokenräkningen från senaste anropet i `LLMClient.last_usage`
(`prompt_tokens`, `completion_tokens`, `total_tokens`). Mätningar mot Gemini:

- Vår egen prompt är liten: systemprompten ~322 tokens och användarprompten
  ~143, alltså cirka 465 tokens per anrop.
- Att be modellen om fältet `reasoning` kostar extra utdata-tokens.

## Tester

```bash
python -m pytest tests/ -q
```

Testerna täcker regelmotorn (poängordning, påståendejämförelse, syn-avgörande, Meier
dubbelt) och agentens logik med en fejkad LLM – inga riktiga modellanrop behövs.

## Projektstruktur

```
meier/
  rules.py            Regler: poängordning, jämförelse, syn, slumpat slag
  llm.py              LLM-klient (Google Gemini)
  game.py             Spelmotor för flera oberoende agenter
  session.py          Interaktiv session: fullt flöde och logg
  match.py            Batchkörning av många matcher + statistik (JSONL)
  analysis.py         Analys: digest av protokoll + LLM-frågor med diagram
  cli.py              Kommandoradsgränssnitt
  opponents.py        Motståndarprofilen: statistik och klartext
  legality.py         Reglerna: vilka påståenden och svar som är lagliga
  policy.py           Reservstrategin när ingen LLM svarar (Axels läge)
  agents/
    base.py           Agent-grundklass och roll
    roster.py         De fem spelarna och deras parametrar
    strategic.py      Spelaren: LLM:en väljer bland lagliga drag
    personality.py    Spelarprofilen som text till prompten
    reader.py         Läser motståndarna med LLM
    player.py         Meier-spelaragenten (enkelt gränssnitt)
  web/
    app.py            FastAPI-app
    static/           Frontend (HTML/CSS/JS)
tests/                Enhetstester
```
