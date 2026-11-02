# Mercusys Extender för Home Assistant

En custom integration som ger varje Mercusys Wi-Fi-extender en **Starta om**-knapp och status-sensorer i Home Assistant. Knappen kan användas i automationer via åtgärden `button.press`. Integrationen använder enhetens lokala webbgränssnitt och kräver ingen molntjänst.

## Installation

### Via HACS

1. Öppna **HACS → Integrations → ⋮ → Custom repositories** i Home Assistant.
2. Lägg till `https://github.com/jesper1982atea/ha-mercusys` som typen **Integration**.
3. Sök efter **Mercusys Extender** i HACS och välj **Download**. Har du redan kopierat integrationen manuellt kan HACS installera över samma `custom_components/mercusys_extender`-mapp. Starta om Home Assistant efteråt.
4. Dina befintliga enheter och lösenord finns kvar i Home Assistants konfigurationsposter. Du behöver inte lägga till enheterna igen.

När en ny GitHub-release publiceras visar HACS en uppdateringsentitet under **Inställningar → System → Uppdateringar**. Du kan installera den där. Home Assistant behöver startas om efter en koduppdatering.

För automatisk installation kan du skapa en automation med HACS-uppdateringsentiteten för just detta förråd. Kopiera entitetens faktiska ID från Home Assistant och ersätt exemplet nedan. Automationens klockslag väljer en tid när en omstart passar:

```yaml
alias: Uppdatera Mercusys Extender automatiskt
triggers:
  - trigger: time
    at: "03:30:00"
conditions:
  - condition: state
    entity_id: update.mercusys_extender
    state: "on"
actions:
  - action: update.install
    target:
      entity_id: update.mercusys_extender
  - delay: "00:02:00"
  - action: homeassistant.restart
mode: single
```

Använd bara denna automation om du vill att Home Assistant ska startas om automatiskt efter en uppdatering. HACS-uppdateringar kan ta längre tid än två minuter; kontrollera automationens spårning om omstarten kommer för tidigt.

### Manuell installation

1. Kopiera mappen `custom_components/mercusys_extender` till `<Home Assistant config>/custom_components/mercusys_extender`.
2. Starta om Home Assistant.
3. Gå till **Inställningar → Enheter och tjänster → Lägg till integration** och sök efter **Mercusys Extender**.
4. Lägg till din första extenders IP-adress med lösenordet som används i webbgränssnittet. Inget användarnamn behövs.
5. Lägg till integrationen en gång till för din andra extender. Varje enhet får en egen omstartsknapp.

Om webbgränssnittet bara svarar via HTTPS, ange hela adressen, exempelvis `https://192.168.1.10`. Låt **Verifiera HTTPS-certifikat** vara av om enheten har ett självsignerat certifikat.

Om du anger endast IP-adressen provar integrationen HTTP och därefter HTTPS automatiskt. För att tvinga ett visst protokoll skriver du hela adressen med `http://` eller `https://`. Om inloggningen misslyckas, titta efter `Could not validate extender` i Home Assistants logg; raden visar IP, protokoll och feltyp utan att skriva ut lösenordet.

## Automation

Välj respektive enhets **Starta om**-knapp i automationsredigeraren. Exempel:

```yaml
actions:
  - action: button.press
    target:
      entity_id: button.mercusys_192_168_1_10_reboot
```

Det faktiska entitets-ID:t kan skilja sig; kopiera det från Home Assistant. Starta helst om en extender i taget och lägg in några minuters väntan om båda ingår i samma automation.

## Sensorer

Status läses var femte minut. Integrationen visar antal trådlösa klienter totalt, på huvudnätet, på gästnätet och per frekvensband (2,4 GHz, 5 GHz, 6 GHz och MLO), samt trådbundna klienter. Sensorn **Trådlösa klienter** har attributet `clients` med namn, IP-adress, MAC-adress, band och nätverkstyp. När enheten rapporterar länkhastighet finns även `rx_rate_mbps` och `tx_rate_mbps` per klient. På ME25BE hämtas huvud- och gästklienter från separata anrop.

Om firmware lämnar uppgifterna visas även WAN-anslutningens upptid, processor- och minnesanvändning. ME25BE:s processor- och minnesvärden läses från dess `perf`-status. **Senaste omstartskommando** visar när integrationen senast lyckades skicka ett omstartskommando. Tidpunkten sparas och överlever omstart av Home Assistant. Den är inte en bekräftelse på när extendern faktiskt startade om.

**Senaste statusuppdatering** visar när integrationen senast lyckades läsa status. Tidsstämpeln uppdateras vid varje lyckad avläsning och behåller sitt senaste värde om kontakten bryts. I enhetens aktivitetslogg visas tidsstämpelns ändringar samt händelser när kontakten bryts, återkommer och ett omstartskommando skickas. Denna statusuppdateringstid är en tidpunkt i Home Assistant, inte extenderns upptid.

Statusfrågorna loggar in på webbgränssnittet. Vissa enheter tillåter bara en administratörssession åt gången; då kan en pågående Safari-session loggas ut när Home Assistant uppdaterar status.

ME25BE loggas nu ut med samma anrop som dess webbgränssnitt använder. Om en inloggning ändå nekas pausar integrationen automatiska inloggningsförsök för den enheten, så att lösenordsspärren inte nås av femminuterspollningen. Efter att åtkomsten är återställd, ladda om integrationen i **Inställningar → Enheter och tjänster** för att börja läsa status igen. Vill du använda webbgränssnittet under felsökning kan du tillfälligt inaktivera enbart 252-konfigurationen där.

## Stöd och begränsningar

För äldre modeller används [`tplinkrouterc6u`](https://github.com/AlexandrErohin/TP-Link-Archer-C6U). ME25BE med firmware 1.1.0 har ett eget protokollstöd för SHA-256, RSA-OAEP och HMAC. Konfigurationsflödet testar inloggning och status utan att starta om enheten. Om det misslyckas, ange modell och firmwareversion vid felrapportering.

Lösenordet anges i Home Assistants konfigurationsdialog och sparas i Home Assistants config entry. Lägg inte lösenordet i `configuration.yaml` eller i detta projekt.

Om firmware inte stöder statusfrågan blir status-sensorerna otillgängliga, men omstartsknappen finns kvar. Att knappen lyckas bekräftar att kommandot skickades, inte att enheten hunnit starta upp igen. ME25BE:s verifierade status- och systemanrop lämnar ingen enhetsupptid eller starttid. Därför visas ingen påhittad upptid; WAN-anslutningens upptid är ett annat värde.
