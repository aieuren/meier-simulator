# Reglerna för Meier

Detta är regeltexten för Meier.

Originalet är [`meier-regler.pdf`](meier-regler.pdf) (en sida, hämtad
2026-11-08). Vid tvekan gäller PDF:en.

## Om ordet "påstående"

PDF:en säger bud om det en spelare säger om tärningarna. Den här texten säger
påstående, eftersom det ligger närmare vad handlingen faktiskt är: ett påstående
om vad tärningarna visar, som kan vara sant eller falskt.

---

## Spelet i korthet

Två lite avlånga tärningar och en bägare med lock. Spelades redan anno 1626,
kanske.

Man har tre liv. När man mist dem är man ute. Sist kvar vinner.

## Tärningarna

Två tärningar läses som ett tal med den högsta siffran först. 2 och 5 blir 52,
inte 25.

Tärningarna är avlånga, inte kubiska. Det gör att sidorna 1 och 2 (ändytorna)
är mindre sannolika än 3–6 (långytorna).

## Poängordning, högst först

| Ordning | Tärningar | Värde |
|---|---|---|
| 1 | ⚁ ⚀ | 21 – Meier |
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

Lägg märke till att par slår singlar. 11 är näst bäst och 31 sämst. 44 slår
alltså 65.

## En runda

En runda börjar med ett påstående och slutar när någon synar. Rundan kan inte ta
slut på något annat sätt (se undantaget om Meier nedan).

1. Första spelaren skakar två tärningar i bägaren, tittar i smyg, och säger ett
   resultat till nästa spelare. Det kan vara det sanna resultatet, ett högre
   eller ett lägre.

   Det är alltså tillåtet att påstå under det tärningarna visar. Bluffen går åt
   båda hållen.

2. Nästa spelare väljer ett av tre:

   - Slå – skakar utan att titta på förra slaget och säger ett högre resultat.
     Den som slår måste alltid säga ett högre påstående än det förra, vad
     tärningarna än visar.
   - Syna – lyfter locket.
     - Visar tärningarna lägre än det sagda: föregående spelare (den som
       ansvarar för påståendet) förlorar ett liv.
     - Visar tärningarna samma eller högre: den som synade förlorar ett liv.
   - Skicka vidare – skickar bägaren utan att slå, med samma påstående och samma
     tärningar. Spelaren tar då över ansvaret för påståendet.

     Den som skickar vidare tittar inte på tärningarna. Att lyfta på locket är
     att syna, och det är en annan handling. Spelaren vet alltså bara vad
     påståendet säger, inte vad tärningarna visar.

3. Meier kostar dubbelt. Om påståendet är Meier, eller om tärningarna visar Meier
   när någon synar, förlorar man två liv i stället för ett.

## Efter en livsförlust

Bägaren går till föregående spelare, som slår och börjar en ny runda.

Är spelaren ute hoppas hen över: bägaren går till närmaste aktiva spelare före i
sittordningen.

## Helt varv tillbaka

Kommer bägaren ett helt varv tillbaka till den som satte påståendet, måste den
spelaren höja.

- Är påståendet inte Meier: tärningarna slås om, och spelaren väljer att titta på
  dem eller påstå utan att titta.
- Är påståendet Meier: det går inte att höja. Spelaren slår i stället om och
  börjar en ny runda. Ingen förlorar liv.

## Ett förtydligande som PDF:en bara antyder

PDF:en säger att "skicka vidare" sker "utan att slå". Den säger inte ordagrant att
spelaren inte ser tärningarna. Men alternativet vore orimligt: att lyfta på
locket är att syna. Kunde man titta och sedan skicka vidare skulle "skicka
vidare" vara en gratis syn, och syna-alternativet vore meningslöst. Därför ser
den som skickar vidare inte tärningarna, utan vet bara vad påståendet säger.

## Några tolkningar för denna simulator

Reglerna ovan lämnar några saker öppna. Här står de tolkningar som gjorts, så
att det går att skilja på vad spelet kräver och vad den här maskinen har
bestämt. Inget av detta är regler, och allt kan ändras utan att reglerna
ändras.

- Att datorn spelar spelaren ändrar inte att "skicka vidare" sker utan att syna.
  Den som svarar får påståendet och sitt livsantal, aldrig tärningarna.
- Att ett slag utan att titta måste lägga sig över det förra påståendet är en regel.
  Vilket högre påstående som väljs är däremot ett strategival.
- Hur ofta en spelare bluffar, synar eller skickar vidare är också ett
  strategival. Reglerna säger inget om det.
- Tärningarnas form är modellerad som en avlång kropp, där längden är 1,3 gånger
  bredden. Det ger ändytorna lägre sannolikhet än långytorna, i linje med
  reglernas lösa beskrivning.

Hur valen är gjorda i praktiken står i [agentmodellen](../agent-model.md) och
[granskningen](granskning.md).
