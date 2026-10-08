# Yale Doorman BLE PIN- og Credential-protokoll

Dette dokumentet beskriver den detaljerte protokollspesifikasjonen for administrasjon av PIN-koder og adgangskoder over Bluetooth Low Energy (BLE) til Yale Doorman Classic utstyrt med Yale Access Module. Spesifikasjonen er basert på statisk analyse og dekompilering av Android-appen Yale Home (`com.assaabloy.yale`, bibliotekene `com.aaecosystem` og `libaugustLockComm.so`).

---

## 1. Oversikt og arkitektur

Når Yale Home-appen administrerer PIN-koder over BLE (uten Wi-Fi-bro), sendes kommandoene direkte til Yale Access-modulen over den etablerte, krypterte AES-sesjonen.

```
+---------------------------------------------------------------+
|                       Host / Klient                           |
|                                                               |
|  1. Etablerer AES-128 sesjon via offline-nøkkel              |
|  2. Bygger 18-byte kommandopakke (0xEE-header + opcode)       |
|  3. Beregner August-sjekksum (modulo 256)                     |
|  4. Krypterer og sender over SECURE_WRITE (bd4ac613-...)      |
+---------------------------------------------------------------+
                               | (BLE AES-CBC sesjon)
                               v
+---------------------------------------------------------------+
|                      Yale Access Module                       |
|                                                               |
|  Validerer sesjon, dekrypterer pakke, verifiserer sjekksum     |
|  og oppdaterer låsens interne minne/slot-register             |
+---------------------------------------------------------------+
```

### Ingen avhengighet til skysignerte tokens
Analysen viser at det **ikke inngår skysignerte tokens eller sertifikater i BLE-payloaden**. All autorisasjon er fullstendig delegert til den lokale AES-128-sesjonen som etableres under tilkoblingshåndtrykket med modulen ved hjelp av låsens `offline_key` og `key_index`.

---

## 2. Generell pakkestruktur (18 bytes)

Alle kommandoer pakkes i faste blokker på 18 bytes (`NUM_BYTES_PER_PACKET = 18`):

| Byte posisjon | Type | Beskrivelse |
|---|---|---|
| `0` | `uint8` | Magic / synkroniseringsheader: Alltid `0xEE`. |
| `1` | `uint8` | **Opcode** (kommando-ID, f.eks. `0x27`, `0x28`, `0x2B`, `0x2C`). |
| `2` | `uint8` | Reservert / null (`0x00`). |
| `3` | `uint8` | **Sjekksum** (toer-komplement / modulo 256 negasjon). |
| `4 .. 15` | `bytes` | Kommandospesifikk payload (PIN, slot, tidsplan, etc.). |
| `16 .. 17` | `uint16_le` | Kanal-/typeindikator: Alltid `0x0002` (`0x02, 0x00`). |

### Algoritme for sjekksum
Sjekksummen beregnes slik at summen av alle 18 bytes i pakken modulo 256 er lik 0:

```python
def calculate_checksum(packet: bytearray) -> int:
    # packet[3] må være 0 under summering
    packet[3] = 0
    total = sum(packet[:18]) & 0xFF
    return (-total) & 0xFF


def build_command_packet(opcode: int, payload: bytes) -> bytes:
    pkt = bytearray(18)
    pkt[0] = 0xEE
    pkt[1] = opcode
    pkt[2] = 0x00
    pkt[3] = 0x00  # Placeholder
    pkt[4 : 4 + len(payload)] = payload
    pkt[16] = 0x02
    pkt[17] = 0x00
    pkt[3] = calculate_checksum(pkt)
    return bytes(pkt)
```

---

## 3. Koding av PIN-kode (Packed BCD)

PIN-koden kodes som **Packed BCD (Binary Coded Decimal / packed nibbles)** i et buffer på 7 bytes (`NUM_BYTES_KEY_CODE = 7`), initialisert og fylt med `0xFF`:

- Første siffer plasseres i **high nibble** av byte 0.
- Andre siffer plasseres i **low nibble** av byte 0.
- Ubenyttede nibbles forblir `0xF`.

### Eksempler:
- 4-sifret PIN `"1234"`:
  `[0x12, 0x34, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]`
- 6-sifret PIN `"123456"`:
  `[0x12, 0x34, 0x56, 0xFF, 0xFF, 0xFF, 0xFF]`
- 5-sifret PIN `"12345"` (oddetalls lengde):
  `[0x12, 0x34, 0x5F, 0xFF, 0xFF, 0xFF, 0xFF]`

```python
def encode_pin(pin_str: str) -> bytes:
    buf = bytearray([0xFF] * 7)
    for i, ch in enumerate(pin_str):
        digit = int(ch) & 0x0F
        byte_idx = i // 2
        if i % 2 == 0:
            buf[byte_idx] = (buf[byte_idx] & 0x0F) | (digit << 4)
        else:
            buf[byte_idx] = (buf[byte_idx] & 0xF0) | digit
    return bytes(buf)
```

---

## 4. Opcodes og kommandoreferanse

| Opcode | Konstant | C-funksjon i `libaugustLockComm.so` | Formål |
|---|---|---|---|
| `0x0A` | `CMD_UNLOCK` | `augLockCmdUnlock` | Låse opp låsen |
| `0x0B` | `CMD_LOCK` | `augLockCmdLock` | Låse låsen |
| `0x27` | `CMD_KEYCODE_SET` | `augLockCmdSetKeypadKey*` | Forhåndsregistrere PIN-verdi |
| `0x28` | `CMD_KEYCODE_CLEAR` | `augLockCmdClearKeypadKey*` | Slette PIN for en gitt slot |
| `0x29` | `CMD_KEYCODE_CLEAR_ALL` | `augLockCmdClearAllKeypadKeys` | Slette alle PIN-koder i låsen |
| `0x2A` | `CMD_KEYCODE_UNLOCK` | `augLockCmdUnlockKey` | Låse opp direkte med PIN over BLE |
| `0x2B` | `CMD_KEYCODE_ACCESS` | `augLockCmdSetKeypadSchedule*` | Sette tidsplan / gyldighet |
| `0x2C` | `CMD_KEYCODE_COMMIT` | `augLockCmdCommitKeypad*` | Binde PIN og tidsplan til slot |
| `0x39` | `CMD_UNITY_UNITY_GET_KEYCODE`| `augLockGetUnityKeycode` | Hente PIN-informasjon for slot |
| `0x42` | `CMD_ENTER_CREDENTIAL_LEARN_MODE` | `augLockEnterCredentialLearnMode` | Læremodus for RFID/kort |
| `0x43` | `CMD_DELETE_CREDENTIAL_COMMAND` | `augLockDeleteCredential` | Generell sletting av credential |

### Credential Types (`credential_type`):
- `0` = PIN (`CREDENTIAL_SCHEDULE_TYPE_PIN`)
- `1` = RFID / Adgangsbrikke (`CREDENTIAL_SCHEDULE_TYPE_RFID`)
- `2` = Fingeravtrykk (`CREDENTIAL_SCHEDULE_TYPE_FINGERPRINT`)
- `4` = Ansiktsgjenkjenning (`CREDENTIAL_SCHEDULE_TYPE_FACE`)

For Yale Doorman benyttes typisk `0` for PIN-koder.

---

## 5. Protokollsekvens: Opprette eller endre PIN-kode

I Yale Home-appen og produksjonsflyten utføres opprettelse eller oppdatering av en PIN som en **4-stegs sekvens** (inkludert pre-clear for å sikre at sporet i mikrokontrolleren er rent):

```
Klient (Linux / Mobil)                                Yale Access Modul
       |                                                      |
       |  0. KeyCode_Clear (0x28) [Pre-clear slot & PIN]      |
       |----------------------------------------------------->|
       |  Svar: ACK med 0xAA / 0xBB (Slot klargjort)          |
       |<-----------------------------------------------------|
       |                                                      |
       |  1. KeyCode_Set (0x27) [PIN bytes]                   |
       |----------------------------------------------------->|
       |  Svar: ACK med 0xBB (Bekreftet "keyCode")            |
       |<-----------------------------------------------------|
       |                                                      |
       |  2. KeyCode_Access (0x2B) [Tidsplan / Schedule]      |
       |----------------------------------------------------->|
       |  Svar: ACK med 0xBB (Bekreftet schedule)             |
       |<-----------------------------------------------------|
       |                                                      |
       |  3. KeyCode_Commit (0x2C) [PIN, Slot, Type]          |
       |----------------------------------------------------->|
       |  Svar: ACK med 0xBB (PIN skrevet til maskinvare)     |
       |<-----------------------------------------------------|
```

### Steg 0: `KeyCode_Clear` (`0x28`) - Pre-clear
For å unngå konflikter i mikrokontrollerens minne dersom sporet allerede er opptatt, sender klienten først en `KeyCode_Clear`-pakke for sporet. Eventuelle feil her ignoreres hvis sporet allerede var tomt.

### Steg 1: `KeyCode_Set` (`0x27`)
Forbereder modulen på den nye PIN-koden:

- **Pakkestruktur (18 bytes)**:
  - Byte `0`: `0xEE`
  - Byte `1`: `0x27`
  - Byte `2`: `0x00`
  - Byte `3`: Sjekksum
  - Byte `4..10`: 7 bytes BCD-kodet PIN
  - Byte `12`: `credential_type` (`0x00` for PIN)
  - Byte `16..17`: `0x02, 0x00`
- **Validering av svar**:
  Modulen returnerer respons med header `0xBB` (`bb27...`) der payloaden matcher innsendt PIN.

### Steg 2: `KeyCode_Access` (`0x2B`)
Definerer når PIN-koden skal være aktiv:

- **Pakkestruktur (18 bytes)**:
  - Byte `0`: `0xEE`
  - Byte `1`: `0x2B`
  - Byte `2`: `0x00`
  - Byte `3`: Sjekksum
  - Byte `4..7`: `start_time` (`uint32` little-endian, se tabell)
  - Byte `8..11`: `end_time` (`uint32` little-endian, se tabell)
  - Byte `12`: `slot` (eller `access_type`)
  - Byte `13`: `credential_type` (`0x00`)
  - Byte `16..17`: `0x02, 0x00`

- **Tidsplan-moduser**:
  - **Alltid aktiv (`ScheduleType.ALWAYS`)**:
    - `access_type = 0x80`
    - `start_time = 0`, `end_time = 0`
  - **Engangskode / midlertidig vindu (`ScheduleType.TEMPORARY`)**:
    - `access_type = 0x81` eller `0x82`
    - `start_time` / `end_time` = UTC Unix epoch-tidsstempel i sekunder
  - **Gjentakende ukentlig (`ScheduleType.RECURRING`)**:
    - `access_type` = Bitmask av dager: `1 << day_of_week` (Mandag = bit 1, Tirsdag = bit 2, osv.)
    - `start_time` / `end_time` = Sekund i døgnet (`0` til `86399`)

### Steg 3: `KeyCode_Commit` (`0x2C`)
Knytter PIN og tidsplan til det spesifikke sporet (`slot`):

- **Pakkestruktur (18 bytes)**:
  - Byte `0`: `0xEE`
  - Byte `1`: `0x2C`
  - Byte `2`: `0x00`
  - Byte `3`: Sjekksum
  - Byte `4..10`: 7 bytes BCD-kodet PIN
  - Byte `11`: `slot & 0xFF` (lav byte av slot-indeks)
  - Byte `12`: `credential_type` (`0x00`)
  - Byte `13`: `(slot >> 8) & 0xFF` (høy byte av slot-indeks)
  - Byte `16..17`: `0x02, 0x00`
- **Validering av svar**:
  Modulen returnerer `{"error": "COMM_SUCCESS"}`.

---

## 6. Protokollsekvens: Slette PIN-kode

### Slette enkeltkode (`0x28` - `KeyCode_Clear`)
Kalles via `sendClearKeyCode(pin, slot, credential_type)`:

- **Pakkestruktur (18 bytes)**:
  - Byte `0`: `0xEE`
  - Byte `1`: `0x28`
  - Byte `2`: `0x00`
  - Byte `3`: Sjekksum
  - Byte `4..10`: 7 bytes BCD-kodet PIN
  - Byte `11`: `slot & 0xFF`
  - Byte `12`: `credential_type` (`0x00`)
  - Byte `13`: `(slot >> 8) & 0xFF`
  - Byte `16..17`: `0x02, 0x00`
- **Svar**: `{"error": "COMM_SUCCESS"}`.

### Slette alle PIN-koder (`0x29` - `KeyCode_ClearAll`)
Kalles via `sendClearAllKeyCodes()`:

- **Pakkestruktur (18 bytes)**:
  - Byte `0`: `0xEE`
  - Byte `1`: `0x29`
  - Byte `2`: `0x00`
  - Byte `3`: Sjekksum
  - Byte `4..15`: `0x00` (ubenyttet)
  - Byte `16..17`: `0x02, 0x00`

---

## 7. Svarmeldinger og feilkoder fra låsen

### Svarsynkronisering og headere:
- `0xBB` / `0xAA`: Gyldig bekreftelse fra modulen (`bb27` for SET, `bb2b` for ACCESS, `bb2c` for COMMIT, `aa28`/`bb28` for CLEAR).
- `0xCC`: Feilrespons eller ekko dersom pakken ble avvist eller sjekksummen i byte 3 var korrupt.

### Viktig sjekksum-felle i klientimplementasjoner:
`Session._write_checksum(command)` i `yalexs_ble` beregner `(-sum(command[:18])) & 0xFF` uten først å nullstille `command[0x03]`. Dersom en kommandopakke sendes inn der sjekksummen allerede er ferdig beregnet (slik at totalsummen modulo 256 er 0), vil `_write_checksum` beregne `0x00` og overskrive byte 3 med null. Modulen mottar da en pakke med korrupt sjekksum, kvitterer med `0xCC`, og forkaster koden uten å lagre den i flash-minnet.
Løsning: Klienten må patche eller sikre at `command[0x03] = 0` før sjekksummen summeres.

### Feilkoder fra modulen:
Dersom en operasjon feiler i modulen, returneres en statuskode:

| Feilkonstant | Beskrivelse |
|---|---|
| `COMM_SUCCESS` | Operasjonen var vellykket |
| `KEYCODE_SLOT_IN_USE` | Sporet (slot) er allerede opptatt av en annen kode |
| `KEYCODE_EXISTING_KEY` | PIN-koden eksisterer allerede i et annet spor |
| `KEYCODE_NOSPACE` | Minnet i låsen er fullt |
| `KEYCODE_INVALID_ACCESS` | Ugyldig tidsplan eller gyldighetsperiode |
| `KEYCODE_DISABLE` | Tastaturfunksjon er deaktivert |
| `KEYCODE_TIMEOUT` | Tidsavbrudd under operasjon |

---

## 8. Verifisering og dekryptering via Bluetooth HCI Snoop

For å ettergå protokollen mot reelle data fra Yale Home-appen benyttes verktøyet `tools/decrypt_ble_snoop.py`:

```
+---------------------+      AES-128-ECB (offline_key)      +---------------------+
| Klient Nonce 1 (8B) | --------------------------------->  |  Yale Access Modul  |
+---------------------+                                     +---------------------+
                                                            |  Lås Nonce 1 (8B)   |
+---------------------+      AES-128-ECB (offline_key)      +---------------------+
|     Host Mottar     | <---------------------------------- |
+---------------------+
           |
           v
+---------------------------------------------------------------------------------+
| Session Key (16 bytes) = Client Nonce 1 (8 bytes) + Lock Nonce 1 (8 bytes)      |
+---------------------------------------------------------------------------------+
           |
           v
+---------------------------------------------------------------------------------+
| Dekryptering av etterfølgende GATT-kommandoer:                                  |
| AES-128-CBC med IV = 16 null-bytes (bytes(16)) over de første 16 bytes         |
+---------------------------------------------------------------------------------+
```

### Kjøring av dekrypteringsverktøyet
```bash
# Automatisk uthenting fra tilkoblet telefon via ADB og dekryptering:
python tools/fetch_btsnoop.py

# Eller direkte dekryptering av en btsnoop_hci.log / PCAP / bugreport.zip:
python tools/decrypt_ble_snoop.py data/btsnoop_hci.log -k 438b544da1ffd82510a973d5ff9853bb
```
