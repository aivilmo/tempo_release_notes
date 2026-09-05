# Tempo 2.1.0

> ⚠ **Vóór het upgraden — actie vereist**
>
> - De omgevingsvariabele `db_url` is hernoemd naar `TEMPO_DATABASE__URL`—werk je implementatieconfiguratie bij vóór de upgrade, anders zal de applicatie niet starten.
> - Verwijderde verouderde `/v0` API-endpoints; werk eventuele integraties of scripts bij om `/v1` of latere endpoints te gebruiken.
> - Ondersteuning voor Python 3.9 is vervallen; u moet Tempo nu draaien op Python 3.10 of later.

## Wat is er veranderd

- Er is een wekelijks samenvattingsrapport toegevoegd dat de geregistreerde tijd per project toont en kan worden geëxporteerd als CSV.
- Eindpunt `/v1/entries/bulk` toegevoegd om tot 200 tijdregistraties in één verzoek aan te maken.
- Uurtarieven kunnen nu per project worden ingesteld en zullen het standaardtarief van de gebruiker overschrijven bij het berekenen van facturatie.
- Urenrapport toegevoegd gegroepeerd per klant
- Optionele wekelijkse e-mailsamenvatting toegevoegd die geregistreerde uren samenvat voor gebruikers die hiervoor kiezen.

## Wat is er verbeterd

- Sneltoetsen toegevoegd voor timerbediening: `Alt+S` om de timer te starten of stoppen en `Alt+X` om van project te wisselen.
- Weekrapporten laden nu aanzienlijk sneller dankzij verbeteringen in database-indexering.
- Verzoeken voor projectlijsten worden nu 60 seconden per workspace gecachet, waardoor laadtijden worden verkort bij het meerdere keren bekijken van projecten.
- Timer detecteert nu wanneer je 10 minuten inactief bent geweest en vraagt je om onbeheerde tijd te verwijderen.

## Wat is er opgelost

- Tijdsdrift verholpen die zorgde voor onnauwkeurige tijdregistratie na ongeveer 6 uur continu draaien.
- Weekrapport totalen bevatten nu correct de tijdregistraties van de laatste dag van het geselecteerde datumbereik.
- Afrondingsfout in BTW-berekening opgelost voor facturen met bedragen boven 1000 euro waarbij belasting per regelitem werd afgerond in plaats van op het totaal
- Het aanmaken van een tijdregistratie zonder een `project_id` geeft nu een 422 foutmelding met een duidelijke boodschap in plaats van een 500 foutmelding.
- Er is een probleem opgelost waarbij timers op de achtergrond bleven doorlopen na het uitloggen.
- Sessiecookies bevatten nu `SameSite` en `Secure` attributen om de beveiliging tegen cross-site aanvallen te verbeteren.
- CSV-import laat niet langer stilzwijgend rijen met lege beschrijvingen vallen; ze worden nu geïmporteerd met `(no description)` als plaatshouder tekst.
- Afrondingsverschillen tussen factuurvoorbeeld en definitieve PDF opgelost die ervoor konden zorgen dat totalen met kleine bedragen verschilden.
- CSV-downloads gebruiken nu de tijdzone van de workspace in plaats van de tijdzone van de browser voor datumopmaak.
- Er is een probleem opgelost waarbij werkruimtes die meerdere regio's omvatten dubbele wekelijkse overzichtsmeldingen ontvingen.
