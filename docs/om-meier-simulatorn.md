# Om meier-simulatorn – vad det här är

En kort genomgång för dig som är nyfiken men inte ska bygga vidare på koden.
Inga formler, ingen installation. Bara vad grejen är och vad spelarna gör.

Vill du köra igång själv: se [README](../README.md). Vill du ha hela tekniska
modellen: se [agent-model.md](agent-model.md).

---

## Vad är det här?

Fyra AI-spelare som spelar det svenska tärningsspelet Meier mot varandra.
Varje spelare har sin egen profil – alltså sin egen spelstil – och de spänner
från försiktig till djärv och kalkylerande. Tre av dem drivs av en språkmodell.

Du kan sitta vid sidan och titta på när de spelar. Du kan också själv mata in
ett tärningsslag och se vad en spelare skulle svara. Och du kan låta dem spela
många matcher i följd.

Vad det inte är: ett försök att hitta den bästa strategin. Vi bygger en
*maskin för att förstå Meier* – ett slags laboratorium. Att vinna är inte
poängen. Poängen är att maskinen går att köra, går att upprepa och går att
fråga. Vad den sedan visar är en senare fråga.

---

## Spelet

Två tärningar i en bägare med lock. Tärningarna läses som ett tal med den
högsta först: 2 och 5 blir 52. 21 kallas Meier och är högst. Sedan
faller ordningen, och par slår singlar – 44 slår alltså 65.

En runda går från första påståendet till dess att någon synar.
En match är många rundor i följd. Varje spelare har tre liv, och den som
mist sina liv är ute. Sist kvar vinner matchen.

Den fullständiga regeltexten står i
[`docs/regler/meier-regler.md`](regler/meier-regler.md).

### Tärningarna är inte kubiska

Tärningarna är avlånga. Ändytorna (1 och 2) är kvadratiska, långytorna
(3–6) är längre. Längden är ungefär 1,3 gånger bredden.

Chansen för en sida följer sidans rymdvinkel från tärningens masscentrum. Det
är den vanligaste modellen för en kropp som kastas på måfå: en yta som ligger
längre bort från centrum täcker en mindre vinkel och blir mindre sannolik.

Ändytorna ligger längst ut och blir därför ovanligare än man kanske tror. Med
längden 1,3 mot bredden 1,0 blir en långsida 1,56 gånger så sannolik som en
ändyta — inte 1,3, som man får om man bara jämför areorna. Det är den
fördelning maskinen slår med.

Tabellen visar sannolikheten för varje utfall, och hur stor chansen är att slå
utfallet eller lägre. Den sista kolumnen är samma sak för en vanlig kub, så att
det går att se vad formen gör.

| Utfall | Exakt utfall | Utfallet eller lägre | Vanlig kub, eller lägre |
|---|---:|---:|---:|
| 21 (Meier) | 2,9 % | 100,0 % | 100,0 % |
| 11 | 1,5 % | 97,1 % | 94,4 % |
| 22 | 1,5 % | 95,6 % | 91,7 % |
| 33 | 3,6 % | 94,1 % | 88,9 % |
| 44 | 3,6 % | 90,5 % | 86,1 % |
| 55 | 3,6 % | 86,9 % | 83,3 % |
| 66 | 3,6 % | 83,4 % | 80,6 % |
| 65 | 7,2 % | 79,8 % | 77,8 % |
| 64 | 7,2 % | 72,6 % | 72,2 % |
| 63 | 7,2 % | 65,4 % | 66,7 % |
| 62 | 4,6 % | 58,3 % | 61,1 % |
| 61 | 4,6 % | 53,7 % | 55,6 % |
| 54 | 7,2 % | 49,1 % | 50,0 % |
| 53 | 7,2 % | 41,9 % | 44,4 % |
| 52 | 4,6 % | 34,7 % | 38,9 % |
| 51 | 4,6 % | 30,1 % | 33,3 % |
| 43 | 7,2 % | 25,5 % | 27,8 % |
| 42 | 4,6 % | 18,4 % | 22,2 % |
| 41 | 4,6 % | 13,8 % | 16,7 % |
| 32 | 4,6 % | 9,2 % | 11,1 % |
| 31 | 4,6 % | 4,6 % | 5,6 % |

Mellan kolumnerna syns vad formen gör. Meier och 11 blir ovanligare än vid en
kub, medan utfall där båda tärningarna är 3–6 blir vanligare. Udda och jämnt
förblir ändå lika sannolikt, eftersom 1 och 2 ligger på ändytorna (en udda, en
jämn) och 3–6 på långytorna.

Kolumnen Utfallet eller lägre är den som liknar spelet mest. Den säger hur ofta
tärningarna visar påståendet eller mindre, och det är just det en syn avgör.

---

## De fem spelarna

Spelarens egen profil sitter i fyra parametrar, inte i namnet. Varje parameter
går från 0 till 1.

- `caution` – försiktighet: hur gärna spelaren undviker risk. Hög försiktighet
  ger färre synar
- `statistics` – statistik: hur mycket spelaren styr sina beslut av
  sannolikheter
- `unpredictability` – oförutsägbarhet: hur mycket spelaren varierar sitt spel
  för att vara svår att läsa
- `reading` – läsförmåga: hur mycket spelaren låter information om andras
  tidigare spel styra

Bluffandet är ingen parameter. I Meier måste den som slår alltid höja över det
som står, och då blir en del påståenden lögner vad spelaren än vill. Bluffen är
ett nödvändigt ont i spelet, inte en egenskap att skruva på.

| Spelare | försiktighet | statistik | oförutsägbarhet | läsförmåga | LLM | Profil |
|---|---:|---:|---:|---:|---|---|
| **Axel** | 0,50 | 0,50 | 0,20 | 0,00 | nej | Grundtaktik. Referens utan språkmodell. |
| **Berit** | 0,50 | 0,50 | 0,20 | 0,00 | ja | Samma taktik som Axel, men med LLM. |
| **Cecilia** | 0,80 | 0,50 | 0,20 | 0,50 | ja | Lyfter försiktigheten. |
| **David** | 0,50 | 0,80 | 0,20 | 0,50 | ja | Lyfter statistiken. |
| **Elsa** | 0,50 | 0,50 | 0,80 | 0,50 | ja | Lyfter oförutsägbarheten. |

Upplägget är två baslinjer och tre varianter. Axel är referensen: han har ingen
språkmodell utan spelar en fast räkneregel, och han läser ingen motståndare.
Berit har exakt samma parametrar som Axel. Skillnaden mellan dem är bara
beslutsmotorn, regler mot språkmodell. Cecilia, David och Elsa lyfter en
dimension var, och alla tre har samma läsförmåga som varandra. Därför handlar
deras inbördes jämförelse bara om den dimension de lyfter.

Kravet på Axel är att taktiken inte innehåller någon språkmodell. Han lär sig
inget om motståndarna under matchens gång och anpassar sig inte efter dem.
Däremot behöver hans enskilda drag inte vara reproducerbara ner på slumpnivå.

Han är byggd för att vara tillräckligt bra, inte optimerad. Hans uppsättning
kallas grundtaktik.

Vill du se exakt vad Axel gör, drag för drag, finns hela hans speltaktik
beskriven i [agent-model.md §7.2](agent-model.md). Där står tabellerna för
vilket påstående han säger, när han synar och när han slår.

Tre begrepp:

| Begrepp | Vad det är |
|---|---|
| **Egen profil** | Spelarens egna fyra parametrar. Känd för spelaren själv. |
| **Motståndarprofil** | Spelarens gissning om en annan spelares benägenhet att syna och att bluffa. Byggd enbart på offentligt beteende. |
| **Motståndartyp** | Kort etikett som sammanfattar motståndarprofilen, till exempel "bluffbenägen". |

Spelaren känner aldrig en motståndares verkliga parametrar. Den gissar, och
gissningen kan vara fel. Det är skillnaden mellan profil och motståndarprofil.

---

## Hur en spelare tänker

### Spelaren ser inte allt

En spelare vet bara tre saker: sina egna tärningar, vad som sagts högt, och vad
som hänt tidigare i matchen. Den vet inte vad motståndaren har i bägaren.
Allt den tror om andra är en gissning byggd på offentligt beteende.

Att tärningarna är dolda är det som gör en bluff möjlig att komma undan med.
Att man måste höja är det som gör den nödvändig. Två olika saker, och båda
behövs.

### Modellen väljer draget

Modellen bestämmer draget. Den väljer fritt bland de lagliga alternativen, men
den kan aldrig bryta mot reglerna: koden räknar upp vad som är tillåtet i läget
och modellen väljer inom den listan.

### Bluffen börjar med tvånget att höja

Grunden till bluffandet i Meier är inte psykologi. Den är regeln att varje nytt
påstående måste vara högre än det förra. Tärningarna bryr sig inte om den
regeln.

Står bordet på 63 måste du säga 64 eller högre, vad dina tärningar än visar.
Visar de 41 finns inget ärligt påstående kvar. Du säger något högre än
tärningarna, alltså bluffar. Samma sak om tärningarna visar exakt 63: påståendet
måste vara strikt högre, så din egen nivå duger inte som svar.

Ju högre bordet står, desto oftare händer det. Tabellen visar hur ofta dina
tärningar inte räcker till, alltså hur ofta du tvingas bluffa:

| Bordet står på | Du tvingas bluffa |
|---|---:|
| 43 | 26 % |
| 52 | 35 % |
| 63 | 65 % |
| 66 | 83 % |

Vid Meier finns inget högre påstående, så där kan ingen slå. Bägaren går tillbaka
och den som satte påståendet måste slå om, och då börjar en ny runda.

Det är därför bluffen finns. Sedan kan man välja hur man bluffar: var man lägger
sig, hur ofta man tar chansen och vad man försöker få motståndaren att tro. Det
kommer ovanpå grunden.

### Vad ett påstående kostar

Varje beslut är en avvägning mellan två saker: chansen att slippa bli synad och
vad det kostar om du blir synad.

Påstår du exakt det tärningarna visar och blir synad, vinner du rundan.
Tärningarna visar då minst påståendet, så synaren förlorar. Påstår du högre och
blir synad, förlorar du ett liv, eller två om påståendet är Meier. En avslöjad
bluff kostar dig alltså ett liv. Det du kan vinna med den är att motståndaren
inte synar.

Så vad köper en bluff? Att motståndaren får ett svårare beslut. Hen måste
antingen syna ett påstående hen misstror, eller slå om bägaren till något ännu
högre – och då ta över risken själv. En bluff är inte värd mer än sanningen. Den
flyttar risken över till motståndaren, och den lönar sig bara när motståndaren
hellre avstår från att syna än tar den chansen.

### Två slags höjningar

När spelaren har sett sina tärningar och bluffar över det hen såg, är ett högre
påstående alltid dyrare att bli synad på. En syn på 66 är billigare för
motståndaren än en syn på 51, eftersom tärningarna då oftare är lägre än
påståendet. Att höja långt ökar alltså risken att åka dit.

När spelaren i stället slår blint finns ingen sann nivå att lägga sig strax
över, och kalkylen är en annan: ett lågt påstående är svårt för nästa spelare att
slå över, ett högt sätter press men synas oftare.

Vem väger det ena mot det andra? Modellen. Koden räknar bara upp vilka
påståenden som är lagliga i läget, och modellen väljer bland dem. Den får
spelets ekonomi beskriven i ord – att ett påstående under tärningarna är säkert
och ett över är en bluff – men ingen färdig formel.

Repliken däremot skrivs inte av modellen. Den byggs i koden ur draget, så att en
spelare aldrig säger något annat än det hen faktiskt gjorde.

Axel är undantaget. Han har ingen modell utan spelar en fast räkneregel: vid
bluff lägger han sig på den minsta möjliga höjningen. Vid blindt slag är den
minsta lagliga höjningen det säkra valet, men han tar ibland ett större kliv
ändå — det är hans oförutsägbarhet som slår till. Samma räkneregel tar över om
en modell inte svarar.

### Hur spelaren bluffar

Tvånget att höja gäller alla lika. Bluffen är därför ingen ratt man skruvar på
— den följer av spelet. Det som skiljer spelarna är hur de hanterar tvånget.

En försiktig spelare synar mer sällan, vilket gör att en bluff oftare får stå.
En oförutsägbar spelare tar ibland ett större kliv än nödvändigt, så att
motståndaren inte kan läsa mönstret. Ingen av dem har en inställning som heter
"bluffa mer". Parametrarna säger hur spelaren brukar göra, inte vilket drag som
är bäst i läget.

### Spelaren läser sina motståndare

Här kommer språkmodellen in. Arbetet är delat i två roller:

Sekreteraren bokför vad som hänt vid bordet. Rena siffror, ingen tolkning:
hur ofta motståndaren bluffat, hur ofta hen synat, hur ofta hen höjt.

Läsaren är språkmodellen. Den tolkar siffrorna och sätter en
motståndarprofil: en gissning om hur ofta motståndaren synar och hur ofta hen
bluffar, plus en kort motståndartyp som "bluffbenägen", "försiktig" eller
"oförutsägbar", och ett mått på hur säker gissningen är.

En sak är viktig här: modellen får aldrig se dolda tärningar. Den får bara det
som varit offentligt. Annars skulle läsförmågan vara fusk.

### Spelaren litar inte fullt på sin egen läsförmåga

En språkmodell är väldigt säker på sin sak, även när den knappt har något att
gå på. Fråga den efter en enda syn och den svarar "jag är helt säker". Det är
en risk: en spelare som agerar på en tunn gissning som vore den ett faktum
låter brus styra spelet.

Därför har läsförmågan ett tak, och taket sätts av bordet — inte av modellen
och inte av den enskilda motståndaren. Två saker skiljer sig:

- Motståndarprofilen gäller en motståndare i taget. Den byggs bara på
  vad just den spelaren gjort.
- Taket för hur mycket läsförmågan får väga gäller hela bordet. Det räknar
  alla synar som avgjorts i matchen, oavsett vem de gällde.

Skälet är att varje syn är ett offentligt facit: när locket lyfts ser alla vad
som låg i bägaren, och hela bordet lär sig något om hur spelet brukar se ut.
Därför är bordets samlade erfarenhet den ärliga måttstocken – inte bara de synar
som råkade gälla din motståndare.

Antalet avgjorda synar bestämmer hur mycket läsförmågan får väga:

| Synar vid bordet | Hur mycket får läsförmågan väga |
|---|---:|
| 0 | 0 % |
| 1 | 25 % |
| 3 | 50 % |
| 9 | 75 % |

Modellen får säga "jag är säker", men taket gäller ändå. En bild byggd på en
enda syn väger en fjärdedel av en mogen bild.

Samma princip gäller åt andra hållet: en motståndare som synar ofta gör varje
bluff dyrare, så spelaren bluffar mindre mot hen. Spelaren får motståndarens
benägenhet att syna med i underlaget när hen väljer påstående. Mot en som sällan
synar är det friare fram; mot en som synar ofta lönar sig bara de påståenden som
är nästan säkra.

---

## Vad du kan göra i webbappen

- Rollerna – de fem spelarna och deras profiler.
- Enskild spelare – skriv in två tärningar och se vad en spelare svarar.
- Spelarna möter varandra – spelarna spelar mot varandra, ett steg i taget eller
  hela matchen. Loggen visar varje påstående, varje syn och vem som förlorade liv.
- Matchserie – kör många matcher och få statistik.
- Analys – välj bland loggarna och ställ frågor om materialet. Svaren kommer
  från en språkmodell och kan innehålla diagram.

---

## Vad resultaten betyder

Maskinen mäter ingenting åt dig, men den ger underlag. Efter en matchserie kan
du titta på två frågor:

- Vilken spelstil som vinner oftast. Här finns bara ett mått: den som står kvar
  sist har vunnit, för den som mist tre liv är ute. Det finns ingen poängliga.
- Om läsförmågan lönar sig. Cecilia läser motståndarna, Berit nästan inte.
  Går det att se någon skillnad mellan dem, eller väger tur och bordets övriga
  spelare tyngre?

Om det sista: `reading` är medvetet satt lågt, och taket för hur mycket
läsförmågan får väga är strängt. Det betyder inte att läsförmåga är värdelös –
det betyder att modellen inte vill överskatta en gissning byggd på få synar. Om
läsförmågan inte syns i siffrorna är det en upplysning om modellen, inte om
spelet.

En viktig varning: enstaka matcher säger nästan ingenting. Meier har hög
slump i sig, och flera spelare med liv som tar slut gör att en enskild match kan
vända på en enda syn. Kör hellre flera hundra matcher än tio.

---

## Vad du kan prova

Öppna fliken *Enskild spelare*, välj en roll och mata in två tärningar. Du får
se vad just den spelaren svarar på slaget.

Byt sedan roll och slå samma tärningar igen. Samma slag, samma regler, olika
profil – det är själva poängen med maskinen.

Prova också att köra en hel match och läsa loggen: varje påstående, varje syn och
vem som förlorade liv står med.
