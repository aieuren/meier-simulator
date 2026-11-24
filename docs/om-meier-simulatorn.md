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
utfallet eller högre. Den sista kolumnen är samma sak för en vanlig kub, så att
det går att se vad formen gör.

| Utfall | Exakt utfall | Utfallet eller högre | Vanlig kub, eller högre |
|---|---:|---:|---:|
| 21 (Meier) | 2,9 % | 2,9 % | 5,6 % |
| 11 | 1,5 % | 4,4 % | 8,3 % |
| 22 | 1,5 % | 5,9 % | 11,1 % |
| 33 | 3,6 % | 9,5 % | 13,9 % |
| 44 | 3,6 % | 13,1 % | 16,7 % |
| 55 | 3,6 % | 16,6 % | 19,4 % |
| 66 | 3,6 % | 20,2 % | 22,2 % |
| 65 | 7,2 % | 27,4 % | 27,8 % |
| 64 | 7,2 % | 34,6 % | 33,3 % |
| 63 | 7,2 % | 41,7 % | 38,9 % |
| 62 | 4,6 % | 46,3 % | 44,4 % |
| 61 | 4,6 % | 50,9 % | 50,0 % |
| 54 | 7,2 % | 58,1 % | 55,6 % |
| 53 | 7,2 % | 65,3 % | 61,1 % |
| 52 | 4,6 % | 69,9 % | 66,7 % |
| 51 | 4,6 % | 74,5 % | 72,2 % |
| 43 | 7,2 % | 81,6 % | 77,8 % |
| 42 | 4,6 % | 86,2 % | 83,3 % |
| 41 | 4,6 % | 90,8 % | 88,9 % |
| 32 | 4,6 % | 95,4 % | 94,4 % |
| 31 | 4,6 % | 100,0 % | 100,0 % |

Mellan kolumnerna syns vad formen gör. Meier och 11 blir ovanligare än vid en
kub, medan utfall där båda tärningarna är 3–6 blir vanligare.

Kolumnen Utfallet eller högre är den som liknar spelet mest. Den säger hur ofta
tärningarna når upp till påståendet, och det är just det en syn avgör: synaren
vinner när tärningarna visar påståendet eller högre.

---

## Spelarna

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

Bluffen är alltså sällan ett fritt val. Står bordet redan högt kan dina tärningar
ligga under, och då finns inget sant påstående kvar att säga. Att höja är det
enda lagliga draget, och höjningen blir en bluff vare sig du vill eller inte.
Valet finns bara vid rundans början och när bordet står lågt. Då kan du säga det
tärningarna visar och bära en sanning, eller lägga dig över den och hoppas på att
ingen synar. Det valet är det som skiljer spelarna åt.

### Två slags höjningar

När spelaren har sett sina tärningar och bluffar över det hen såg, är ett högre
påstående alltid dyrare att bli synad på. En syn på 66 är billigare för
motståndaren än en syn på 51, eftersom tärningarna då oftare är lägre än
påståendet. Att höja långt ökar alltså risken att åka dit.

När spelaren i stället slår finns ingen sann nivå att lägga sig strax över,
och kalkylen är en annan: ett lågt påstående är svårt för nästa spelare att slå
över, ett högt sätter press men synas oftare. Spelaren får titta på sina nya
tärningar innan den påstår. Väljer den bort titten vet den inget om utfallet.

Vem väger det ena mot det andra? Modellen. Koden räknar bara upp vilka
påståenden som är lagliga i läget, och modellen väljer bland dem. Den får
spelets ekonomi beskriven i ord – att ett påstående under tärningarna är säkert
och ett över är en bluff – men ingen färdig formel.

Repliken däremot skrivs inte av modellen. Den byggs i koden ur draget, så att en
spelare aldrig säger något annat än det hen faktiskt gjorde.

Axel är undantaget. Han har ingen modell utan spelar en fast räkneregel, och
hans speltaktik beskrivs i detalj längre fram. Samma räkneregel tar över om en
modell inte svarar.

### Hur spelaren bluffar

Tvånget att höja gäller alla lika. Bluffen är därför ingen ratt man skruvar på
— den följer av spelet.

Här går spelarna isär. **Axel**, den fasta räkneregeln, bluffar aldrig
frivilligt: han säger vad tärningarna visar och ljuger bara när regeln tvingar
honom. **Berit, Cecilia och David**, som styrs av en språkmodell, får välja själva
och kan höja över sina tärningar om de tror att det lönar sig.

Det som skiljer profilerna åt är hur de hanterar tvånget. En försiktig spelare
synar mer sällan, vilket gör att en bluff oftare får stå. En oförutsägbar spelare
tar ibland ett större kliv än nödvändigt, så att motståndaren inte kan läsa
mönstret. Ingen av dem har en inställning som heter "bluffa mer". Parametrarna
säger hur spelaren brukar göra, inte vilket drag som är bäst i läget.

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

### Så spelar Axel – du kan spela som han

Axel har ingen språkmodell. Varje drag räknas fram ur samma fasta regel, och
regeln går att lära sig. Det här avsnittet är skrivet så att du kan sitta vid
ett riktigt bord och göra samma sak som han.

Två saker gäller hela tiden. Han räknar i liv, inte i vunna rundor: att vinna
en runda är inget värt i sig. Och han har bara en enda fast tro om bordet – hur
ofta en syn brukar lyckas på en viss nivå. Han lär sig inget om dig som person.

Om du vill följa honom exakt: skruva ner hans oförutsägbarhet till noll. Då
gäller tabellerna nedan utan undantag.

#### Runda för runda: så sitter han vid bordet

**När det är hans tur att öppna rundan** tittar han i bägaren och säger vad
tärningarna visar. Inget mer. Visar de 43 säger han 43. Visar de 31 säger han
31. Han ljuger inte frivilligt.

| Tärningarna visar | Han säger |
|---|---|
| vilket värde som helst | samma värde |

Det enda undantaget är när ett högre påstående redan ligger. Då måste han höja
enligt regeln, och om tärningarna inte täcker höjningen blir påståendet osant.
Det är regelns verkning, inte ett val. Den situationen kallas **tvingad
höjning** och finns längre ner.

**När någon annan har påstått** har han inte sett tärningarna. Då väger han
tre svar mot varandra och tar det som är värt mest i liv. Svaren kommer i
regelbokens ordning:

| Påståendet han får | Han gör |
|---|---|
| 21, 11, 22, 33, 44, 55, 66, 65, 64 | **syna** |
| 63, 62, 61, 54, 53, 52, 51, 43, 42 | **skicka vidare** |
| 41, 32, 31 | **slå** |

Skälet till att han synar de låga påståendena är inte att de är bluffar. Det
är att nästan varje slag ligger **under** dem. Säger någon 11 är det bara
Meier som slår det, alltså vinner synen i 96 fall av 100. Säger någon 22 vinner
synen i 94. Ju högre påståendet blir, desto fler slag ligger över det, och då
blir synen sämre än att bära påståendet vidare.

Vid 64 vinner synen fortfarande i 65 fall av 100. Vid 63 har det jämnat ut sig
helt: där skiljer det en halv tusendels liv mellan att syna och att skicka
vidare, så 63 är i praktiken ett myntkast för honom.

Två rader i tabellen ser bakvända ut men är rätt. **31 synar han aldrig** –
bara Meier är högre, så där finns allt att vinna på att slå i stället. **61 och
62 synar han inte** trots att de ligger högt, för att bära dem är billigare.

**När han slår** skakar han bägaren på nytt och lyfter på locket. Tärningarna
är nya och ingen har påstått något om dem, så det finns inget att dölja. Räcker
det han ser över det förra påståendet säger han det. Räcker det inte säger han
nästa steg i ordningen.

Att avstå från att titta är ett eget val. Axel gör det aldrig.

**När bägaren gått ett varv** måste han höja. Tärningarna slås om och han
väljer först, tittar sedan. Står påståendet redan på Meier finns inget högre:
då slår han om bägaren och börjar en ny runda, och valet faller bort.

#### Ett parti att följa

Tre spelare: Axel, Berit och Cecilia. Alla har tre liv. Turen går Axel → Berit
→ Cecilia.

**Axel öppnar rundan.** Han tittar i bägaren och ser 31. Han säger **31**, för
det är vad tärningarna visar. Ingen bluff.

**Berit får 31.** Tabellen säger **slå** på 31, så hon skakar om bägaren. Hon
lyfter på locket och ser 64. Det räcker gott över 31, så hon säger **64**.

**Cecilia får 64.** Tabellen säger **syna** på 64, så hon lyfter på locket.
Tärningarna visar 64 och påståendet var 64. Värdet är alltså inte lägre än
påståendet, och då förlorar den som synade: **Cecilia förlorar ett liv**.

Nästa runda börjar hos spelaren före Cecilia, alltså Berit.

**Runda 2.** Berit öppnar. Hon skakar bägaren, ser 63 och säger **63**. Cecilia får 63 och
**skickar vidare**. Axel får 63 och **skickar vidare**. Nu har påståendet gått
ett helt varv och är tillbaka hos Berit, som måste höja.

Hon slår om bägaren och tittar. Nu visar tärningarna 31 – långt under det hon
måste höja över. Men regeln säger att den som slår måste säga högre, så hon
säger **64**. Här är hon tvingad att ljuga.

Cecilia får 64 och **synar**. Tärningarna visar 31 mot påståendet 64, och
**Berit förlorar ett liv**.

Lägg märke till tre saker. Axel bluffade aldrig i det här partiet – han sa 31
när han hade 31. Berit ljög, men bara när regeln tvingade henne att höja. Och
hon höjde alltid bara ett steg, aldrig mer.

#### Fem regler att ta med till bordet

1. **Öppnar du rundan: säg vad tärningarna visar.** Alltid. Ingen bluff.
2. **Får du ett påstående på 21, 11, 22, 33, 44, 55, 66, 65 eller 64, syna.**
   Där ligger nästan varje slag under påståendet, så synen vinner.
3. **Får du 63, 62, 61, 54, 53, 52, 51, 43 eller 42, skicka vidare.** Bär
   påståendet i stället för att betala för en syn.
4. **Får du 41, 32 eller 31, slå.** Där finns inget att förlora på att skaka
   om bägaren.
5. **Ljög du? Då var du tvingad.** Den som måste höja över ett påstående som
   tärningarna inte täcker har inget val. Höj då bara ett steg, aldrig mer.

Regel 2 och 3 är de som skiljer honom från en nybörjare. De flesta synar för
sällan på låga påståenden och för ofta på höga. Axel gör tvärtom: han synar när
synen är som säkrast, alltså på de låga.

#### Varför han inte bluffar

En bluff kan bara löna sig om motståndaren lägger sig. Då vinner man inget liv
– man slipper bara en syn. Men den som slår måste alltid höja, och då blir en
del påståenden osanna ändå. Lögnen kommer alltså av sig själv när den behövs.
Att ljuga i onödan lägger bara till en risk utan att köpa något.

Det här är en förenkling av simulatorn, inte en sanning om Meier. En människa
kan bluffa för att bli svårläst. Den mekanismen finns inte här: Axel lär sig
inget om dig under matchen, så det finns ingen att luras.

#### Det han aldrig gör

Han lär sig inget om dig under matchen – samma regler gäller i runda 1 som i
sista rundan. Han satsar inte på att vinna rundan, utan på att överleva
matchen. Och han ljuger aldrig för nöjes skull, bara när regeln tvingar honom.

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
