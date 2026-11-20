# Om Meier – vad det här är

En kort genomgång för dig som är nyfiken men inte ska bygga vidare på koden.
Inga formler, ingen installation. Bara vad grejen är och vad spelarna gör.

Vill du köra igång själv: se [README](../README.md). Vill du ha hela tekniska
modellen: se [agent-model.md](agent-model.md).

---

## Vad är det här?

Fyra AI-spelare som spelar det svenska tärningsspelet **Meier** mot varandra.
Varje spelare har sin egen **profil** – alltså sin egen spelstil – och de spänner
från försiktig till djärv och kalkylerande. Tre av dem drivs av en språkmodell.

Du kan sitta vid sidan och titta på när de spelar. Du kan också själv mata in
ett tärningsslag och se vad en spelare skulle svara. Och du kan låta dem spela
många matcher i följd.

**Vad det inte är:** ett försök att hitta den bästa strategin. Vi bygger en
*maskin för att förstå Meier* – ett slags laboratorium. Att vinna är inte
poängen. Poängen är att maskinen går att köra, går att upprepa och går att
fråga. Vad den sedan visar är en senare fråga.

---

## Spelet, på en minut

Två tärningar i en bägare med lock. Tärningarna läses som ett tal med den
högsta först **först**: 2 och 5 blir **52**.

**21 kallas Meier och är högst.** Sedan faller ordningen:

> 21, 11, 22, 33, 44, 55, 66, 65, 64, 63, 62, 61, 54, 53, 52, 51, 43, 42, 41, 32, 31

Lägg märke till att 11 är näst bäst och 31 sämst. **Par slår singlar** – 44 slår
alltså 65. Det är med flit förvirrande, och det är hela charmen.

En **runda** är från första budet till dess att någon **synar**. Så här går
den, i korthet:

1. Du skakar bägaren, tittar **i smyg**, och säger ett resultat: sant, högre
   eller lägre.
2. Nästa spelare **slår** (höjer blint), **synar** (lyfter locket) eller
   **skickar vidare** (samma bud, samma tärningar, men du tar över ansvaret).
   Den som skickar vidare tittar inte – att lyfta locket är att syna.
3. **Meier kostar dubbelt** – både som bud och som visat resultat vid syn.

En **match** är många rundor i följd. Varje spelare har tre liv. När man mist
sina tre liv är man ute. Sist kvar vinner matchen.

Den fullständiga regeltexten, med undantagen om Meier-varvet och vem som
förlorar liv vid syn, står i [`docs/regler/meier-regler.md`](regler/meier-regler.md).
Den filen är den kanoniska versionen. Avviker den här sammanfattningen från den
har den här fel.

### Tärningarna är inte kubiska

Det här är en finurlighet som många inte känner till: tärningarna är
**avlånga**. Ändytorna (1 och 2) är kvadratiska, långytorna (3–6) är längre.
Längden är ungefär 1,3 gånger bredden.

**Maskinen antar** att chansen för en sida följer sidans area. Då blir 3–6
exakt 1,3 gånger så sannolika som 1–2, eftersom långytan har arean bredd gånger
längd medan ändytan har arean bredd gånger bredd.

Det är ett antagande, inte en fysikalisk sanning. Den vanligaste modellen för en
kropp som kastas slumpmässigt väger sidorna efter **rymdvinkeln** från
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

Alltså: **Meier och 11 blir ovanligare**, medan höga utfall där båda
tärningarna är 3–6 blir vanligare. Udda och jämnt förblir ändå lika sannolikt,
eftersom 1 och 2 ligger på ändytorna (en udda, en jämn) och 3–6 på långytorna.

Det är den fördelning maskinen använder när den slår tärningarna.

---

## De fyra spelarna

Spelarens **egen profil** sitter i tre parametrar, inte i namnet. Varje parameter
går från 0 till 1.

- **`risk`** – riskbenägenhet: hur gärna spelaren synar och tar en chans
- **`press`** – press: hur ofta spelaren bluffar, och hur högt den lägger det
  blinda budet
- **`reading`** – läsförmåga: hur mycket spelaren låter information om andras
  tidigare spel styra

| Spelare | risk | press | läsförmåga | LLM | Profil |
|---|---:|---:|---:|---|---|
| **Axel** | 0,50 | 0,50 | 0,00 | nej | Grundtaktik. Fast mätsticka. |
| **Berit** | 0,25 | 0,25 | 0,15 | ja | Försiktig. Bjuder nära sanningen. |
| **Cecilia** | 0,50 | 0,45 | 0,50 | ja | Kalkylerande. Läser motståndaren. |
| **David** | 0,65 | 0,60 | 0,35 | ja | Djärv. Pressar budet högre. |

**Axel är referensen.** Han har ingen språkmodell alls, spelar alltid likadant
och ändrar sig aldrig. **Han deltar i matcherna – jämförelsenivån sitter alltså
i spelet, inte på en hylla.** De andras resultat mäts mot hans. Han är byggd för
att vara "tillräckligt bra", inte optimerad. Hans uppsättning kallas
**grundtaktik**.

Tre begrepp som är lätta att blanda ihop:

| Begrepp | Vad det är |
|---|---|
| **Egen profil** | Spelarens egna `risk`, `press` och `reading`. Känd för spelaren själv. |
| **Motståndarprofil** | Spelarens **gissning** om en annan spelares `risk` och `press`. Byggd enbart på offentligt beteende. |
| **Motståndartyp** | Kort etikett som sammanfattar motståndarprofilen, till exempel "bluffbenägen". |

Spelaren känner **aldrig** en motståndares verkliga parametrar. Den gissar, och
gissningen kan vara fel. Det är skillnaden mellan profil och motståndarprofil.

---

## Hur en spelare tänker

Det här är den intressanta delen.

### Spelaren ser inte allt

En spelare vet bara tre saker: sina egna tärningar, vad som sagts högt, och vad
som hänt tidigare i matchen. Den vet **inte** vad motståndaren har i bägaren.
Allt den tror om andra är en gissning byggd på offentligt beteende.

Det låter självklart, men det är hela spelet. Om spelaren fick se allt skulle
det inte finnas något att bluffa om.

### Spelaren väger risk mot vinst

Varje beslut är en avvägning mellan två saker: **chansen att slippa bli synad**
och **vad det kostar om du blir synad**.

Att bjuda exakt det tärningarna visar är **säkert**. Blir du synad vinner du
rundan, för tärningarna visar då minst budet.

Att bjuda högre är en bluff. Blir du synad **förlorar du ett liv** (två om budet
är Meier), för tärningarna visar då mindre än du sa. En bluff som avslöjas ger
dig alltså ingenting.

Så vad köper en bluff? Att motståndaren får ett **svårare beslut**. Hen måste
antingen syna ett bud hen misstror, eller slå blint till något ännu högre – och
då ta över risken själv. En bluff är inte "värd mer". Den flyttar risken över
till motståndaren, och den lönar sig bara när motståndaren hellre avstår från
att syna än tar den chansen.

Här är det lätt att tro att det finns en enda regel, men maskinen fattar **två
olika slags höjningar**, och de fungerar olika.

**När spelaren har sett sina tärningar** och bluffar över det hen såg, väljer
hen den **minsta möjliga höjningen**. Ett högre bud synas nämligen oftare: en
syn på 66 är billigare för motståndaren än en syn på 51, eftersom tärningarna
då oftare är lägre än budet. Att höja längre ökar alltså bara risken att åka
dit, utan att ge något tillbaka. Här höjs det därför bara ett enda steg, aldrig
flera.

**När spelaren slår blint** vet hen inte alls vad tärningarna visar. Då finns
ingen "sann" nivå att lägga sig strax över, och då är kalkylen en annan. Här
bestämmer `press` hur högt budet läggs: låg press lägger sig nära minimum, hög
press tar ett språng uppåt för att sätta motståndaren i ett dyrare läge. Det är
ett medvetet val i modellen, inte en sanning om spelet – ett språng är farligare
om det blir synat, men svårare att värja sig mot.

Så: **minsta höjning gäller bluffen över sedda tärningar.** Den blinda
höjningen styrs av `press`. Det är två skilda beslut i koden
(`decide_bid` respektive `decide_raise`).

### Spelaren bluffar med flit

En vanlig missuppfattning är att en AI-spelare "ljuger" när den råkar säga fel.
Så är det inte här. Bluffen är ett **aktivt val**, och hur ofta spelaren
bluffar styrs av `press`.

En spelare med låg `press` bjuder oftast sanningen. En spelare med hög `press`
tar chansen oftare. Parametern styr hur ofta, inte vilken strategi som är bäst.

### Spelaren läser sina motståndare

Här kommer språkmodellen in. Arbetet är delat i två roller:

**Sekreteraren** bokför vad som hänt vid bordet. Rena siffror, ingen tolkning:
hur ofta motståndaren bluffat, hur ofta hen synat, hur ofta hen höjt.

**Läsaren** är språkmodellen. Den tolkar siffrorna och sätter en
**motståndarprofil**: en gissning om motståndarens `risk` och `press`, plus en
kort **motståndartyp** som "bluffbenägen", "försiktig" eller "oförutsägbar", och
ett mått på hur säker gissningen är.

Två saker är viktiga här:

**Modellen får aldrig se dolda tärningar.** Den får bara det som varit
offentligt. Annars skulle läsförmågan vara fusk.

**Modellen får inte bestämma draget.** Den tolkar och beskriver. Själva beslutet
tas av en beräkning som är densamma för alla spelare. Det gör att en spelare
aldrig kan spela sämre för att modellen skriver en dålig mening.

### Spelaren litar inte fullt på sin egen läsförmåga

Det här är den nyaste delen, och den är värd att förklara.

En språkmodell är väldigt säker på sin sak, även när den knappt har något att
gå på. Fråga den efter en enda syn och den svarar "jag är helt säker". Det är
en risk: en spelare som agerar på en tunn gissning som vore den ett faktum
låter brus styra spelet.

Därför har läsförmågan ett **tak, och taket sätts av bordet — inte av modellen
och inte av den enskilda motståndaren**. Här är det lätt att blanda ihop två
saker:

- **Motståndarprofilen** gäller **en** motståndare i taget. Den byggs bara på
  vad just den spelaren gjort.
- **Taket** för hur mycket läsförmågan får väga gäller **hela bordet**. Det räknar
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
bluff dyrare, så spelaren bluffar mindre mot hen. Maskinen räknar med
motståndarens synfrekvens när den väljer bud. Mot en som sällan synar är det
friare fram; mot en som synar ofta lönar sig bara de bud som är nästan säkra.

---

## Vad du kan göra i webbappen

- **Spelarna** – de fyra spelarna och deras profiler.
- **Enskild spelare** – skriv in två tärningar och se vad en spelare svarar.
  Det här är det enklaste sättet att se bluffandet i aktion.
- **Fyra spelare** – fyra spelare spelar mot varandra, ett steg i taget eller
  hela matchen. Loggen visar varje bud, varje syn och vem som förlorade liv.
- **Matchserie** – kör många matcher och få statistik.
- **Analys** – ladda upp loggarna och ställ frågor om materialet. Svaren kommer
  från en språkmodell och kan innehålla diagram.

---

## Vad resultaten betyder

Maskinen mäter ingenting åt dig, men den ger underlag. Efter en matchserie kan
du titta på två frågor:

- **Vilken spelstil som vinner oftast.** I Meier är de två samma sak: den som
  står kvar sist har vunnit, för den som mist tre liv är ute. Överlevnad är
  spelets enda mått, och därför finns det ingen poängliga att titta på.
- **Om läsförmågan lönar sig.** Cecilia läser motståndarna, Berit nästan inte.
  Går det att se någon skillnad mellan dem, eller väger tur och bordets övriga
  spelare tyngre?

Om det sista: `reading` är medvetet satt lågt, och taket för hur mycket
läsförmågan får väga är strängt. Det betyder inte att läsförmåga är värdelös –
det betyder att modellen inte vill överskatta en gissning byggd på få synar. Om
läsförmågan inte syns i siffrorna är det en upplysning om modellen, inte om
spelet.

En viktig varning: **enstaka matcher säger nästan ingenting.** Meier har hög
slump i sig, och fyra spelare med liv som tar slut gör att en enskild match kan
vända på en enda syn. Det är mönstret över många matcher som är intressant. Kör
hellre flera hundra än tio, och titta på hela bilden i stället för att jaga
förklaringar till en enskild förlust.

---

## Vad du kan prova

Öppna fliken *Enskild spelare* och mata in två tärningar. Du får se vad varje
spelare svarar på samma slag. Samma tärningar, samma regler, olika profil – det
är själva poängen med maskinen.

Prova samma slag med flera spelare och jämför. Prova också att köra en hel
match och läsa loggen: varje bud, varje syn och vem som förlorade liv står
med.
