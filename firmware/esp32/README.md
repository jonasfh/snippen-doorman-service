# ESP32 BLE Bridge for Snippen Doorman

Dette området inneholder arkitektur, referansemodeller og spesifikasjon for en mikrokontroller-basert Doorman-klient (f.eks. ESP32-WROOM-32, ESP32-C3 eller ESP32-S3) som kan erstatte eller supplere Raspberry Pi for uavhengige utleieenheter (se [docs/multi_node_architecture.md](../../docs/multi_node_architecture.md)).

## Formål

En ESP32-node fungerer som en strømgjerrig (< 0.3 W), robust og rimelig gateway plassert i nærheten av en Yale Doorman-lås:
1. Kobler seg til lokalt Wi-Fi (med fallback eller offline-caching).
2. Poller WordPress Booking REST API (`GET /wp-json/snippen/v1/door/bookings?lock_id=<id>`).
3. Oppretter BLE-forbindelse til Yale Doorman Access Module ved aktiveringstidspunkt (JIT-provisjonering).
4. Kjører August AES-128-CCM kryptering og programmerer PIN-kode i ledig slot (3–9).
5. Sletter PIN-kode ved bookingens utløp.

## Modulstruktur

```
firmware/esp32/
├── README.md               # Denne arkitekturbeskrivelsen
├── config.example.h        # Eksempeloppsett (Wi-Fi SSID, WordPress API URL, Lock ID, Yale Key)
└── src/
    ├── main.cpp            # Applikasjonsflyt, oppstart og timer-loop
    ├── config_store.h      # NVS Flash / Preferences for lagring av offline koder og nøkler
    ├── booking_client.h    # HTTPS klient for WordPress REST API kommunikasjon
    ├── yale_ble.h          # BLE NimBLE klient og August sesjonshåndtering
    └── yale_crypto.h       # Maskinvare-akselerert AES-128-CCM og sjekksumberegning
```

## Krav til ESP32 Maskinvare & Biblioteker

- **Maskinvare:** ESP32 med minst 4MB Flash (støtter OTA-oppdateringer og NVS).
- **Bluetooth:** NimBLE (mer minneeffektivt enn standard Bluedroid-stakk i ESP-IDF / Arduino).
- **Kryptografi:** MbedTLS (inkludert i ESP-IDF) med støtte for maskinvareakselerert AES-128-CCM.
- **Tidssynkronisering:** SNTP (`pool.ntp.org`) for nøyaktig UTC-klokke ved tidslukeberegning.
