# Produksjonsoppsett for Raspberry Pi Gateway

Denne veiledningen beskriver hvordan **Snippen Doorman Service** installeres, konfigureres og driftes på en dedikert Raspberry Pi i grendehuset på Snippen.

---

## 1. Maskinvare og operativsystem

- **Enhet**: Raspberry Pi 3B+, 4B, Zero 2W eller 5 med integrert Bluetooth LE.
- **Anbefalt OS**: **Raspberry Pi OS Lite (64-bit)** (Debian 12 Bookworm).
- **Plassering**: Montert innendørs med fri sikt eller kort avstand (maks 10–15 meter) til Yale Doorman-dørlåsene (f.eks. ytterdør og fellesrom med ca. 5 meters innbyrdes avstand).

---

## 2. Rask installasjon med `install_pi.sh`

Klon kodelageret eller overfør den bygde distribusjonspakken (`dist/snippen_doorman_service-*.whl`) til Raspberry Pi, og kjør installasjonsskriptet som root:

```bash
# 1. Klon repoet (eller pakk ut en release-tarball)
git clone https://github.com/jonasfh/snippen-doorman-service.git
cd snippen-doorman-service

# 2. Bygg release-pakken lokalt (eller bruk en ferdigbygd wheel)
python3 scripts/build_release.py

# 3. Kjør installasjonsskriptet som root
sudo bash scripts/install_pi.sh
```

### Hva skriptet utfører automatisk:
1. Installerer påkrevde systempakker (`python3-venv`, `python3-pip`, `bluez`, `rfkill`, `libglib2.0-dev`, `systemd-timesyncd`, `fake-hwclock`).
2. Oppretter en dedikert, uprivilegert systembruker og gruppe `doorman`.
3. Tildeler systembrukeren gruppetilhørighet i `bluetooth` og `netdev`.
4. Oppretter installasjonskatalog `/opt/snippen-doorman-service` med et isolert Python-virtualenv (`.venv`).
5. Installerer `snippen-doorman-service` i det virtuelle miljøet.
6. Installerer D-Bus-policyen `/etc/dbus-1/system.d/snippen-doorman.conf` for direkte BlueZ-kommunikasjon uten root-rettigheter.
7. Konfigurerer kontinuerlig NTP-tidssynkronisering (`systemd-timesyncd`) mot norsk tidsserver-pool (`no.pool.ntp.org`).
8. Installerer og aktiverer systemd-tjenesten `/etc/systemd/system/snippen-doorman.service` (med avhengighet til `time-sync.target`).
9. Oppretter miljøfilen `/etc/snippen-doorman/snippen-doorman.env` med sikre filrettigheter (`0640`, eies av `root:doorman`).

---

## 3. Konfigurasjon (`/etc/snippen-doorman/snippen-doorman.env`)

Rediger miljøvariablene med en teksteditor som root:

```bash
sudo nano /etc/snippen-doorman/snippen-doorman.env
```

Eksempel på produksjonskonfigurasjon for to dører:

```bash
# REST API mot WordPress Snippen Booking
SNIPPEN_DOORMAN_API_URL="https://vestreholmensameie.no/wp-json/snippen/v1/door"
SNIPPEN_DOORMAN_API_TOKEN="hemmelig-bearer-token-fra-wp-admin"

# Konfigurasjon for begge dørene på Snippen (1 offline key per dør)
DOORMAN_LOCKS="ytterdor=AA:BB:CC:DD:EE:01:0123456789abcdef0123456789abcdef:1,fellesrom=AA:BB:CC:DD:EE:02:fedcba9876543210fedcba9876543210:1"

# Tidsstyring (sekunder / minutter)
SNIPPEN_DOORMAN_SYNC_INTERVAL=60.0
SNIPPEN_DOORMAN_OFFLINE_RETRY_INTERVAL=10.0
SNIPPEN_LEAD_TIME_MINUTES=60
SNIPPEN_GRACE_PERIOD_MINUTES=15

# Yale Doorman gjestespor (standard 3 til 9)
SNIPPEN_GUEST_SLOT_MIN=3
SNIPPEN_GUEST_SLOT_MAX=9

# Web Dashboard og HTTPS (TLS)
SNIPPEN_DOORMAN_WEB_HOST=0.0.0.0
SNIPPEN_DOORMAN_WEB_PORT=8080
SNIPPEN_DOORMAN_WEB_TLS=true
```

> **Sikkerhet:** Filen inneholder kryptonøkler og API-token. Kontroller at rettighetene alltid er begrenset:
> ```bash
> sudo chmod 640 /etc/snippen-doorman/snippen-doorman.env
> sudo chown root:doorman /etc/snippen-doorman/snippen-doorman.env
> ```

---

## 4. Web Dashboard og Web-Config PWA

Tjenesten kjører et innebygd administrasjonsgrensesnitt på port **8080** over HTTPS:

- **Admin Dashboard:** `https://snippen-doorman-service.local:8080` (eller `https://<pi-ip>:8080`)
- **WiFi Provisioning PWA (Web Bluetooth):** `https://snippen-doorman-service.local:8080/web-config`

### Første gangs tilkobling og selvsignert sertifikat
Siden TLS-sertifikatet opprettes automatisk på enheten (`/opt/snippen-doorman-service/data/tls/cert.pem`), vil nettleseren gi en advarsel (*"Tilkoblingen er ikke privat"*):
1. Klikk **Avansert** (*Advanced*).
2. Velg **Fortsett til snippen-doorman-service.local (usikkert)**.

---

## 5. Drift med systemd

### Starte og stoppe tjenesten
```bash
# Start tjenesten
sudo systemctl start snippen-doorman

# Sjekk status
sudo systemctl status snippen-doorman

# Stopp tjenesten
sudo systemctl stop snippen-doorman

# Start på nytt
sudo systemctl restart snippen-doorman
```

### Se sanntidslogger
```bash
journalctl -u snippen-doorman -f
```

---

## 6. Tidssynkronisering og NTP (Systemklokke & Dørlåser)

Raspberry Pi mangler integrert batteridrevet maskinvareklokke (RTC). For at tidsbegrensede PIN-koder skal være nøyaktige og låsenes interne klokke alltid synkron, styres tiden i to ledd:

### 6.1 Systemtid på Raspberry Pi (`systemd-timesyncd`)
Installasjonsskriptet setter opp `systemd-timesyncd` mot den norske NTP-poolen (`no.pool.ntp.org`) og aktiverer `fake-hwclock` (forhindrer tidsreversering ved reboot uten internett).

```bash
# Sjekk NTP-synkroniseringsstatus og nøyaktighet
timedatectl timesync-status

# Sjekk generell klokkestatus (System clock synchronized: yes)
timedatectl status
```

Systemd-tjenesten `snippen-doorman.service` har `After=time-sync.target`, som forhindrer at doorman-tjenesten starter før systemklokken er verifisert over NTP.

### 6.2 Låsenes interne klokke (BLE RTC Heartbeat)
- **Ved ny booking:** Klokken i Yale Doorman stilles automatisk over BLE hver gang en ny PIN-kode programmeres inn.
- **Daglig Heartbeat:** I perioder uten nye bookinger vil `DoormanSyncEngine` kontakte låsene én gang i døgnet (`SNIPPEN_DOORMAN_HEARTBEAT_INTERVAL_HOURS=24.0`) for å synkronisere låsens interne RTC-klokke og oppdatere batteritelemetri.

---

## 7. Bluetooth Recovery og feilsøking (#7)

Dersom Bluetooth-adapteren opplever heng, interferens, feilmeldingen `No powered Bluetooth adapters found. Turn on Bluetooth and try again.`, eller soft-block på en fersk installasjon:

### Manuell aktivering og rettigheter for bruker:
Når du logger inn som en vanlig bruker (f.eks. `jonas`) og skal teste eller kjøre verktøy direkte:

```bash
# 1. Fjern rfkill-blokkeringen på Bluetooth
sudo rfkill unblock bluetooth

# 2. Legg brukeren din til i bluetooth-gruppen (hvis den ikke allerede er det)
sudo usermod -aG bluetooth $USER

# 3. Start Bluetooth-tjenesten på nytt
sudo systemctl restart bluetooth

# 4. Slå på radioen i BlueZ
bluetoothctl power on
```
*(Husk å logge ut og inn igjen eller kjøre `newgrp bluetooth` dersom gruppetilhørigheten ble endret i aktiv sesjon).*

### Ytterligere feilsøking og recovery:

1. **Automatisk gjenoppretting**:
   - Systemd-enheten har `ExecStartPre=-/usr/sbin/rfkill unblock bluetooth` og starter automatisk på nytt ved feil (`Restart=on-failure`, `RestartSec=10s`).
2. **Sjekk at Bluetooth ikke er blokkert**:
   ```bash
   rfkill list bluetooth
   sudo rfkill unblock bluetooth
   ```
3. **Omstart av Bluetooth-undersystemet (BlueZ)**:
   ```bash
   sudo systemctl restart bluetooth
   sudo systemctl restart snippen-doorman
   ```
4. **Inspiser Bluetooth-adapterens tilstand**:
   ```bash
   bluetoothctl show
   ```
5. **D-Bus tilgangsfeil**:
   - Hvis loggen viser `PermissionDenied` mot `org.bluez`, sjekk at `/etc/dbus-1/system.d/snippen-doorman.conf` eksisterer og kjør `sudo systemctl reload dbus`.

---

## 8. Drift uten fast internett («Walk-by Sync» med delt mobilnett)

Når Raspberry Pi står plassert i Snippen grendehus uten fast bredbånd, synkroniseres bookingdata ved at noen går forbi med delt nett (personal hotspot) på mobiltelefonen.

### 8.1 Hvordan umiddelbar synkronisering fungerer
1. **NetworkManager Dispatcher (`SIGUSR1`):** I det millisekundet Pi-en kobler seg til telefonens Wi-Fi og tildeles en lokal IP-adresse, kjører NetworkManager skriptet `/etc/NetworkManager/dispatcher.d/99-snippen-sync`. Dette sender signalsending `SIGUSR1` direkte til `snippen-doorman`-prosessen.
2. **Øyeblikkelig oppvåkning:** Doorman-tjenesten avbryter dvalen på mikrosekundet og kjører en full synkroniseringssyklus (`sync_once`) mot WordPress Booking API umiddelbart.
3. **Adaptiv offline-loop:** Dersom nettet var nede, venter ikke tjenesten i f.eks. 15 minutter, men sjekker på nytt med et kort offline-intervall (`SNIPPEN_DOORMAN_OFFLINE_RETRY_INTERVAL=10.0`). Dette fungerer som en robust sikring dersom telefonens 4G/5G-modem brukte et par sekunder på å åpne internettruting.
4. **Aktiv Wi-Fi-reskanning:** Når tjenesten er offline, trigges en aktiv Wi-Fi-skanning med jevne mellomrom for å oppdage kjente hotspots raskt (slik at Pi-en ikke sover forbi mobilen).

### 8.2 Konfigurere flere kjente Wi-Fi-nettverk (flere telefoner)
Linux NetworkManager støtter lagring av så mange kjente Wi-Fi-nettverk som ønskelig. Både din telefon og f.eks. Lises telefon kan legges til, slik at Pi automatisk kobler seg til den som er tilgjengelig:

```bash
# Legg til telefon 1
sudo nmcli device wifi connect "Jonas iPhone" password "hemmelig_passord_1"

# Legg til telefon 2
sudo nmcli device wifi connect "Lises iPhone" password "hemmelig_passord_2"

# Sjekk lagrede profiler (begge skal ha AUTOCONNECT=yes)
nmcli connection show
```

Du kan også koble til nye nettverk via Web Dashboard / Web-Config PWA på `https://<pi-ip>:8080/web-config`.

### 8.3 Beste praksis for telefonens hotspot
- **iPhone:** Gå til *Innstillinger* -> *Delt internett* og slå på **Maksimal kompatibilitet** (dette tvinger 2.4 GHz som har best rekkevidde og støttes av alle Raspberry Pi-modeller).
- **Skjerm på ved passering:** Hold gjerne skjermen på telefonen åpen på siden for *Delt internett* i 5–10 sekunder idet du nærmer deg grendehuset. Smarttelefoner sparer batteri ved å skru ned beacon-utsending hvis skjermen er låst og ingen enheter er tilkoblet.
- **Manuell trigger via terminal (valgfritt):**
  Dersom du er koblet til Pi-en over SSH eller vil teste signalet manuelt:
  ```bash
  sudo systemctl kill -s SIGUSR1 snippen-doorman
  # eller:
  pkill -USR1 -f "snippen-doorman service run"
  ```
