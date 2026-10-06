# Uthenting av Yale Offline Keys via Home Assistant

Denne veiledningen beskriver hvordan du henter ut **Offline Key** (128-bit AES heksadesimal nøkkel) og **Key Slot Index** (typisk `1`) for Yale Doorman med Yale Access Module.

Nøklene benyttes av `snippen-doorman-service` for direkte, sikker Bluetooth Low Energy (BLE)-kommunikasjon mot låsen, helt uavhengig av Yale Cloud under daglig drift.

---

## 1. Bakgrunn og prinsipper

1. **Hvorfor trenger vi Offline Key?**
   Kommunikasjonen over BLE mellom styringsenheten (f.eks. Raspberry Pi) og Yale Access Module er kryptert med AES-128. For å opprette en kryptert sesjon krever modulen en forhåndsdelt offline-nøkkel og et nøkkelspor.
2. **Hvorfor via Home Assistant?**
   Yale Home Cloud API krever godkjente OAuth-klienter for autentisering. Home Assistant har en offisiell OAuth-avtale med Yale, og laster automatisk ned låsens krypteringsnøkler fra Yale-skyen når kontoen autentiseres.
3. **Hvorfor egen driftskonto (`post@vestreholmensameie.no`)?**
   For å unngå sammenblanding med private Yale-kontoer, unngå eksponering av private låser, og sikre enkel overdragelse ved fremtidige styre-/driftsendringer i sameiet, benyttes en dedikert driftskonto:
   - **Tjenestekonto:** `post@vestreholmensameie.no`
   - Tilknyttet formål: Snippen Grendehus / Vestre Holmen Sameie

---

## 2. Steg-for-steg oppskrift

```
+------------------------------------+       +------------------------------------+
| 1. Personlig Yale Home-konto       |       | 2. Driftskonto                     |
|    (Nåværende eier av låsen)       |       |    post@vestreholmensameie.no      |
+-----------------+------------------+       +-----------------+------------------+
                  |                                            |
                  |  Inviter som "Eier (Owner)"                |  Godta invitasjon
                  +------------------------------------------->+
                                                               |
                                             Logg inn via Home Assistant
                                                               v
                                             +------------------------------------+
                                             | 3. Midlertidig Home Assistant      |
                                             |    Docker-container                |
                                             |    (Aktiver debug logging)         |
                                             +-----------------+------------------+
                                                               |
                                             Last ned logg og kjør parse_ha_keys.py
                                                               v
                                             +------------------------------------+
                                             | 4. .env konfigurasjon              |
                                             |    SNIPPEN_DOORMAN_BLE_KEY=...     |
                                             +------------------------------------+
```

### Steg 1: Opprett driftskonto for Yale Home
1. Opprett en ny Yale Home-bruker knyttet til e-postadressen:
   - **E-post:** `post@vestreholmensameie.no`
2. Dette kan gjøres i Yale Home-mobilappen (på en sekundær enhet, eller ved å logge ut midlertidig).
3. Fullfør tofaktorsertifisering (2FA via e-post eller SMS).

### Steg 2: Inviter driftskontoen med Eier-tilgang (Owner)
1. Åpne Yale Home-appen på din **personlige konto** (som i dag eier låsen til grendehuset).
2. Velg låsen for Snippen Grendehus.
3. Gå til **Innstillinger** (tannhjulet) -> **Brukere** -> **Inviter ny bruker**.
4. Skriv inn e-postadressen: `post@vestreholmensameie.no`.
5. **KRITISK:** Sett adgangsnivå til **Eier (Owner)**.
   > **Viktig:** Yale/August distribuerer kun `OfflineKeys` til kontoer med *Owner*-rettigheter. Gjester (*Guest*) tildeles ikke offline-kryptonøklene.
6. Åpne invitasjonslenken mottatt på `post@vestreholmensameie.no` (eller logg inn i appen med driftskontoen) og godta invitasjonen.
7. Bekreft at låsen nå er synlig og kontrollerbar under driftskontoen.

### Steg 3: Start midlertidig Home Assistant i Docker
Kjør opp en midlertidig Home Assistant-container på din arbeidsstasjon:

```bash
docker run -d --name ha-key-extractor -p 8123:8123 ghcr.io/home-assistant/home-assistant:stable
```

Vent ca. 15-30 sekunder til webgrensesnittet er klart.

### Steg 4: Koble til Yale Home i Home Assistant
1. Åpne nettleseren og gå til `http://localhost:8123`.
2. Opprett en midlertidig lokal bruker (navn/passord er kun for denne midlertidige containeren).
3. Gå til **Innstillinger** -> **Enheter og tjenester** -> **Legg til integrasjon** (nederst til høyre).
4. Søk etter **Yale** (eller **August**).
5. Autentiser med driftskontoen:
   - **E-post:** `post@vestreholmensameie.no`
   - Angi passord og oppgi 2FA-koden mottatt på SMS eller e-post.
6. Fullfør veiviseren til låsen vises som en integrert enhet i Home Assistant.

### Steg 5: Aktiver feilsøkingslogging og hent ut nøkler
1. Under listen over integrasjoner, finn kortet for **Yale** (eller **August**).
2. Klikk på menyen med tre prikker (`...`) på integrasjonskortet.
3. Velg **Aktiver feilsøkingslogging** (*Enable debug logging*).
4. Klikk på tre prikker (`...`) igjen og velg **Last inn på nytt** (*Reload*).
5. Vent i 10–15 sekunder mens integrasjonen henter ned ferske enhetsdata fra Yale-skyen.
6. Klikk på de tre prikkene en tredje gang og velg **Deaktiver feilsøkingslogging** (*Disable debug logging*).
7. Nettleseren din vil umiddelbart laste ned en loggfil, vanligvis med navn som `home-assistant_yalexs_...log`.

### Steg 6: Ekstraher nøkler med `tools/parse_ha_keys.py`
Bruk det innebygde CLI-verktøyet i dette repositoriet til å parse loggfilen:

```bash
python tools/parse_ha_keys.py --log-file ~/Downloads/home-assistant_*.log --output-env .env
```

Verktøyet vil:
- Finne `OfflineKeys`-blokken for låsen.
- Validere at nøkkelen er en gyldig 128-bit hex-streng (32 tegn) og at slot index er et gyldig heltall.
- Skrive ut eller oppdatere `.env` med:
  ```bash
  SNIPPEN_DOORMAN_BLE_KEY="0123456789abcdef0123456789abcdef"
  SNIPPEN_DOORMAN_BLE_SLOT=1
  SNIPPEN_DOORMAN_BLE_ADDRESS="AA:BB:CC:DD:EE:FF"
  ```

Alternativt kan du åpne loggfilen i en teksteditor og søke manuelt etter `OfflineKeys`:
```json
"OfflineKeys": {
  "loaded": [
    {
      "key": "0123456789abcdef0123456789abcdef",
      "slot": 1
    }
  ]
}
```

### Steg 7: Rydd opp Home Assistant-containeren
Når nøkkelen er lagret i `.env`, stopper og fjerner du den midlertidige containeren:

```bash
docker stop ha-key-extractor && docker rm ha-key-extractor
```

---

## 3. Verifisering mot dørlåsen over BLE

Etter at nøklene er lagret i `.env` (eller oppgis via parametere), verifiserer du kommunikasjonen mot Yale Doorman:

```bash
# Les av status (batteri, dør, låsetilstand)
snippen-doorman status --address "AA:BB:CC:DD:EE:FF" --key "<HEX_KEY>" --slot 1

# Test låseoperasjon
snippen-doorman lock   --address "AA:BB:CC:DD:EE:FF" --key "<HEX_KEY>" --slot 1

# Test opplåsing
snippen-doorman unlock --address "AA:BB:CC:DD:EE:FF" --key "<HEX_KEY>" --slot 1
```

---

## 4. Sikkerhet og hemmeligheter

- **Sikker lagring:** `OfflineKey` gir full kontroll over dørlåsen. Filen `.env` skal **aldri** sjekkes inn i git (den er inkludert i `.gitignore`).
- **Nøkkelens levetid:** Offline-nøkkelen er stabil og endres ikke med mindre låsen/modulen nullstilles (factory reset) eller fjernes og legges til på nytt i Yale Home.
- **Driftskonto:** Passord og 2FA for `post@vestreholmensameie.no` bør lagres i sameiets felles passordhvelv (f.eks. Bitwarden/1Password).
