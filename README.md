# Mejeri – LLM-baserade AI-spelare

En webapplikation och ett Python-bibliotek med **oberoende, LLM-baserade
AI-agenter** som spelar tärningsspelet **Mejeri** (Mejer/Mia/Mire/Kuriki/Kunito).

Fokus för första versionen: en agent som simulerar en spelare. Givet utfallet av
ett tärningsslag med två tärningar bestämmer agenten hur spelaren svarar – den
säger sanningen, ett högre eller ett lägre resultat. Fler agenter med olika
roller kan spela hela spel mot varandra.

## Vad som finns

- **Webbapp med tre flikar:**
  - **Enskild spelare** – skriv in tärningsutfallet (två tärningar) och se spelarens svar.
  - **Fyra agenter** – fyra agenter spelar mot varandra i ett fullt flöde fram till en syn.
  - **Hela spel** – en logg per spelat spel från början till slut (innehållet kommer).
- **Fyra spelarroller** – Ärlig-Adolf, Rackar-Rakel, Kalkylerande-Karin och Trygge-Tor.
- **Domaragent** – Domare-Doris övervakar att alla följer reglerna och säger OK eller
  kommer med invändningar.
- **Interaktiv spelsession** – fyra agenter spelar mot varandra i ett fullt flöde
  fram till en syn. Slumpen avgör ordningen och vem som börjar. Varje steg
  bekräftas med OK, eller så körs hela flödet fram till synen på en gång. Varje
  svar sparas i en logg.
- **Spelmotor** – flera oberoende agenter spelar ett fullt Mejeri-spel mot varandra.
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
- Kommer bägaren ett helt varv tillbaka till budgivaren måste denne höja. Är
  budet Mejer får spelaren i stället slå om och börja en ny runda.

Poängordning (högst först):
21, 11, 22, 33, 44, 55, 66, 65, 64, 63, 62, 61, 54, 53, 52, 51, 43, 42, 41, 32, 31.

## Kom igång

Enklast: kör startskriptet. Det installerar beroenden om de saknas och startar
webbappen.

```bash
./run.sh                # startar i förgrunden (Ctrl-C stoppar)
./run.sh --background   # startar i bakgrunden, loggar till /tmp/mejeri_web.log
./run.sh --check        # kontrollerar bara att beroenden och port är redo
```

Öppna sedan `http://localhost:12000`.

Manuellt, om du hellre vill:

```bash
pip install -r requirements.txt
python -m uvicorn mejeri.web.app:app --host 0.0.0.0 --port 12000
```

> **Efter en omstart av miljön:** globalt installerade paket försvinner, och
> `python -m uvicorn` svarar då "No module named uvicorn". Kör `./run.sh` igen –
> skriptet upptäcker att paketen saknas och installerar om dem automatiskt.

### Kommandoradsgränssnitt

```bash
# Givet tärningsslaget 2 och 5: hur svarar spelaren?
python -m mejeri.cli announce 2 5 --role rackar

# Om spelaren slår efter ett tidigare bud (måste höja)
python -m mejeri.cli announce 2 5 --role kalkyl --previous-bid 43

# Spelaren möter en motståndares bud
python -m mejeri.cli decide 43 --role trygg

# Spela ett helt spel med flera oberoende agenter
python -m mejeri.cli play rackar kalkyl trygg

# Interaktiv session med OK-grind, domare och logg
python -m mejeri.cli session
```

### Roller

| Nyckel | Namn | Stil |
|---|---|---|
| `arling` | Ärlig-Adolf | Spelar rakt och ärligt |
| `rackar` | Rackar-Rakel | Bluffar högt, tar risker |
| `kalkyl` | Kalkylerande-Karin | Matematisk, väger risk mot vinst |
| `trygg` | Trygge-Tor | Feg och defensiv |
| `domare` | Domare-Doris | Domare (inte en spelare) |

## Interaktiv spelsession

I webbappen finns sektionen **"Fyra agenter spelar mot varandra"**:

1. Klicka **Ny session**. Slumpen avgör spelordningen och vem som börjar.
2. Ett steg visas i taget. Klicka **OK – nästa steg** för att utföra det, eller
   **Kör till syn** för att spela hela vägen fram till en syn på en gång.
3. Flödet följer reglerna:
   - Den som börjar **slår och tittar i smyg**, sedan säger ett bud.
   - Nästa spelare **slår** (skakar bägaren på nytt och säger ett högre bud), **synar** eller **skickar
     vidare**.
   - Kommer bägaren ett helt varv tillbaka till budgivaren måste denne **höja**.
     Är budet Mejer slår budgivaren i stället om och börjar en ny runda.
   - Vid en **syn** lyfts locket. Visar tärningarna lägre än budet förlorar
     budgivaren ett liv, annars den som synade. Mejer kostar dubbelt.
4. Domaren granskar varje svar och säger **OK** eller kommer med en invändning.

Loggen byggs **nedåt**: äldst överst, nyast nederst. Varje runda börjar med en
rad för tärningsutfallet (indata) med tärningssymboler. Därefter följer en rad
per svar – bara siffran som sägs, eller **Synar** / **Skickar vidare** / **Slår**
/ **Höjer** – och domarens utlåtande. Inga repliker visas. Vid en syn visas
resultatet och vem som förlorade liv. Livsställningen syns i spelordningen.

**OK-knappen** ligger i loggen, direkt under det senaste tärningsutfallet. Den
bekräftar steget så att nästa rad läggs till.

> **Obs:** Grinden (att varje steg måste bekräftas med OK) är till för att vi ska
> kunna kontrollera att allt fungerar. **Kör till syn** och ett framtida
> automatläge kör flera steg utan att du behöver trycka.

## API

| Metod | Väg | Beskrivning |
|---|---|---|
| GET | `/api/roles` | Roller och poängordning |
| POST | `/api/announce` | Givet tärningsutfall: spelarens svar |
| POST | `/api/decide` | Givet ett bud: Slå, Syna eller Skicka vidare |
| GET | `/api/health` | Status och vald LLM-leverantör |
| POST | `/api/session/new` | Ny session: slumpad ordning, domare, första slaget |
| GET | `/api/session` | Hela sessionens tillstånd och logg |
| POST | `/api/session/advance` | OK på aktuellt steg: utför det |
| POST | `/api/session/run` | Kör hela flödet fram till en syn |
| POST | `/api/session/stop` | Avsluta sessionen |

Exempel:

```bash
curl -X POST http://localhost:12000/api/announce \
  -H "Content-Type: application/json" \
  -d '{"die1": 2, "die2": 5, "role": "rackar"}'
```

## LLM-konfiguration

Agenterna föredrar ditt **Anthropic-konto (Claude)**. Sätt nyckeln och kör:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export MEJERI_MODEL=claude-sonnet-4-5   # valfritt
python -m uvicorn mejeri.web.app:app --port 12000
```

Saknas `ANTHROPIC_API_KEY` faller klienten tillbaka på en OpenAI-liknande proxy
(OpenHands agent-server), som används i Agent Canvas-miljön. Se `mejeri/llm.py`.

Miljövariabler:

| Variabel | Betydelse |
|---|---|
| `ANTHROPIC_API_KEY` | Claude-nyckel (föredras) |
| `ANTHROPIC_BASE_URL` | Egen Anthropic-bas-URL (valfritt) |
| `MEJERI_MODEL` | Modellnamn |
| `MEJERI_BASE_URL` | Bas-URL för OpenAI-liknande proxy |
| `MEJERI_PROFILE_MODEL` | Konkret modell som profilen `openhands_<namn>` pekar på |

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
- Ett vanligt Mejeri-svar landar därför kring **17 900 prompt + 200–700
  completion ≈ 18 000–19 000 tokens totalt**.

## Tester

```bash
python -m pytest tests/ -q
```

Testerna täcker regelmotorn (poängordning, budjämförelse, syn-avgörande, Mejer
dubbelt) och agentens logik med en fejkad LLM – inga riktiga modellanrop behövs.

## Projektstruktur

```
mejeri/
  rules.py            Regler: poängordning, jämförelse, syn, slumpat slag
  llm.py              LLM-klient (Anthropic + OpenHands-fallback)
  game.py             Spelmotor för flera oberoende agenter
  session.py          Interaktiv session: fullt flöde, domare, logg
  cli.py              Kommandoradsgränssnitt
  agents/
    base.py           Agent-grundklass och roll
    player.py         Mejeri-spelaragenten och rollerna
    referee.py        Domaragenten (Domare-Doris)
  web/
    app.py            FastAPI-app
    static/           Frontend (HTML/CSS/JS)
tests/                Enhetstester
```
