# Global Gaming

Communitybot voor Global Gaming met Fortnite, Minecraft, Rocket League, Roblox, Call of Duty, Among Us en GTA VI-discussies. De Engelstalige berichten en kaarten gebruiken neonblauw en felroze.

## Op je Windows-pc starten

1. Installeer **Python 3.12 of nieuwer met de Python Launcher** van [python.org](https://www.python.org/downloads/windows/).
2. Download `global-gaming-bot.zip` bij de [nieuwste release](https://github.com/vincebosps4-pixel/global-gaming-bot/releases/latest). Pak alles uit in een vaste map, bijvoorbeeld `C:\GlobalGaming`. Start niet vanuit de zip.
3. Dubbelklik op **START-HIER.cmd**. Plak de botsleutel wanneer daarom wordt gevraagd. De sleutel wordt niet zichtbaar getoond en blijft op deze pc in `config/token.txt`.
4. De eerste start installeert de onderdelen en voert de tests uit. Dit kan enkele minuten duren. **STATUS.cmd** toont of de bot verbonden is.
5. Laat de pc ingeschakeld, aangemeld en verbonden met internet. Het scherm mag vergrendeld zijn. Slaapstand of afsluiten maakt de bot offline. Na opnieuw aanmelden start de geplande taak de bot, als het aanmaken van die taak tijdens installatie gelukt is.

**START-BOT.cmd** zet de bot aan. **STOP-BOT.cmd** sluit hem netjes af en schakelt de automatische start uit. Er is geen betaald hostingabonnement nodig. Draai maar één exemplaar: de lokale vergrendeling voorkomt dubbele processen op dezelfde pc, niet op verschillende computers.

## Functies

- Persoonlijk welkomstbericht in `👋・welcome` voor nieuwe leden, met een lokaal gemaakt neonblauw/roze kaartje, hun Discord-profielfoto en naam, en knoppen voor regels en gamekeuzes. Geen externe afbeeldingsdienst nodig. Werkt terwijl de bot online is; geen inhaalberichten voor joins tijdens offline tijd en geen welkomstspam bij opstarten. Bots krijgen geen kaartje.
- 19 vaste informatie-embeds, inclusief de Among Us-chat en het groepszoekkanaal. Alleen eigen herkenbare berichten worden bijgewerkt.
- Eenmalige kanaalopmaak: `👋・welcome`, `💬・chat`, `🔎・looking-for-group` enzovoort. ID's en inhoud blijven behouden.
- Ticketpaneel met formulier en één open ticket per lid. Alleen de aanvrager, Support Team, serverbeheerders en bot kunnen het zien. Sluiten maakt het voor de aanvrager alleen-lezen; Support Team kan heropenen. Geen automatische verwijdering of externe transcripten.
- Giveaways met privévoorbeeld, publicatiebevestiging, deelnameknop, één deelname per account, eindtijd en willekeurige winnaars. Na een herstart blijven deelnemers en eenmaal getrokken winnaars behouden. Als de bot bij de eindtijd offline is, verwerkt hij de uitslag zodra hij online komt; late deelname is gesloten.
- Roze boostbedankjes wanneer Discord een boost-systeembericht verstuurt terwijl de bot online is. Zet deze systeemberichten aan in de serverinstellingen. Discord beheert zelf de Server Booster-rol.
- Discord Onboarding biedt acht optionele gamekeuzes, 31 landkeuzes en zes apparaatkeuzes. Zeven gamerollen geven toegang tot de bijbehorende categorie. Uitvinken verbergt die weer. Other Games, land en apparaat zijn profielrollen.

Giveaways beginnen pas nadat een beheerder een echte prijs, looptijd en regels heeft bevestigd. Er is geen wedstrijd met een verzonnen prijs gestart. GTA VI is een nieuws- en discussiecategorie; de bot haalt geen automatisch nieuws op.

## Discord-opdrachten

Met **/profile** ziet een lid eerst privé de eigen blauw-roze gamerkaart. Naam staat erop; avatar, games, apparaten, badges en level/XP zijn los aan of uit te zetten via het keuzemenu (ook alles uit). Games en apparaten volgen de huidige onboardingrollen. Deel vanuit een gewone community- of gamechat met **Share in this channel**. Zowel bot als lid moeten daar afbeeldingen mogen bijvoegen. Een eerder gedeelde kaart is een momentopname.

**Start earning XP** is optioneel en standaard uit. Een gewoon chatbericht of antwoord in een van de vaste community- of gamechats levert 10 XP op: maximaal eens per drie minuten en 100 XP per UTC-dag. Geen XP voor bots, webhooks, tickets, staff, privéberichten, threads, voice of offline activiteit. Elke 100 XP geeft een level. Badges: level 2 First Level-Up, 5 Squad Regular, 10 Veteran, 25 GG Legend. **Pause earning XP** stopt het verdienen en behoudt de voortgang. Levels en badges zijn cosmetisch; ze geven geen serverrechten. De host bewaart alleen het lid-ID, zichtbaarheid, deelnamekeuze, XP en de laatste beloningsperiode; geen berichttekst, avatar of rollenlijst.

| Opdracht | Functie |
|---|---|
| '/profile' | Persoonlijke gamerkaart, weergavekeuzes en optionele levels |
| `/community_help` | Privéoverzicht van tickets, giveaways en rolkeuzes |
| `/announce` | Aankondiging met privévoorbeeld en publicatieknop |
| `/welcome_preview` | Je eigen welkomstkaartje bekijken, alleen voor jou zichtbaar |
| `/welcome_member` | Als beheerder een gemist welkom na een offline join plaatsen voor één gekozen lid. De automatische en handmatige route delen dezelfde controle op dubbele kaartjes. |
| `/giveaway` | Gratis giveaway voorbereiden: prijs, minuten, winnaars, regels |
| `/giveaway_cancel` | Annuleren met bevestiging; bericht blijft behouden |
| `/setup_embeds` | Vaste embeds vernieuwen |
| `/setup_community` | Ticketpaneel en kanaalstijl instellen |
| `/bot_status` | Verbinding, timer en rechten controleren |

Beheeropdrachten eisen **Server beheren**, ook bij oude previewknoppen. Wijs Support Team alleen toe aan vertrouwde medewerkers. Leden krijgen geen opdrachten om willekeurige kanalen of rollen te veranderen.

## Rechten en gegevens

De bot is vastgezet op de bestaande Global Gaming-app en server. Nodig: kanalen bekijken, berichten versturen, links insluiten, berichtgeschiedenis lezen, kanalen beheren en rollen beheren; bovendien **Bestanden bijvoegen in welcome** voor de kaartjes. De beheerrechten dienen voor privé-ticketkanalen en hun toegangsrechten. Houd de botrol boven Support Team; **Administrator is niet nodig**. Bewaar de expliciete publicatierechten in de alleen-lezen START HERE-kanalen.

**Server Members Intent moet aan** op de [botpagina in het Discord Developer Portal](https://discord.com/developers/applications/1567606693674885302/bot), zodat Discord nieuwe leden aan de bot doorgeeft. Dit is ingesteld voor Global Gaming. Message Content en Presence blijven uit. De bot vraagt geen volledige ledenlijst op en bewaart geen lidcache. Hij ontvangt systeemberichten voor boosts, geen algemene berichtinhoud. Geen Welcomer, Ticket Tool, GiveawayBot of andere extra bot nodig.

Dubbele joinmeldingen worden per lid en joinmoment onderdrukt, ook na een herstart met dezelfde database. Bij een onduidelijke netwerkfout wordt niet blind opnieuw verstuurd: controleer dan welcome. Een mislukte verbinding kan dus een welkomstbericht missen. De normale afbeelding en naam worden in geheugen verwerkt; een niet-beschikbare profielfoto krijgt een neutrale avatar. Lange namen worden passend gemaakt. De volledige naam staat ook als Discord-tekst in de embed; beschikbare systeemlettertypen bepalen de schriftweergave op het kaartje.

Ticketinhoud blijft in Discord. Ticketmetadata, giveawayteksten, deelnemers-ID's, resultaten en de laatste welkomstregistratie per lid (ID, joinmoment en bericht-ID) staan in `data/community.sqlite3` op de host. Namen en profielfoto's worden niet in deze database opgeslagen. De repository en release bevatten geen sleutel of gebruikersgegevens. Bewaar `config/` en `data/` privé. Bij verhuizing: stop de oude bot en neem beide mappen mee om actieve tickets en giveaways te behouden.

## Automatische updates

Elke 30 minuten controleert de supervisor uitsluitend stabiele releases van **vincebosps4-pixel/global-gaming-bot**. Hij controleert downloadlocatie, checksum en toegestane bestanden, installeert elke versie apart en voert de tests uit terwijl de bestaande bot blijft draaien. Daarna herstart hij de bot. Werkt de nieuwe versie niet, dan valt hij terug op de vorige. Lokale sleutels en data worden niet door een release overschreven.

Updates ontstaan wanneer we code publiceren met een hoger nummer in `VERSION`. De bot schrijft geen eigen wijzigingen. De GitHub-workflow test op Windows en Linux voordat hij een release publiceert; er is geen Discord-sleutel nodig op GitHub. De vaste Windows-startomgeving is gescheiden van bijgewerkte botcode; een wijziging daarvan kan een nieuwe handmatige installatie vereisen.

Updates pauzeren: maak een leeg bestand `config/PAUSE-UPDATES`; verwijder dat om updates te hervatten. Logs staan in `logs/`. Bij een mislukte eerste installatie is er nog geen vorige versie beschikbaar.

## Ontwikkelen en Docker

```text
python -m pip install -r requirements.txt
python -m unittest discover -s . -p "test_*.py" -v
python bundle.py dist
```

Direct starten: zet `DISCORD_BOT_TOKEN` in hostgeheimen of lokale `.env`, kies een blijvende `DATA_DIR` en voer `python bot.py` uit. `AUTO_SETUP=true` vernieuwt embeds en ticketinrichting; de kanaalnamen worden slechts eenmaal per database gewijzigd. `PUBLISH_ONCE=true` publiceert en sluit af; knoppen en timers vereisen daarna een draaiende bot. `SUPPORT_ROLE_ID` kan de unieke Support Team-rol expliciet aanwijzen.

Docker: bouw de Dockerfile, geef de sleutel als geheime variabele door, koppel een volume aan `/data` en gebruik `--restart unless-stopped`. De Windows-supervisor wordt niet in Docker gebruikt.

Databasemigraties moeten aanvullend en achterwaarts compatibel blijven. Een rollback behoudt de huidige data; hij draait geen uitgevoerde Discord-acties terug.

Documentatie: [discord.py](https://discordpy.readthedocs.io/en/stable/), [Discord-kanaalrechten](https://docs.discord.com/developers/resources/channel#edit-channel-permissions), [GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).
