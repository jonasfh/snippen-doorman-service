"""Embedded HTML/CSS/JS frontend for Snippen Doorman Web Dashboard."""

from __future__ import annotations

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="no">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Snippen Doorman Gateway</title>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #131b2e;
      --card-border: #1f2d47;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --badge-bg: #1e293b;
      --input-bg: #0b1120;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    body { background: var(--bg); color: var(--text); min-height: 100vh; padding: 1rem; }
    .container { max-width: 960px; margin: 0 auto; }

    /* Header */
    header { display: flex; justify-content: space-between; align-items: center; padding: 1rem 0 1.5rem; border-bottom: 1px solid var(--card-border); margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem; }
    .logo-area { display: flex; align-items: center; gap: 0.75rem; }
    .logo-icon { width: 36px; height: 36px; background: linear-gradient(135deg, #2563eb, #10b981); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 1.25rem; font-weight: bold; }
    h1 { font-size: 1.35rem; font-weight: 700; letter-spacing: -0.02em; }
    .status-pill { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0.75rem; border-radius: 9999px; font-size: 0.8rem; font-weight: 600; background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
    .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: #10b981; box-shadow: 0 0 8px #10b981; animation: pulse 2s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.85); } }

    /* Nav Tabs */
    nav { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; overflow-x: auto; padding-bottom: 0.25rem; }
    .nav-btn { background: var(--card-bg); border: 1px solid var(--card-border); color: var(--text-muted); padding: 0.6rem 1.1rem; border-radius: 8px; font-weight: 600; font-size: 0.9rem; cursor: pointer; transition: all 0.2s; white-space: nowrap; }
    .nav-btn:hover { color: var(--text); border-color: #3b82f6; }
    .nav-btn.active { background: #1e3a8a; border-color: #3b82f6; color: #fff; }

    /* Cards & Layout */
    .tab-content { display: none; }
    .tab-content.active { display: block; animation: fadeIn 0.25s ease-in-out; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
    .grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.25rem; margin-bottom: 1.25rem; }
    .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 1.25rem; box-shadow: 0 4px 12px rgba(0,0,0,0.3); margin-bottom: 1.25rem; }
    .card-title { font-size: 1.05rem; font-weight: 700; margin-bottom: 1rem; display: flex; align-items: center; justify-content: space-between; color: #cbd5e1; }

    /* Key-Value Rows */
    .stat-row { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.9rem; }
    .stat-row:last-child { border-bottom: none; }
    .stat-label { color: var(--text-muted); }
    .stat-val { font-weight: 600; font-variant-numeric: tabular-nums; }
    .badge { padding: 0.2rem 0.55rem; border-radius: 6px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
    .badge-green { background: rgba(16, 185, 129, 0.2); color: #34d399; }
    .badge-yellow { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
    .badge-red { background: rgba(239, 68, 68, 0.2); color: #f87171; }
    .badge-blue { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }

    /* Action Buttons */
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 0.5rem; padding: 0.65rem 1.2rem; border-radius: 8px; font-size: 0.9rem; font-weight: 600; cursor: pointer; transition: all 0.15s; border: none; text-decoration: none; }
    .btn-primary { background: var(--primary); color: white; }
    .btn-primary:hover { background: var(--primary-hover); }
    .btn-success { background: var(--success); color: white; }
    .btn-success:hover { background: #059669; }
    .btn-danger { background: var(--danger); color: white; }
    .btn-secondary { background: #334155; color: white; }
    .btn-secondary:hover { background: #475569; }
    .btn-sm { padding: 0.4rem 0.75rem; font-size: 0.8rem; }
    .btn-block { width: 100%; }

    /* Forms & Inputs */
    .form-group { margin-bottom: 1rem; }
    label { display: block; font-size: 0.85rem; font-weight: 600; margin-bottom: 0.4rem; color: #cbd5e1; }
    input[type="text"], input[type="password"], input[type="number"], select {
      width: 100%; padding: 0.65rem 0.85rem; background: var(--input-bg); border: 1px solid var(--card-border);
      border-radius: 8px; color: var(--text); font-size: 0.9rem; outline: none; transition: border-color 0.2s;
    }
    input:focus { border-color: var(--primary); }
    .help-text { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.35rem; }

    /* Event Log Table */
    .log-terminal { background: #070a12; border: 1px solid #172033; border-radius: 8px; padding: 0.75rem; font-family: monospace; font-size: 0.8rem; max-height: 220px; overflow-y: auto; color: #a5b4fc; }
    .log-line { margin-bottom: 0.35rem; word-break: break-all; }
    .log-time { color: #64748b; margin-right: 0.5rem; }

    /* Alerts & Toasts */
    .toast { position: fixed; bottom: 1.5rem; right: 1.5rem; background: #1e293b; color: white; padding: 0.9rem 1.3rem; border-radius: 10px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); font-size: 0.9rem; font-weight: 600; display: none; z-index: 100; border-left: 5px solid var(--primary); }
    .toast.success { border-left-color: var(--success); }
    .toast.error { border-left-color: var(--danger); }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="logo-area">
        <div class="logo-icon">🚪</div>
        <div>
          <h1>Snippen Doorman Gateway</h1>
          <div style="font-size: 0.75rem; color: var(--text-muted);">Adgangskontroll for Yale Doorman Classic over BLE</div>
        </div>
      </div>
      <div>
        <span class="status-pill">
          <span class="pulse-dot"></span>
          <span id="header-status">Tilkoblet</span>
        </span>
      </div>
    </header>

    <nav>
      <button class="nav-btn active" onclick="showTab('status')">📊 Oversikt & Test</button>
      <button class="nav-btn" onclick="showTab('locks')">🔐 Dørlåser</button>
      <button class="nav-btn" onclick="showTab('api')">🌐 Booking API</button>
      <button class="nav-btn" onclick="showTab('ble')">📡 BLE WiFi Oppsett</button>
    </nav>

    <!-- TAB 1: OVERSIKT & TEST -->
    <div id="tab-status" class="tab-content active">
      <div class="grid-2">
        <!-- System Status -->
        <div class="card">
          <div class="card-title">🖥️ Gateway Status</div>
          <div class="stat-row"><span class="stat-label">Vertsnavn:</span><span class="stat-val" id="sys-hostname">-</span></div>
          <div class="stat-row"><span class="stat-label">Lokal IP:</span><span class="stat-val" id="sys-ip">-</span></div>
          <div class="stat-row"><span class="stat-label">WiFi Nettverk:</span><span class="stat-val" id="sys-wifi">-</span></div>
          <div class="stat-row"><span class="stat-label">Oppetid:</span><span class="stat-val" id="sys-uptime">-</span></div>
          <div class="stat-row"><span class="stat-label">Tjenesteversjon:</span><span class="stat-val" id="sys-version">0.11.0</span></div>
        </div>

        <!-- Lock Status -->
        <div class="card">
          <div class="card-title">
            <span>🚪 Primærlås</span>
            <span class="badge badge-green" id="lock-state-badge">Tilkoblet</span>
          </div>
          <div class="stat-row"><span class="stat-label">Navn:</span><span class="stat-val" id="lock-name">Hoveddør</span></div>
          <div class="stat-row"><span class="stat-label">MAC-adresse:</span><span class="stat-val" id="lock-addr">-</span></div>
          <div class="stat-row"><span class="stat-label">Låsetilstand:</span><span class="stat-val" id="lock-status">-</span></div>
          <div class="stat-row"><span class="stat-label">Dørtilstand:</span><span class="stat-val" id="door-status">-</span></div>
          <div class="stat-row"><span class="stat-label">Batterinivå:</span><span class="stat-val" id="lock-battery">-</span></div>
        </div>
      </div>

      <!-- Quick Actions -->
      <div class="card">
        <div class="card-title">⚡ Hurtighandlinger</div>
        <div style="display: flex; gap: 0.75rem; flex-wrap: wrap;">
          <button class="btn btn-primary" onclick="triggerUnlock()">🔓 Lås opp dør (Test)</button>
          <button class="btn btn-secondary" onclick="triggerLock()">🔒 Lås dør (Test)</button>
          <button class="btn btn-secondary" onclick="triggerSync()">🔄 Synkroniser reservasjoner nå</button>
          <button class="btn btn-secondary" onclick="testLockStatus()">🔋 Oppdater batteri over BLE</button>
        </div>
      </div>

      <!-- Sync Logs -->
      <div class="card">
        <div class="card-title">📋 Siste hendelser og synkroniseringslogg</div>
        <div class="log-terminal" id="log-terminal">
          <div class="log-line"><span class="log-time">[System]</span> Initialiserer dashboard...</div>
        </div>
      </div>
    </div>

    <!-- TAB 2: DØRLÅSER -->
    <div id="tab-locks" class="tab-content">
      <div class="card">
        <div class="card-title">🔐 Konfigurer Yale Doorman Lås(er)</div>
        <form id="locks-form" onsubmit="saveLocks(event)">
          <div id="locks-container">
            <!-- Dynamically populated locks -->
          </div>
          <div style="display: flex; gap: 0.75rem; margin-top: 1rem;">
            <button type="submit" class="btn btn-success">Lagre låsinnstillinger</button>
            <button type="button" class="btn btn-secondary" onclick="addLockRow()">+ Legg til dør</button>
          </div>
        </form>
      </div>
    </div>

    <!-- TAB 3: BOOKING API -->
    <div id="tab-api" class="tab-content">
      <div class="card">
        <div class="card-title">🌐 WordPress Booking API & Tidsinnstillinger</div>
        <form id="api-form" onsubmit="saveApiSettings(event)">
          <div class="form-group">
            <label for="cfg-api-url">REST API Endepunkt</label>
            <input type="text" id="cfg-api-url" name="api_url" placeholder="https://vestreholmensameie.no/wp-json/snippen/v1/door">
            <div class="help-text">Standard: https://vestreholmensameie.no/wp-json/snippen/v1/door</div>
          </div>
          <div class="form-group">
            <label for="cfg-api-token">Bearer Token / API-nøkkel</label>
            <input type="password" id="cfg-api-token" name="api_token" placeholder="Hemmelig API-token">
            <div class="help-text">Autentiseringstoken generert i Snippen Booking-plugin.</div>
          </div>
          <div class="grid-2">
            <div class="form-group">
              <label for="cfg-lead-time">Lead Time (minutter før start)</label>
              <input type="number" id="cfg-lead-time" name="lead_time_minutes" value="60">
              <div class="help-text">Hvor mange minutter før booking koden legges i låsen.</div>
            </div>
            <div class="form-group">
              <label for="cfg-grace-period">Grace Period (minutter etter slutt)</label>
              <input type="number" id="cfg-grace-period" name="grace_period_minutes" value="15">
              <div class="help-text">Hvor lenge koden beholdes før sletting.</div>
            </div>
          </div>
          <div style="display: flex; gap: 0.75rem; margin-top: 1rem;">
            <button type="submit" class="btn btn-success">Lagre API-innstillinger</button>
            <button type="button" class="btn btn-secondary" onclick="testApiConnection()">Test API-forbindelse</button>
          </div>
        </form>
      </div>
    </div>

    <!-- TAB 4: BLE SETUP -->
    <div id="tab-ble" class="tab-content">
      <div class="card">
        <div class="card-title">📡 Bluetooth WiFi-oppsett (GATT Peripheral)</div>
        <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 1.25rem;">
          Gjør det mulig å endre WiFi-nettverk uten skjerm, tastatur eller nettverkskabel via en mobiltelefon med Web Bluetooth API.
        </p>
        <div class="stat-row">
          <span class="stat-label">Oppsettmodus status:</span>
          <span class="stat-val" id="ble-setup-status"><span class="badge badge-yellow">Venter på aktivering</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Fysisk GPIO-knapp:</span>
          <span class="stat-val" id="gpio-pin-label">GPIO 26 (Aktiv)</span>
        </div>
        <div style="display: flex; gap: 0.75rem; margin-top: 1.5rem;">
          <button class="btn btn-primary" onclick="activateBleSetup()">Aktiver BLE-oppsett i 10 minutter</button>
          <a class="btn btn-secondary" href="/web-config" target="_blank">Åpne Web Bluetooth Verktøy</a>
        </div>
      </div>
    </div>

  </div>

  <div id="toast" class="toast">Varselmelding</div>

  <script>
    let currentConfig = null;

    function showTab(name) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
      document.getElementById('tab-' + name).classList.add('active');
      event.target.classList.add('active');
      if (name === 'locks' || name === 'api') loadConfig();
    }

    function showToast(msg, type = 'info') {
      const toast = document.getElementById('toast');
      toast.textContent = msg;
      toast.className = 'toast ' + type;
      toast.style.display = 'block';
      setTimeout(() => { toast.style.display = 'none'; }, 4000);
    }

    function updateLockStateInUI(lk) {
      if (!lk) return;
      const lockMap = { 'unlocked': 'Ulåst', 'locked': 'Låst', 'jammed': 'Fastkilt', 'unknown': 'UKJENT' };
      const doorMap = { 'closed': 'Lukket', 'open': 'Åpen', 'unknown': 'UKJENT' };
      if (lk.name) document.getElementById('lock-name').textContent = lk.name;
      if (lk.address) document.getElementById('lock-addr').textContent = lk.address;
      if (lk.lock_status) {
        const s = lk.lock_status.toLowerCase();
        document.getElementById('lock-status').textContent = lockMap[s] || lk.lock_status.toUpperCase();
      }
      if (lk.door_status) {
        const s = lk.door_status.toLowerCase();
        document.getElementById('door-status').textContent = doorMap[s] || lk.door_status.toUpperCase();
      }
      if (lk.battery != null) {
        document.getElementById('lock-battery').textContent = lk.battery + '%';
      }
    }

    async function loadStatus() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById('sys-hostname').textContent = data.hostname || '-';
        document.getElementById('sys-ip').textContent = data.ip || '-';
        document.getElementById('sys-wifi').textContent = data.wifi_ssid || 'Kabel (Ethernet)';
        document.getElementById('sys-uptime').textContent = data.uptime || '-';

        if (data.primary_lock) {
          updateLockStateInUI(data.primary_lock);
        }

        if (data.events && data.events.length) {
          const terminal = document.getElementById('log-terminal');
          terminal.innerHTML = data.events.map(e => `<div class="log-line"><span class="log-time">[${e.time}]</span> ${e.msg}</div>`).join('');
        }
      } catch (err) {
        console.error('Status fetch error:', err);
      }
    }

    async function loadConfig() {
      try {
        const res = await fetch('/api/config');
        if (!res.ok) return;
        currentConfig = await res.json();

        // Populate API tab
        document.getElementById('cfg-api-url').value = currentConfig.api_url || '';
        document.getElementById('cfg-api-token').value = currentConfig.api_token_masked || '';
        document.getElementById('cfg-lead-time').value = currentConfig.lead_time_minutes || 60;
        document.getElementById('cfg-grace-period').value = currentConfig.grace_period_minutes || 15;
        document.getElementById('gpio-pin-label').textContent = `GPIO ${currentConfig.gpio_button_pin || 26} (Aktiv)`;

        // Populate Locks tab
        renderLocks(currentConfig.locks || []);
      } catch (err) {
        showToast('Kunne ikke hente innstillinger: ' + err.message, 'error');
      }
    }

    function renderLocks(locks) {
      const container = document.getElementById('locks-container');
      if (!locks || !locks.length) {
        locks = [{ name: 'Hoveddør', address: '', key_masked: '', slot: 1 }];
      }
      container.innerHTML = locks.map((lk, i) => `
        <div style="background: rgba(0,0,0,0.25); border: 1px solid var(--card-border); padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
          <div style="font-weight: 700; margin-bottom: 0.75rem;">Dør #${i + 1}</div>
          <div class="grid-2">
            <div class="form-group">
              <label>Dørnavn</label>
              <input type="text" class="lock-name" value="${lk.name || ''}" placeholder="F.eks. Ytterdør">
            </div>
            <div class="form-group">
              <label>Bluetooth MAC-adresse</label>
              <input type="text" class="lock-addr" value="${lk.address || ''}" placeholder="XX:XX:XX:XX:XX:XX">
            </div>
          </div>
          <div class="grid-2">
            <div class="form-group">
              <label>Offline Nøkkel (16-byte hex)</label>
              <input type="password" class="lock-key" value="${lk.key_masked || ''}" placeholder="32 heksadesimale tegn">
            </div>
            <div class="form-group">
              <label>Nøkkelspor (Slot)</label>
              <input type="number" class="lock-slot" value="${lk.slot || 1}" min="1" max="10">
            </div>
          </div>
        </div>
      `).join('');
    }

    function addLockRow() {
      const container = document.getElementById('locks-container');
      const count = container.children.length + 1;
      const div = document.createElement('div');
      div.innerHTML = `
        <div style="background: rgba(0,0,0,0.25); border: 1px solid var(--card-border); padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
          <div style="font-weight: 700; margin-bottom: 0.75rem;">Dør #${count}</div>
          <div class="grid-2">
            <div class="form-group">
              <label>Dørnavn</label>
              <input type="text" class="lock-name" value="Dør ${count}" placeholder="Dørnavn">
            </div>
            <div class="form-group">
              <label>Bluetooth MAC-adresse</label>
              <input type="text" class="lock-addr" value="" placeholder="XX:XX:XX:XX:XX:XX">
            </div>
          </div>
          <div class="grid-2">
            <div class="form-group">
              <label>Offline Nøkkel (16-byte hex)</label>
              <input type="password" class="lock-key" value="" placeholder="32 heksadesimale tegn">
            </div>
            <div class="form-group">
              <label>Nøkkelspor (Slot)</label>
              <input type="number" class="lock-slot" value="1" min="1" max="10">
            </div>
          </div>
        </div>
      `;
      container.appendChild(div.firstElementChild);
    }

    async function saveLocks(e) {
      e.preventDefault();
      const names = document.querySelectorAll('.lock-name');
      const addrs = document.querySelectorAll('.lock-addr');
      const keys = document.querySelectorAll('.lock-key');
      const slots = document.querySelectorAll('.lock-slot');

      const locks = [];
      for (let i = 0; i < names.length; i++) {
        locks.push({
          name: names[i].value.trim(),
          address: addrs[i].value.trim(),
          key: keys[i].value.trim(),
          slot: parseInt(slots[i].value, 10) || 1
        });
      }

      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ locks })
        });
        const data = await res.json();
        if (data.success) {
          showToast('Låsinnstillinger lagret!', 'success');
          loadConfig();
        } else {
          showToast('Feil: ' + (data.errors || []).join(', '), 'error');
        }
      } catch (err) {
        showToast('Kunne ikke lagre: ' + err.message, 'error');
      }
    }

    async function saveApiSettings(e) {
      e.preventDefault();
      const body = {
        api_url: document.getElementById('cfg-api-url').value.trim(),
        api_token: document.getElementById('cfg-api-token').value.trim(),
        lead_time_minutes: parseInt(document.getElementById('cfg-lead-time').value, 10),
        grace_period_minutes: parseInt(document.getElementById('cfg-grace-period').value, 10)
      };
      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
        const data = await res.json();
        if (data.success) {
          showToast('API-innstillinger lagret!', 'success');
        } else {
          showToast('Feil: ' + (data.errors || []).join(', '), 'error');
        }
      } catch (err) {
        showToast('Kunne ikke lagre: ' + err.message, 'error');
      }
    }

    async function triggerUnlock() {
      if (!confirm('Vil du sende test-opplåsingssignal til låsen over BLE?')) return;
      showToast('Sender opplåsingskommando over BLE...', 'info');
      try {
        const res = await fetch('/api/test/unlock', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast('Døren er låst opp!', 'success');
          updateLockStateInUI(data);
          loadStatus();
        } else {
          showToast('Kunne ikke låse opp: ' + data.error, 'error');
        }
      } catch (err) {
        showToast('Feil: ' + err.message, 'error');
      }
    }

    async function triggerLock() {
      if (!confirm('Vil du sende test-låsesignal til låsen over BLE?')) return;
      showToast('Sender låsekommando over BLE...', 'info');
      try {
        const res = await fetch('/api/test/lock', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast('Døren er låst!', 'success');
          updateLockStateInUI(data);
          loadStatus();
        } else {
          showToast('Kunne ikke låse: ' + data.error, 'error');
        }
      } catch (err) {
        showToast('Feil: ' + err.message, 'error');
      }
    }

    async function triggerSync() {
      showToast('Kjører synkronisering...', 'info');
      try {
        const res = await fetch('/api/sync', { method: 'POST' });
        const data = await res.json();
        showToast(`Synk fullført: ${data.added || 0} nye, ${data.activated || 0} aktivert`, 'success');
        loadStatus();
      } catch (err) {
        showToast('Synk-feil: ' + err.message, 'error');
      }
    }

    async function testLockStatus() {
      showToast('Kobler til låsen over BLE...', 'info');
      try {
        const res = await fetch('/api/test/status', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast(`Lås svarte! Batteri: ${data.battery != null ? data.battery + '%' : 'N/A'}`, 'success');
          updateLockStateInUI(data);
          loadStatus();
        } else {
          showToast('Feil under oppkobling: ' + data.error, 'error');
        }
      } catch (err) {
        showToast('Feil: ' + err.message, 'error');
      }
    }

    async function testApiConnection() {
      showToast('Tester Booking API...', 'info');
      try {
        const res = await fetch('/api/test/api', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast(`API Svarte OK! Fant ${data.bookings_count} reservasjoner.`, 'success');
        } else {
          showToast('API-feil: ' + data.error, 'error');
        }
      } catch (err) {
        showToast('Nettverksfeil: ' + err.message, 'error');
      }
    }

    async function activateBleSetup() {
      showToast('Aktiverer BLE-oppsett i 10 min...', 'info');
      try {
        const res = await fetch('/api/ble-setup', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          document.getElementById('ble-setup-status').innerHTML = '<span class="badge badge-green">Aktiv (10 min)</span>';
          showToast('BLE-annonsering startet!', 'success');
        }
      } catch (err) {
        showToast('Kunne ikke starte BLE: ' + err.message, 'error');
      }
    }

    // Polling every 5s
    loadStatus();
    setInterval(loadStatus, 5000);
  </script>
</body>
</html>
"""
