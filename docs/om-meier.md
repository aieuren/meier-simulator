# Om Meier – vad det här är och vad det ger

En kort genomgång för dig som är nyfiken men inte ska bygga vidare på koden.
Inga formler, ingen installation. Bara vad grejen är, vad spelarna gör och vad
vi hittills lärt oss.

Vill du köra igång själv: se [README](../README.md). Vill du ha hela tekniska
modellen: se [agent-model.md](agent-model.md).

---

## Vad är det här?

Fyra AI-spelare som spelar det svenska tärningsspelet **Meier** mot varandra.
Varje spelare drivs av en språkmodell, och varje spelare har sin egen
personlighet: en är feg, en bluffar mycket, en räknar mycket.

Du kan sitta vid sidan och titta på när de spelar. Du kan också själv mata in
ett tärningsslag och se vad en spelare skulle svara. Och du kan låta dem spela
hundratals matcher och få statistik på hur det gick.

**Vad det inte är:** ett försök att hitta den bästa strategin. Vi bygger en
*maskin för att förstå Meier* – ett slags laboratorium. Att vinna är inte
poängen. Poängen är att kunna se vad som händer när en spelare bluffar, när en
annan synar, och vad som faktiskt lönar sig.

---

## Spelet, på en minut

Två tärningar i en bägare med lock. Tärningarna läses som ett tal med den
högsta först **först**: 2 och 5 blir **52**.

**21 kallas Meier och är högst.** Sedan faller ordningen:

> 21, 11, 22, 33, 44, 55, 66, 65, 64, 63, 62, 61, 54, 53, 52, 51, 43, 42, 41, 32, 31

Lägg märke till att 11 är näst bäst och 31 sämst. **Par slår singlar** – 44 slår
alltså 65. Det är med flit förvirrande, och det är hela charmen.

En **runda** är från första budet till dess att någon **synar**. I praktiken
slutar alltså varje runda med att någon förlorar liv – oftast ett, ibland två.
Så här går den, i korthet:

1. Du skakar bägaren, tittar **i smyg**, och säger ett resultat: sant, högre
   eller lägre.
2. Nästa spelare **slår** (höjer blint), **synar** (lyfter locket) eller
   **skickar vidare** (samma bud, samma tärningar, men du tar över ansvaret).
3. **Meier kostar dubbelt** – både som bud och som visat resultat vid syn.

En **match** är många rundor i följd. Varje spelare har tre liv, och i stort
sett varje runda kostar någon ett liv. När man mist sina tre liv är man ute.
Sist kvar vinner matchen. En match tar i snitt knappt tio rundor.

Den fullständiga regeltexten, med undantagen om Meier-varvet och vem som
förlorar liv vid syn, står i [`docs/regler/meier-regler.md`](regler/meier-regler.md).
Den filen är den kanoniska versionen. Avviker den här sammanfattningen från den
har den här fel.

### Tärningarna är inte kubiska

Det här är en finurlighet som många inte känner till: tärningarna är
**avlånga**. Ändytorna (1 och 2) är kvadratiska, långytorna (3–6) är längre.
Därför är 3–6 ungefär 1,3 gånger så sannolika som 1–2.

Vad det gör med spelet:

| Utfall | Avlång tärning | Vanlig kub |
|---|---:|---:|
| 21 (Meier) | 3,9 % | 5,6 % |
| 11 | 1,9 % | 2,8 % |
| 65, 64, 63, 54, 53, 43 | 6,5 % | 5,6 % |

Alltså: **Meier och 11 blir ovanligare**, medan höga utfall där båda
tärningarna är 3–6 blir vanligare. Udda och jämnt förblir ändå lika sannolikt.

Det spelar roll för bluffandet. Ett bud på 65 är rimligare än ett bud på 21.

---

## De fyra spelarna

Personligheten sitter i tre rattar, inte i namnet. Varje ratt går från 0 till 1.

- **risk** – hur gärna spelaren synar och tar en chans
- **press** – hur ofta spelaren bluffar och pressar budet
- **läsning** – hur mycket spelaren låter motståndarnas beteende styra

| Spelare | risk | press | läsning | LLM | Karaktär |
|---|---:|---:|---:|---|---|
| **Axel** | 0,50 | 0,50 | 0,00 | nej | Basmodellen. Fast mätsticka. |
| **Berit** | 0,25 | 0,25 | 0,15 | ja | Försiktig. Bjuder nära sanningen. |
| **Cecilia** | 0,50 | 0,45 | 0,50 | ja | Kalkylerande. Läser motståndaren. |
| **David** | 0,65 | 0,60 | 0,35 | ja | Djärv. Pressar budet högre. |

**Axel är referensen.** Han har ingen språkmodell alls, spelar alltid likadant
och ändrar sig aldrig. Han är måttstocken de andra jämförs mot. Han är byggd
för att vara "tillräckligt bra", inte optimerad – och som mätningarna nedan
visar räcker det långt.

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

En bluff läggs därför alltid på den **minsta möjliga höjningen**. Ett högre bud
synas nämligen oftare (en syn på 66 är billigare än en syn på 51, eftersom
tärningarna då oftare är lägre än budet). Att höja längre ökar alltså bara
risken att åka dit, utan att ge något tillbaka.

Så när en spelare bjuder 51 på tärningarna 43 är det inget misstag. Den har
vägt chansen att bli synad (omkring 20 % på den nivån) mot livskostnaden, och
kommit fram till att chansningen lönar sig.

### Spelaren bluffar med flit

En vanlig missuppfattning är att en AI-spelare "ljuger" när den råkar säga fel.
Så är det inte här. Bluffen är ett **aktivt val**, och hur ofta spelaren
bluffar styrs av `press`.

Mätt över 200 matcher utan språkmodell:

| Spelare | Bluffar i |
|---|---:|
| Berit | 46 % |
| Cecilia | 63 % |
| Axel | 63 % |
| David | 72 % |

Berit, som är feg, bjuder oftast sanningen. David, som är djärv, bluffar nästan
tre gånger av fyra.

En nyans värd att känna till: `press` styr bluffrekvensen i **skarpt spel**, men
i det enklaste läget – ett enda slag utan motståndare att läsa – skiljer sig
spelarna mindre än man kunde tro. Vid 52 säger Berit 52 medan de andra säger 53.
Skillnaden är verklig men liten. Det är först över många matcher, när läget och
motståndarna spelar in, som personligheterna verkligen märks.

### Spelaren läser sina motståndare

Här kommer språkmodellen in. Spelaren får en sammanställning av vad motståndaren
gjort tidigare – hur ofta hen bluffat, hur ofta hen synat, hur ofta hen höjt –
och **modellen tolkar siffrorna**. Den avgör om motståndaren ska ses som
försiktig, djärv eller oberäknelig.

Två saker är viktiga här:

**Modellen får aldrig se dolda tärningar.** Den får bara det som varit
offentligt. Annars skulle läsningen vara fusk.

**Modellen får inte bestämma draget.** Den tolkar och beskriver. Själva beslutet
tas av en beräkning som är densamma för alla spelare. Det gör att en spelare
aldrig kan spela sämre för att modellen skriver en dålig mening.

### Spelaren litar inte fullt på sin egen läsning

Det här är den nyaste delen, och den är värd att förklara.

En språkmodell är väldigt säker på sin sak, även när den knappt har något att
gå på. Fråga den efter en enda syn och den svarar "jag är helt säker". Det är
farligt: en spelare som agerar på en tunn gissning som vore den ett faktum
spelar sämre än en som inte läser alls.

Därför har läsningen ett **tak som sätts av bordet, inte av modellen**. Antalet
synar som faktiskt avgjorts bestämmer hur mycket läsningen får väga:

| Synar vid bordet | Hur mycket får läsningen väga |
|---|---:|
| 0 | 0 % |
| 1 | 25 % |
| 3 | 50 % |
| 9 | 75 % |

Modellen får säga "jag är säker", men taket gäller ändå. En bild byggd på en
enda syn väger en fjärdedel av en mogen bild.

Samma princip gäller åt andra hållet: en motståndare som synar ofta gör varje
bluff dyrare, så spelaren bluffar mindre mot hen. Mätt i ett kontrollerat läge
(20 möjliga tärningsutfall, mot en motståndare med känd synfrekvens):

| Motståndaren synar | Spelaren bluffar i |
|---|---:|
| 5 % | 20 av 20 lägen |
| 19 % (normalt) | 11 av 20 lägen |
| 45 % | 3 av 20 lägen |

Mot en som aldrig synar är det alltså fritt fram. Mot en som synar ofta lönar
sig bara de bud som är nästan säkra.

---

## Vad mätningarna visar

200 matcher, fyra spelare, ingen språkmodell inblandad (så att det går att
upprepa exakt). En slumpmässig spelare skulle vinna 25 % av gångerna.

| Spelare | Vinster | Synar i |
|---|---:|---:|
| Axel | 31 % | 18 % |
| Berit | 29 % | 18 % |
| Cecilia | 26 % | 18 % |
| David | 15 % | 22 % |

En match tar i snitt **9,4 rundor**.

Tre saker är värda att notera:

**David vinner minst.** Han pressar mest (0,60) och bluffar mest (72 %). Det
straffar sig: hög press bluffar rakt in i synar. Det stämmer med vad de
historiska loggarna visade – en extremt pressande profil förlorade nästan varje
match.

**Axel, som inte läser alls, vinner mest.** Han är enkel, förutsägbar och
fungerar. Det är en nyttig påminnelse: i ett spel med mycket tur slår en stabil
grundstrategi ofta en sofistikerad.

**Alla synar ungefär lika ofta** (18–22 %), trots att deras `risk` skiljer sig.
Synfrekvensen är alltså inte bara en fråga om personlighet – spelets läge tvingar
fram synar.

Och en varning: **200 matcher är inte mycket**. Skillnaderna mellan Axel, Berit
och Cecilia ligger inom felmarginalen. Vi drar inga säkra slutsatser av dem.

---

## Vad du kan göra i webbappen

- **Spelarna** – de fyra spelarna och deras personligheter.
- **Enskild spelare** – skriv in två tärningar och se vad en spelare svarar.
  Det här är det enklaste sättet att se bluffandet i aktion.
- **Fyra spelare** – fyra spelare spelar mot varandra, ett steg i taget eller
  hela matchen. Loggen visar varje bud, varje syn och vem som förlorade liv.
- **Matchserie** – kör många matcher och få statistik.
- **Analys** – ladda upp loggarna och ställ frågor om materialet. Svaren kommer
  från en språkmodell och kan innehålla diagram.

---

## Det roligaste att prova

Skriv in **4 och 3** (alltså 43) i fliken *Enskild spelare*. Berit säger 43,
alltså sanningen. Axel, Cecilia och David säger 51 – en ren bluff. Samma
tärningar, samma regler, olika personlighet. Det är hela poängen med projektet.

Prova sedan **2 och 5** (52). Då säger Berit 52 och de andra 53. Skillnaden är
mindre, men mönstret detsamma: Berit håller igen, de andra tar chansen.

Prova också **1 och 2** (21, Meier). Då ser du att spelet inte bara handlar om
att ljuga: Meier är så starkt att alla fyra bjuder det direkt, utan att tveka.
