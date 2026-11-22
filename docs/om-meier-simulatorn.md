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

Maskinen antar att chansen för en sida följer sidans area. Då blir 3–6
exakt 1,3 gånger så sannolika som 1–2, eftersom långytan har arean bredd gånger
längd medan ändytan har arean bredd gånger bredd.

Det är ett antagande, inte en fysikalisk sanning. Den vanligaste modellen för en
kropp som kastas slumpmässigt väger sidorna efter rymdvinkeln från
masscentrum. För samma form blir förhållandet då 1,56 i stället för 1,30, och
Meier blir 2,9 % i stället för 3,9 %. Skillnaden är liten, men den finns. Arean
är vald för att den är enkel att förklara och kontrollera. Vilken modell som är
rätt för Meiers tärningar vet vi inte.

Med areamodellen blir fördelningen så här:

| Utfall | Avlång tärning | Vanlig kub |
|---|---:|---:|
| 21 (Meier) | 3,9 % | 5,6 % |
| 11 | 1,9 % | 2,8 % |
| 65, 64, 63, 54, 53, 43 | 6,5 % | 5,6 % |

Alltså: Meier och 11 blir ovanligare, medan höga utfall där båda
tärningarna är 3–6 blir vanligare. Udda och jämnt förblir ändå lika sannolikt,
eftersom 1 och 2 ligger på ändytorna (en udda, en jämn) och 3–6 på långytorna.

Det är den fördelning maskinen använder när den slår tärningarna.

---

## De fyra spelarna

Spelarens egen profil sitter i tre parametrar, inte i namnet. Varje parameter
går från 0 till 1.

- `risk` – riskbenägenhet: hur gärna spelaren synar och tar en chans
- `press` – press: hur ofta spelaren bluffar, och hur högt hen påstår när
  hen slår
- `reading` – läsförmåga: hur mycket spelaren låter information om andras
  tidigare spel styra

| Spelare | risk | press | läsförmåga | LLM | Profil |
|---|---:|---:|---:|---|---|
| **Axel** | 0,50 | 0,50 | 0,00 | nej | Grundtaktik. Fast mätsticka. |
| **Berit** | 0,25 | 0,25 | 0,15 | ja | Försiktig. Påstår nära sanningen. |
| **Cecilia** | 0,50 | 0,45 | 0,50 | ja | Kalkylerande. Läser motståndaren. |
| **David** | 0,65 | 0,60 | 0,35 | ja | Djärv. Pressar påståendet högre. |

Axel är referensen. Han har ingen språkmodell alls, spelar alltid likadant
och ändrar sig aldrig. De andras resultat mäts mot hans. Han är byggd för att
vara "tillräckligt bra", inte optimerad. Hans uppsättning kallas
grundtaktik.

Tre begrepp:

| Begrepp | Vad det är |
|---|---|
| **Egen profil** | Spelarens egna `risk`, `press` och `reading`. Känd för spelaren själv. |
| **Motståndarprofil** | Spelarens gissning om en annan spelares `risk` och `press`. Byggd enbart på offentligt beteende. |
| **Motståndartyp** | Kort etikett som sammanfattar motståndarprofilen, till exempel "bluffbenägen". |

Spelaren känner aldrig en motståndares verkliga parametrar. Den gissar, och
gissningen kan vara fel. Det är skillnaden mellan profil och motståndarprofil.

---

## Hur en spelare tänker

### Spelaren ser inte allt

En spelare vet bara tre saker: sina egna tärningar, vad som sagts högt, och vad
som hänt tidigare i matchen. Den vet inte vad motståndaren har i bägaren.
Allt den tror om andra är en gissning byggd på offentligt beteende.

Om spelaren fick se allt skulle det inte finnas något att bluffa om.

### Spelaren väger risk mot vinst

Modellen bestämmer draget. Den väljer fritt bland de lagliga alternativen, men
den kan aldrig bryta mot reglerna: koden räknar upp vad som är tillåtet i läget
och modellen väljer inom den listan.

Varje beslut är sedan en avvägning mellan två saker: chansen att slippa bli
synad och vad det kostar om du blir synad.

Att påstå exakt det tärningarna visar är säkert. Blir du synad vinner du
rundan, för tärningarna visar då minst påståendet.

Att påstå högre är en bluff. Blir du synad förlorar du ett liv (två om påståendet
är Meier), för tärningarna visar då mindre än du sa. En bluff som avslöjas ger
dig alltså ingenting.

Så vad köper en bluff? Att motståndaren får ett svårare beslut. Hen måste
antingen syna ett påstående hen misstror, eller slå om bägaren till något ännu
högre – och då ta över risken själv. En bluff är inte "värd mer". Den flyttar risken över
till motståndaren, och den lönar sig bara när motståndaren hellre avstår från
att syna än tar den chansen.

Det finns två slags höjningar, och de skiljer sig åt.

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
bluff lägger han sig på den minsta möjliga höjningen, och vid blindt slag
bestämmer `press` hur högt han går. Samma räkneregel tar över om en modell inte
svarar.

### Spelaren bluffar med flit

Bluffen är ett aktivt val, och hur ofta spelaren bluffar styrs av `press`.

En spelare med låg `press` påstår oftast sanningen. En spelare med hög `press`
tar chansen oftare. Parametern styr hur ofta, inte vilken strategi som är bäst.

### Spelaren läser sina motståndare

Här kommer språkmodellen in. Arbetet är delat i två roller:

Sekreteraren bokför vad som hänt vid bordet. Rena siffror, ingen tolkning:
hur ofta motståndaren bluffat, hur ofta hen synat, hur ofta hen höjt.

Läsaren är språkmodellen. Den tolkar siffrorna och sätter en
motståndarprofil: en gissning om motståndarens `risk` och `press`, plus en
kort motståndartyp som "bluffbenägen", "försiktig" eller "oförutsägbar", och
ett mått på hur säker gissningen är.

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

- Spelarna – de fyra spelarna och deras profiler.
- Enskild spelare – skriv in två tärningar och se vad en spelare svarar.
- Fyra spelare – fyra spelare spelar mot varandra, ett steg i taget eller
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
slump i sig, och fyra spelare med liv som tar slut gör att en enskild match kan
vända på en enda syn. Kör hellre flera hundra matcher än tio.

---

## Vad du kan prova

Öppna fliken *Enskild spelare*, välj en roll och mata in två tärningar. Du får
se vad just den spelaren svarar på slaget.

Byt sedan roll och slå samma tärningar igen. Samma slag, samma regler, olika
profil – det är själva poängen med maskinen.

Prova också att köra en hel match och läsa loggen: varje påstående, varje syn och
vem som förlorade liv står med.
