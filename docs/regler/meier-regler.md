# Reglerna för Meier

Detta är den kanoniska regeltexten för simulatorn. Allt annat i repot – kod,
tester och övrig dokumentation – ska följa det som står här. Avviker koden från
den här filen är det koden som är fel.

Källan är [`meier-regler.pdf`](meier-regler.pdf) (en sida, hämtad 2026-11-08).
PDF:en ligger i den här mappen och är originalet. Texten nedan är samma regler
i läsbar form, med förtydliganden där PDF:en är kortfattad. Vid tvekan gäller
PDF:en.

## PDF:ens ordalydelse

> Regler för Meier (eller Meyer, Mia, Mire, Kuriki, Kunito…) Spelades redan
> anno 1626, kanske. Två lite avlånga tärningar och en bägare med lock.
>
> När man mist tre liv är man ute. Sist kvar vinner.
>
> Tärningarna läses som ett tal med den högsta först: 2 och 5 blir 52. 21 kallas
> Meier och är högst, sen fallande enligt tabellen.
>
> - Första spelaren skakar två tärningar i bägaren, tittar i smyg och säger ett
>   resultat till nästa spelare: det sanna, ett högre eller ett lägre.
> - Nästa spelare väljer ett av tre:
>   - **Slå:** skakar utan att titta på förra slaget och säger ett högre
>     resultat.
>   - **Syna:** lyfter locket. Visar tärningarna lägre än det sagda förlorar
>     föregående spelare ett liv. Är värdet samma eller högre förlorar den som
>     synade ett liv.
>   - **Skicka vidare:** skickar bägaren utan att slå, med samma bud. Då tar
>     spelaren över ansvaret för budet och tärningarna.
>
> Den som slår måste alltid säga ett högre bud än det förra, vad än tärningarna
> visar.
>
> När någon har förlorat ett liv går bägaren till föregående spelare, som slår
> och börjar en ny runda.
>
> Meier kostar dubbelt: om budet är Meier, eller om tärningarna visar Meier när
> någon synar, förlorar man två liv i stället för ett.
>
> Kommer bägaren ett helt varv tillbaka till den som satte budet måste den
> spelaren höja. Är budet Meier får spelaren i stället slå om och börja en ny
> runda.

PDF:ens poängordning ligger som en bild. Den är avläst och verifierad mot
`rules.RANKING`: alla 21 rader stämmer.

---

## Spelet i korthet

Två lite avlånga tärningar och en bägare med lock. Spelades redan anno 1626,
kanske.

Man har **tre liv**. När man mist dem är man ute. **Sist kvar vinner.**

## Tärningarna

Två tärningar läses som ett tal med den **högsta siffran först**. 2 och 5 blir
**52**, inte 25.

Tärningarna är avlånga, inte kubiska. Det gör att sidorna 1 och 2 (ändytorna)
är mindre sannolika än 3–6 (långytorna). Se `docs/om-meier.md` för de uppmätta
sannolikheterna.

## Poängordning, högst först

| Ordning | Tärningar | Värde |
|---|---|---|
| 1 | ⚁ ⚀ | **21 – Meier** |
| 2 | ⚀ ⚀ | 11 |
| 3 | ⚁ ⚁ | 22 |
| 4 | ⚂ ⚂ | 33 |
| 5 | ⚃ ⚃ | 44 |
| 6 | ⚄ ⚄ | 55 |
| 7 | ⚅ ⚅ | 66 |
| 8 | ⚅ ⚄ | 65 |
| 9 | ⚅ ⚃ | 64 |
| 10 | ⚅ ⚂ | 63 |
| 11 | ⚅ ⚁ | 62 |
| 12 | ⚅ ⚀ | 61 |
| 13 | ⚄ ⚃ | 54 |
| 14 | ⚄ ⚂ | 53 |
| 15 | ⚄ ⚁ | 52 |
| 16 | ⚄ ⚀ | 51 |
| 17 | ⚃ ⚂ | 43 |
| 18 | ⚃ ⚁ | 42 |
| 19 | ⚃ ⚀ | 41 |
| 20 | ⚂ ⚁ | 32 |
| 21 | ⚂ ⚀ | 31 |

Lägg märke till att **par slår singlar**. 11 är näst bäst och 31 sämst. 44 slår
alltså 65. Det är den vanligaste källan till förvirring när man läser kod som
"ser fel ut".

## En runda

En runda börjar med ett bud och slutar när någon **synar**. Rundan kan inte ta
slut på något annat sätt (se undantaget om Meier nedan).

1. **Första spelaren** skakar två tärningar i bägaren, tittar **i smyg**, och
   säger ett resultat till nästa spelare. Det kan vara:
   - det **sanna** resultatet,
   - ett **högre**, eller
   - ett **lägre**.

   Det är alltså tillåtet att bjuda under det tärningarna visar. Bluffen går åt
   båda hållen.

2. **Nästa spelare** väljer ett av tre:

   - **Slå** – skakar *utan att titta* på förra slaget och säger ett **högre**
     resultat. Den som slår **måste alltid** säga ett högre bud än det förra,
     vad tärningarna än visar.
   - **Syna** – lyfter locket.
     - Visar tärningarna **lägre** än det sagda: **föregående spelare** (den som
       ansvarar för budet) förlorar ett liv.
     - Visar tärningarna **samma eller högre**: **den som synade** förlorar ett
       liv.
   - **Skicka vidare** – skickar bägaren **utan att slå**, med **samma bud och
     samma tärningar**. Spelaren tar då över ansvaret för budet.

     Den som skickar vidare **tittar inte på tärningarna**. Att lyfta på locket
     är att syna, och det är en annan handling. Spelaren vet alltså bara vad
     budet säger, inte vad tärningarna visar.

3. **Meier kostar dubbelt.** Om budet är Meier, **eller** om tärningarna visar
   Meier när någon synar, förlorar man **två liv** i stället för ett.

## Efter en livsförlust

Bägaren går till **föregående spelare**, som slår och börjar en ny runda.

Är spelaren ute hoppas hen över: bägaren går till närmaste **aktiva** spelare
före i sittordningen.

## Helt varv tillbaka

Kommer bägaren ett **helt varv** tillbaka till den som satte budet, **måste**
den spelaren **höja**.

- Är budet inte Meier: tärningarna slås om, och spelaren väljer att titta på dem
  eller bjuda blint.
- Är budet **Meier**: det går inte att höja. Spelaren slår i stället **om** och
  börjar en **ny runda**. Ingen förlorar liv.

## Vad som INTE står i reglerna

Detta är inte regler, utan simulatorns egna val. De får ändras utan att
regeltexten ändras:

- Att en blind höjning ("slå") alltid läggs på ett högre bud än det förra – det
  *är* en regel, men *vilket* högre bud som väljs är ett strategival.
- Hur ofta en agent bluffar, synar eller skickar vidare.
- Att tärningarnas exakta form modelleras som `DIE_ELONGATION = 1.3`.

## Ett förtydligande som PDF:en bara antyder

PDF:en säger att "skicka vidare" sker "utan att slå". Den säger inte ordagrant
att spelaren är blind för tärningarna. Men alternativet vore orimligt: att lyfta
på locket **är** att syna. Kunde man titta och sedan skicka vidare skulle
"skicka vidare" vara en gratis syn, och syna-alternativet vore meningslöst.
Därför gäller:

> Den som skickar vidare ser **inte** tärningarna. Spelaren vet bara vad budet
> säger.

Motorn följer detta: den som ska välja handling får **budet** och sitt
**livsantal**, aldrig tärningsvärdet. Se `docs/regler/granskning.md`, punkt 19.
