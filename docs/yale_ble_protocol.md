# Yale Doorman BLE Protokoll og Discovery

Dette dokumentet oppsummerer funn og arkitektur for direkte kommunikasjon over Bluetooth Low Energy (BLE) mellom Ubuntu/Linux og Yale Doorman Classic utstyrt med Yale Access Module, basert på undersøkelser av `yalexs-ble` (v4.0.5) og BlueZ.

---

## 1. Oversikt og systemgrenser

Yale Doorman Classic kommuniserer trådløst via **Yale Access Module** (samme radiomodul som benyttes i August-økosystemet).

```
+-------------------------------------------------------------+
|                     Ubuntu / Linux Host                     |
|                                                             |
|  +---------------------+        +------------------------+  |
|  | snippen-doorman CLI |  --->  |      yalexs-ble        |  |
|  | (discovery/client)  |        | (PushLock / Bleak /    |  |
|  |                     |        |  cryptography)         |  |
|  +---------------------+        +-----------+------------+  |
|                                             |               |
|                                             v               |
|                                   BlueZ D-Bus System Bus    |
|                                             |               |
+---------------------------------------------|---------------+
                                              v (HCI/BLE)
                                   +---------------------+
                                   |  Yale Access Module |
                                   |          +          |
                                   | Yale Doorman Classic|
                                   +---------------------+
```

---

## 2. Hvordan låsen annonserer seg over BLE

Låsen sender ut BLE-annonser (Advertising Packets) som kan fanges opp uten forhåndstilkobling:

1. **Service UUID**:
   - Primær tjeneste-UUID for August/Yale Doorman er `0000fe24-0000-1000-8000-00805f9b34fb` (`COMMAND_SERVICE_UUID`).
2. **Manufacturer Data**:
   - **Yale Manufacturer ID**: `465` (`0x01D1`).
   - **Apple Manufacturer ID**: `76` (`0x004C`) benyttes dersom modulen annonserer HomeKit/HAP-tilstand (starter med byte `0x06` eller `0x11`).
3. **Local Name og serienummer**:
   - Annonsert lokalt navn (`local_name`) er koblet til låsens serienummer:
     - `serial_to_local_name`: De 2 første og 5 siste tegnene av serienummeret (7 tegn).
     - `local_name_to_serial`: Gjenoppretter serienummeret i format `XXYYYZZZZZ`.

---

## 3. Autentisering og kryptert sesjon

Kommunikasjonen over BLE er kryptert med AES. Det er ikke mulig å lese status eller sende kommandoer uten en gyldig nøkkel.

### Nødvendige credentials:
- **Offline Key**: 128-bit symmetrisk nøkkel representert som en 32-tegns heksadesimal streng (16 bytes).
- **Key Index / Slot**: Hvilket nøkkelspor i modulen som benyttes (standard: `1`).
- **BLE MAC-adresse**: Maskinvareadressen til låsen (f.eks. `AA:BB:CC:DD:EE:FF`).

### Sesjonshåndtrykk:
1. Klienten kobler til via Bleak over BlueZ.
2. `SecureSession` setter offline-nøkkelen og genererer et tilfeldig 16-byte nonce.
3. Klienten sender `SEC_LOCK_TO_MOBILE_KEY_EXCHANGE` (`0x01`) over `SECURE_WRITE_CHARACTERISTIC` (`bd4ac613-0b45-11e3-8ffd-0800200c9a66`).
4. Låsen svarer over `SECURE_READ_CHARACTERISTIC` (`bd4ac614-...`) med sitt nonce.
5. Begge parter avleder en felles 16-byte `session_key`.
6. Klienten sender `SEC_INITIALIZATION_COMMAND` (`0x03`) med andre halvdel av noncet, og låsen bekrefter med svar `0x04`.
7. Videre kommandoer og statusoppdateringer krypteres med den dynamiske sesjonsnøkkelen.

---

## 4. Statusavlesning og låseoperasjoner

`yalexs-ble` tilbyr klassen `PushLock` for operasjoner:

- **Låstilstand (`lock_status`)**: `LOCKED`, `UNLOCKED`, `LOCKING`, `UNLOCKING`, `JAMMED`, `UNKNOWN`.
- **Dørtilstand (`door_status`)**: `CLOSED`, `OPEN`, `UNKNOWN` (basert på DoorSense-magnet).
- **Batterinivå (`battery`)**: Prosentvis kapasitet beregnet fra spenningskurven til 4x AA-batterier.
- **Kommandoer**:
  - `await lock.lock()`: Kaller `Commands.LOCK` (`0x0B`).
  - `await lock.unlock()`: Kaller `Commands.UNLOCK` (`0x0A`).

### Batteri- og tilkoblingshåndtering:
For å unngå å tømme batteriene på Yale Doorman, kobler `PushLock` automatisk fra forbindelsen etter inaktivitet (`idle_disconnect_delay = 5.1s`). Den gjenoppretter automatisk forbindelsen ved neste operasjon via `bleak-retry-connector`.

---

## 5. Feilhåndtering

Biblioteket definerer spesifikke unntak som fanges og logges:
- `AuthError`: Feil offline-nøkkel eller feil key slot.
- `DisconnectedError`: Låsen ble frakoblet eller svarte ikke innen tidsavbrudd.
- `YaleXSBLEError`: Protokoll- eller sjekksumfeil.
- `BleakError` / `BleakDBusError`: Kommunikasjonsproblemer mot BlueZ eller Bluetooth-kontrolleren.

---

## 6. Oppsett for Linux og Dev Container

### Kjøring direkte på Ubuntu-host:
Krever installert `bluez` og en aktiv Bluetooth-adapter:
```bash
sudo apt update && sudo apt install -y bluez
hciconfig hci0 up
```

### Kjøring i Dev Container / Docker:
Dev Containeren krever:
1. `--privileged` og bind-mount av `/dev` for radiotilgang.
2. Bind-mount av D-Bus system socket fra hosten:
   ```json
   "mounts": [
     "source=/var/run/dbus/system_bus_socket,target=/var/run/dbus/system_bus_socket,type=bind"
   ]
   ```

---

## 7. Bruk av CLI

### Søke etter Yale-låser i nærheten:
```bash
snippen-doorman discover --timeout 10
```

### Lese status for en lås:
```bash
snippen-doorman status --address "AA:BB:CC:DD:EE:FF" --key "0123456789abcdef0123456789abcdef" --slot 1
```

### Låse / låse opp:
```bash
snippen-doorman lock   --address "AA:BB:CC:DD:EE:FF" --key "0123456789abcdef0123456789abcdef" --slot 1
snippen-doorman unlock --address "AA:BB:CC:DD:EE:FF" --key "0123456789abcdef0123456789abcdef" --slot 1
```
