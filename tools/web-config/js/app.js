import {
  SnippenBLEClient,
  MockSnippenBLEClient,
  isWebBluetoothSupported,
} from './ble.js';

let client = new SnippenBLEClient();
let isSimulator = false;

// DOM references
const btnConnect = document.getElementById('btn-connect');
const btnDisconnect = document.getElementById('btn-disconnect');
const statusPill = document.getElementById('status-pill');
const statusLabel = document.getElementById('status-label');
const wifiCard = document.getElementById('wifi-card');
const btnScanWifi = document.getElementById('btn-scan-wifi');
const wifiList = document.getElementById('wifi-list');
const wifiSsidInput = document.getElementById('wifi-ssid');
const wifiPasswordInput = document.getElementById('wifi-password');
const btnConnectWifi = document.getElementById('btn-connect-wifi');
const feedbackBanner = document.getElementById('feedback');
const dashboardCard = document.getElementById('dashboard-card');
const dashboardLink = document.getElementById('dashboard-link');
const btnApplyExit = document.getElementById('btn-apply-exit');
const simCheckbox = document.getElementById('sim-mode');

function showFeedback(msg, isSuccess = true) {
  feedbackBanner.textContent = msg;
  feedbackBanner.className = `feedback-banner ${isSuccess ? 'success' : 'error'}`;
}

function clearFeedback() {
  feedbackBanner.style.display = 'none';
}

function setupClientEvents(cli) {
  cli.addEventListener('connected', (e) => {
    statusPill.className = 'pill connected';
    statusLabel.textContent = e.detail.deviceName;
    btnConnect.style.display = 'none';
    btnDisconnect.style.display = 'block';
    wifiCard.style.display = 'block';
    showFeedback(`Tilkoblet til ${e.detail.deviceName} over BLE`, true);
  });

  cli.addEventListener('disconnected', () => {
    statusPill.className = 'pill';
    statusLabel.textContent = 'Frakoblet';
    btnConnect.style.display = 'block';
    btnDisconnect.style.display = 'none';
    wifiCard.style.display = 'none';
    dashboardCard.style.display = 'none';
  });

  cli.addEventListener('status', (e) => {
    const data = e.detail;
    if (data.ip) {
      showDashboardPrompt(data.ip);
    }
  });
}

function showDashboardPrompt(ip) {
  dashboardCard.style.display = 'block';
  const url = `http://${ip}:8080`;
  dashboardLink.href = url;
  dashboardLink.textContent = `Åpne Dashboard (${url})`;
}

if (simCheckbox) {
  simCheckbox.addEventListener('change', (e) => {
    isSimulator = e.target.checked;
    if (client.isConnected) {
      client.disconnect();
    }
    client = isSimulator ? new MockSnippenBLEClient() : new SnippenBLEClient();
    setupClientEvents(client);
    showFeedback(isSimulator ? 'Simulator-modus aktivert' : 'Ekte BLE-modus aktivert', true);
  });
}

setupClientEvents(client);

btnConnect.addEventListener('click', async () => {
  clearFeedback();
  try {
    btnConnect.disabled = true;
    btnConnect.textContent = 'Kobler til...';
    await client.connect();
  } catch (err) {
    showFeedback(`Tilkobling feilet: ${err.message}`, false);
  } finally {
    btnConnect.disabled = false;
    btnConnect.textContent = 'Koble til Doorman Gateway';
  }
});

btnDisconnect.addEventListener('click', () => {
  client.disconnect();
});

btnScanWifi.addEventListener('click', async () => {
  btnScanWifi.disabled = true;
  btnScanWifi.textContent = 'Skanner...';
  wifiList.innerHTML = '';
  try {
    const res = await client.scanWifi();
    const networks = res.networks || [];
    if (networks.length === 0) {
      wifiList.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">Ingen nettverk funnet.</div>';
    } else {
      networks.forEach((net) => {
        const item = document.createElement('div');
        item.className = 'network-item';
        item.innerHTML = `
          <span class="network-name">${net.ssid}</span>
          <span class="network-meta">${net.signal || ''}% • ${net.security || 'Åpen'}</span>
        `;
        item.addEventListener('click', () => {
          wifiSsidInput.value = net.ssid;
          wifiPasswordInput.focus();
        });
        wifiList.appendChild(item);
      });
    }
  } catch (err) {
    showFeedback(`Skanning feilet: ${err.message}`, false);
  } finally {
    btnScanWifi.disabled = false;
    btnScanWifi.textContent = 'Skann WiFi-nettverk';
  }
});

btnConnectWifi.addEventListener('click', async () => {
  const ssid = wifiSsidInput.value.trim();
  const pwd = wifiPasswordInput.value.trim();
  if (!ssid) {
    showFeedback('Velg eller skriv inn nettverksnavn (SSID)', false);
    return;
  }

  btnConnectWifi.disabled = true;
  btnConnectWifi.textContent = 'Kobler til WiFi...';
  try {
    const res = await client.testWifi(ssid, pwd);
    if (res.status === 'ok' && res.connected) {
      showFeedback(`Vellykket tilkoblet til ${ssid}! Tildelt IP: ${res.ip}`, true);
      if (res.ip) {
        showDashboardPrompt(res.ip);
      }
    } else {
      showFeedback(`Kunne ikke koble til ${ssid}: ${res.message || 'Ukjent feil'}`, false);
    }
  } catch (err) {
    showFeedback(`Tilkoblingsfeil: ${err.message}`, false);
  } finally {
    btnConnectWifi.disabled = false;
    btnConnectWifi.textContent = 'Lagre & Koble til';
  }
});

btnApplyExit.addEventListener('click', async () => {
  try {
    await client.applyAndExit();
    showFeedback('Oppsett fullført! BLE er slått av og gatewayen er på nett.', true);
  } catch (err) {
    showFeedback(`Feil under avslutning: ${err.message}`, false);
  }
});
