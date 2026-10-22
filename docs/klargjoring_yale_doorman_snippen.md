# Klargjøring og oppgradering av Yale Doorman (Snippen Grendehus)

Dette dokumentet beskriver den praktiske fremgangsmåten for å oppgradere dør 1 på Snippen til **Yale Access Module**, registrere låsen på sameiets felles driftskonto (`post@vestreholmensameie.no`), og håndtere adgangskoder manuelt via **Yale Home-appen** i overgangsfasen inntil fast nettverk og automatisert synkronisering er etablert.

---

## 1. Nødvendig utstyr

Før du reiser opp til Snippen, kontroller at du har med:
- [ ] **Yale Access Module** (hvit og gul modulbrikke med QR-kode).
- [ ] **4 stk. nye 1.5V AA alkaliske batterier** (bytt gjerne ut de gamle mens dekselet først er åpent).
- [ ] **Liten stjernetrekker** (PH1 / PH2) for skruen i batteridekselet (og eventuelt innvendig langskilt).
- [ ] **Smarttelefon** med Bluetooth aktivert og installert **Yale Home**-app.
- [ ] Tilgang til e-posten `post@vestreholmensameie.no` (for å bekrefte invitasjon og 2FA).

---

## 2. Plassering av batterier og radiomodul

På Yale Doorman Classic (V2N) sitter all elektronikk, strømforsyning og radiomodul på **innsiden** av døren:

```
+------------------------------------------+
|          INNVENDIG DØRSKILT              |
|                                          |
|  +------------------------------------+  |
|  | [ Liten festeskrue / låsetapp ]    |  | <-- Øverst på batteridekselet
|  |                                    |  |
|  |  +------------------------------+  |  |
|  |  |       RADIOMODUL-SPOR        |  |  | <-- Her sitter modulen (Verisure / Yale)
|  |  +------------------------------+  |  |     (Trekkes rett opp/ut)
|  |                                    |  |
|  |  +-------+ +-------+ +-------+ +-+ |  |
|  |  | AA #1 | | AA #2 | | AA #3 | | | |  | <-- 4 x AA 1.5V batterier
|  |  +-------+ +-------+ +-------+ +-+ |  |
|  |                                    |  |
|  |   [ E / A ] Bryter (Easy/Adv)      |  | <-- Skyvebryter ved siden av batteriene
|  +------------------------------------+  |
|                                          |
|                [ VRIDER ]                |
|                                          |
|               [ KNAPP / R ]              |
+------------------------------------------+
```

### Hvor tar du ut batteriene?
1. Øverst på det innvendige langskiltet (over dørvrideren) sitter et plastdeksel.
2. Løsne den lille skruen i toppen av dekselet (eller trykk inn låsetappen).
3. Løft eller skyv dekselet av.
4. Du ser nå **4 stk. AA-batterier** og et rektangulært spor rett over batteriene der den nåværende modulen (f.eks. Verisure) er plugget inn.
5. Ta ut ett eller to batterier for å gjøre låsen helt strømløs før modulen byttes.

---

## 3. Trinnvis fremgangsmåte på døren

> [!CAUTION]
> **Kritisk forholdsregel:** Ha døren **åpen** under hele operasjonen inntil du har testet og bekreftet at den nye koden fungerer utenfra.

### Steg 1: Bryt strømmen og fjern gammel modul
1. Åpne døren.
2. Ta av batteridekselet på innsiden og ta ut ett batteri.
3. Trekk den eksisterende Verisure-modulen rett opp/ut av sporet over batteriene. Legg den til side.

### Steg 2: Nullstilling / Modus (Easy vs. Advanced)
For å bruke Yale Access Module med Yale Home-appen må låsen være satt i **Avansert modus (Advanced)**:
1. Kontroller den lille skyvebryteren ved siden av batteriene merket **E / A** (eller *Easy / Advanced*).
2. Sett bryteren i posisjon **A (Advanced)**.
3. *Merk:* Hvis låsen tidligere har hatt en ukjent masterkode, nullstilles låsen ved å ta ut batteriene, skru ut de to festeskruene til innvendig skilt, vippe bryteren på kretskortet fra `Easy` til `Advanced`, og sette inn batteriene igjen mens døren er åpen. Hvis låsen allerede fungerer med kjent masterkode, trenger du ikke å demontere selve skiltet.

### Steg 3: Sett inn ny Yale Access Module
1. Sørg for at strømmen er brutt (ett batteri er ute).
2. Skyv den nye **Yale Access Module** godt ned i modulkontakten.
3. Sett inn alle batteriene (gjerne 4 splitter nye AA-batterier).
4. Låsen vil avgi en oppstartslyd/melodi som bekrefter at modulen har fått strøm.

---

## 4. Oppsett i Yale Home-appen & Driftskonto

For at både du personlig og sameiets felles driftsbruker skal ha tilgang:

### 1. Registrer låsen i Yale Home
1. Åpne **Yale Home-appen** på telefonen din (med Bluetooth på).
2. Trykk på menyen og velg **Konfigurer en enhet** (*Set up a device*).
3. Skann QR-koden på Yale Access-modulen (eller på emballasjen).
4. Følg appens veiviser:
   - Appen kobler seg til modulen via Bluetooth.
   - Du blir bedt om å oppgi eller bekrefte låsens masterkode på utvendig tastatur for å verifisere eierskap.
   - Gi låsen et gjenkjennelig navn (f.eks. `Snippen Hoveddør`).

### 2. Inviter driftskontoen (`post@vestreholmensameie.no`)
1. Gå inn på låsens innstillinger (tannhjulet) i Yale Home-appen.
2. Velg **Brukere** -> **Inviter ny bruker**.
3. Skriv inn: `post@vestreholmensameie.no`.
4. **Kritisk valg:** Velg adgangsnivå **Eier (Owner)** (ikke *Gjest*).
   > [!IMPORTANT]
   > Eier-rettighet er påkrevd for at driftskontoen skal ha fulle administrative rettigheter og for at vi senere kan hente ut offline-nøkler til en eventuell Raspberry Pi-gateway.
5. Åpne invitasjonslenken mottatt på `post@vestreholmensameie.no` og aksepter invitasjonen.

---

## 5. Daglig drift i overgangsfasen (Manuell styring via app)

I denne overgangsfasen styres koder direkte fra mobilen over Bluetooth når du er i nærheten av døren:

### Opprette en adgangskode for en leietaker:
1. Still deg i nærheten av døren med telefonen (Bluetooth-rekkevidde, innen 2–5 meter).
2. Åpne **Yale Home-appen** og velg `Snippen Hoveddør`.
3. Gå til **Gjesteliste** / **Adgangskoder**.
4. Trykk **Legg til kode**:
   - Angi leietakerens navn (f.eks. `Reservasjon 142 - Ola Nordmann`).
   - Angi PIN-kode (normalt 6 siffer).
   - Velg tidsrom / tidsbegrenset adgang (angi fra- og til-tidspunkt for bookingen).
5. Appen programmerer koden rett inn i låsens minne over Bluetooth.

### Sletting / utløp av koder:
- Hvis koden ble lagt inn med tidsstyring i Yale Home, slutter koden automatisk å fungere etter utløpstidspunktet.
- Du kan når som helst slette eller endre koder i appen når du er innen Bluetooth-rekkevidde.

---

---

## 6. Hente ut Offline Key (Klargjøring for Raspberry Pi fra start)

Så snart låsen er registrert og `post@vestreholmensameie.no` er satt som **Eier (Owner)** i Yale Home-appen, genererer Yale-skyen de permanente 128-bit AES-krypteringsnøklene for låsen. Ved å hente ut disse nøklene med en gang, har du alt klart i `.env` for `snippen-doorman-service`.

Dette steget gjøres på en datamaskin med Docker (hjemme eller på laptop):

```
+------------------------------------+
| 1. Yale Home Cloud                 |
|    post@vestreholmensameie.no      |
+-----------------+------------------+
                  |
                  |  Logg inn og autentiser via OAuth
                  v
+------------------------------------+
| 2. Midlertidig Home Assistant      |
|    Docker-container (port 8123)    |
|    Aktiver feilsøkingslogging      |
+-----------------+------------------+
                  |
                  |  Last ned home-assistant_*.log
                  v
+------------------------------------+
| 3. Kjør parse_ha_keys.py           |
|    Genererer ferdig .env           |
+-----------------+------------------+
                  |
                  |  SNIPPEN_DOORMAN_BLE_KEY=...
                  v
+------------------------------------+
| 4. Klar for Raspberry Pi           |
|    Lokal BLE-styring uten sky      |
+------------------------------------+
```

### Steg 1: Start en midlertidig Home Assistant-container
Kjør følgende kommando i terminalen på datamaskinen din:

```bash
docker run -d --name ha-key-extractor -p 8123:8123 ghcr.io/home-assistant/home-assistant:2026.9.4
```
Vent 15–20 sekunder til containeren er ferdig initialisert.

### Steg 2: Koble til Yale i Home Assistant
1. Åpne nettleseren på `http://localhost:8123`.
2. Fyll inn et vilkårlig navn og passord for å opprette en midlertidig lokal administratorkonto i Home Assistant.
3. Gå til **Innstillinger** (Settings) -> **Enheter og tjenester** (Devices & Services) -> **Legg til integrasjon** (Add Integration).
4. Søk opp **Yale** (eller **August**).
5. Logg inn med sameiets driftskonto:
   - **E-post:** `post@vestreholmensameie.no`
   - Oppgi passord og tast inn 2FA-koden mottatt på e-post eller SMS.
6. Fullfør veiviseren til du ser at låsen dukker opp som en enhet i Home Assistant.

### Steg 3: Last ned feilsøkingslogg med nøkler
1. Finn integrasjonskortet for **Yale** / **August**.
2. Klikk på de tre prikkene (`...`) på kortet og velg **Aktiver feilsøkingslogging** (*Enable debug logging*).
3. Klikk på de tre prikkene (`...`) en gang til og velg **Last inn på nytt** (*Reload*).
4. Vent ca. 15 sekunder mens integrasjonen henter ned ferske enhetsdata og krypteringsnøkler fra Yale-skyen.
5. Klikk på de tre prikkene (`...`) en tredje gang og velg **Deaktiver feilsøkingslogging** (*Disable debug logging*).
6. Nettleseren din vil nå automatisk laste ned en loggfil (typisk kalt `home-assistant_yalexs_...log` eller lignende).

### Steg 4: Trekk ut nøklene automatisk med scriptet
Fra rotmappen i dette repositoriet, kjør det innebygde uttrekksverktøyet mot loggfilen du lastet ned:

```bash
python tools/parse_ha_keys.py --log-file ~/Downloads/home-assistant_*.log --output-env .env
```

Verktøyet vil:
- Identifisere låsens BLE MAC-adresse (f.eks. `AA:BB:CC:DD:EE:FF`).
- Hente ut den 128-bit heksadesimale offline-nøkkelen.
- Verifisere Key Slot Index (normalt `1`).
- Opprette eller oppdatere `.env` med verdiene ferdig konfigurert:
  ```dotenv
  SNIPPEN_DOORMAN_BLE_ADDRESS="AA:BB:CC:DD:EE:FF"
  SNIPPEN_DOORMAN_BLE_KEY="0123456789abcdef0123456789abcdef"
  SNIPPEN_DOORMAN_BLE_SLOT=1
  ```

### Steg 5: Rydd opp Home Assistant-containeren
Når nøklene er trygt lagret i `.env`, sletter du den midlertidige containeren:

```bash
docker stop ha-key-extractor && docker rm ha-key-extractor
```

### Steg 6: Verifiser direkte BLE-kommunikasjon (valgfritt)
Dersom du har en laptop eller Raspberry Pi med Bluetooth i nærheten av døren, kan du bekrefte at nøkkelen fungerer direkte mot låsen over BLE:

```bash
# Les ut status, dør-tilstand og batterinivå direkte over BLE
snippen-doorman status
```

---

## 7. Neste steg (Når permanent nettverk og Raspberry Pi skal i drift)

Når dere på et senere tidspunkt etablerer Wi-Fi på Snippen eller monterer en 4G-dongle på Raspberry Pi-en:
1. Yale Access Module, eierskap i Yale Home, og offline-nøklene i `.env` er **allerede ferdig klargjort**.
2. Raspberry Pi-en settes opp med `snippen-doorman-service` i henhold til [docs/raspberry_pi_setup.md](raspberry_pi_setup.md).
3. Tjenesten startes og tar umiddelbart over den automatiske JIT-synkroniseringen av koder fra booking-systemet.
