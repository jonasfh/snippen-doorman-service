/**
 * Web Bluetooth (BLE) client for Snippen Doorman Gateway (Raspberry Pi).
 *
 * Implements GATT client communication for provisioning and telemetry
 * matching the GATT server defined in snippen_doorman.ble.wifi_peripheral.
 */

export const SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
export const CHAR_CONFIG_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
export const CHAR_STATUS_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';
export const CHAR_COMMAND_UUID = '6e400004-b5a3-f393-e0a9-e50e24dcca9e';
export const DEVICE_NAME_PREFIX = 'Snippen';

export function isWebBluetoothSupported() {
  return (
    typeof navigator !== 'undefined' &&
    'bluetooth' in navigator &&
    typeof navigator.bluetooth.requestDevice === 'function'
  );
}

export function encodeJson(obj) {
  const jsonStr = JSON.stringify(obj);
  return new TextEncoder().encode(jsonStr);
}

export function decodeJson(buffer) {
  if (typeof buffer === 'string') {
    return JSON.parse(buffer);
  }
  const text = new TextDecoder('utf-8').decode(buffer);
  return JSON.parse(text);
}

export class SnippenBLEClient extends EventTarget {
  constructor() {
    super();
    this.device = null;
    this.server = null;
    this.service = null;
    this.charStatus = null;
    this.charCommand = null;
    this.isConnected = false;
    this._pendingCommands = new Map();

    this._onDisconnectedBound = this._handleDisconnected.bind(this);
    this._onStatusNotificationBound = this._handleStatusNotification.bind(this);
    this._onCommandNotificationBound = this._handleCommandNotification.bind(this);
  }

  async connect(options = {}) {
    if (!isWebBluetoothSupported()) {
      throw new Error(
        'Web Bluetooth støttes ikke i denne nettleseren. Bruk Chrome på Android, Edge/Chrome på PC/Mac, eller Bluefy på iOS.'
      );
    }

    if (this.isConnected) {
      return { deviceName: this.device.name, deviceId: this.device.id };
    }

    const acceptAllDevices = options.acceptAllDevices ?? false;
    const requestOptions = acceptAllDevices
      ? {
          acceptAllDevices: true,
          optionalServices: [SERVICE_UUID],
        }
      : {
          filters: options.filters || [
            { namePrefix: DEVICE_NAME_PREFIX },
            { services: [SERVICE_UUID] },
          ],
          optionalServices: [SERVICE_UUID],
        };

    try {
      this.device = await navigator.bluetooth.requestDevice(requestOptions);

      this.device.addEventListener('gattserverdisconnected', this._onDisconnectedBound);

      this.server = await this.device.gatt.connect();

      try {
        this.service = await this.server.getPrimaryService(SERVICE_UUID);
      } catch (err) {
        throw new Error(
          `Koblet til "${this.device.name || this.device.id}", men fant ikke Snippen-servicen (${SERVICE_UUID}). Er dette riktig enhet? (${err.message})`
        );
      }

      this.charStatus = await this.service.getCharacteristic(CHAR_STATUS_UUID);
      this.charCommand = await this.service.getCharacteristic(CHAR_COMMAND_UUID);

      await this.charStatus.startNotifications();
      this.charStatus.addEventListener(
        'characteristicvaluechanged',
        this._onStatusNotificationBound
      );

      await this.charCommand.startNotifications();
      this.charCommand.addEventListener(
        'characteristicvaluechanged',
        this._onCommandNotificationBound
      );

      this.isConnected = true;
      const deviceName = this.device.name || 'Snippen-Doorman';
      this.dispatchEvent(
        new CustomEvent('connected', {
          detail: { deviceName, deviceId: this.device.id },
        })
      );

      return { deviceName, deviceId: this.device.id };
    } catch (err) {
      this.disconnect();
      throw err;
    }
  }

  async disconnect() {
    this._pendingCommands.clear();
    if (this.device && this.device.gatt.connected) {
      this.device.gatt.disconnect();
    }
    this._handleDisconnected();
  }

  _handleDisconnected() {
    const wasConnected = this.isConnected;
    this.isConnected = false;
    this.server = null;
    this.service = null;
    this.charStatus = null;
    this.charCommand = null;

    if (this.device) {
      this.device.removeEventListener('gattserverdisconnected', this._onDisconnectedBound);
      this.device = null;
    }

    if (wasConnected) {
      this.dispatchEvent(new CustomEvent('disconnected'));
    }
  }

  _handleStatusNotification(event) {
    try {
      const data = decodeJson(event.target.value);
      this.dispatchEvent(new CustomEvent('status', { detail: data }));
    } catch (err) {
      console.error('[BLE] Error parsing status payload:', err);
    }
  }

  _handleCommandNotification(event) {
    try {
      const data = decodeJson(event.target.value);
      const cmdName = data.cmd;
      if (cmdName && this._pendingCommands.has(cmdName)) {
        const { resolve, timeoutId } = this._pendingCommands.get(cmdName);
        clearTimeout(timeoutId);
        this._pendingCommands.delete(cmdName);
        resolve(data);
      }
      this.dispatchEvent(new CustomEvent('command', { detail: data }));
    } catch (err) {
      console.error('[BLE] Error parsing command notification:', err);
    }
  }

  async sendCommand(commandObj, timeoutMs = 25000) {
    if (!this.isConnected || !this.charCommand) {
      throw new Error('Not connected to BLE peripheral');
    }

    const cmdName = commandObj.cmd;
    const encoded = encodeJson(commandObj);

    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        this._pendingCommands.delete(cmdName);
        reject(new Error(`Timeout waiting for command response '${cmdName}'`));
      }, timeoutMs);

      this._pendingCommands.set(cmdName, { resolve, reject, timeoutId });

      this.charCommand.writeValue(encoded).catch((err) => {
        clearTimeout(timeoutId);
        this._pendingCommands.delete(cmdName);
        reject(err);
      });
    });
  }

  async scanWifi() {
    return this.sendCommand({ cmd: 'SCAN_WIFI' });
  }

  async testWifi(ssid, password) {
    return this.sendCommand({ cmd: 'TEST_WIFI', wifi_ssid: ssid, wifi_password: password });
  }

  async applyAndExit() {
    return this.sendCommand({ cmd: 'APPLY_AND_EXIT' }, 5000);
  }
}

/**
 * Simulator client for testing without physical Bluetooth hardware.
 */
export class MockSnippenBLEClient extends EventTarget {
  constructor() {
    super();
    this.isConnected = false;
    this.device = { name: 'Snippen-Doorman-Sim', id: 'mock-01' };
  }

  async connect() {
    this.isConnected = true;
    setTimeout(() => {
      this.dispatchEvent(
        new CustomEvent('connected', {
          detail: { deviceName: this.device.name, deviceId: this.device.id },
        })
      );
      this.dispatchEvent(
        new CustomEvent('status', {
          detail: {
            status: 'ok',
            device: 'Snippen-Doorman-Sim',
            wifi_connected: false,
            ble_setup_active: true,
            remaining_seconds: 580,
          },
        })
      );
    }, 100);
    return { deviceName: this.device.name, deviceId: this.device.id };
  }

  async disconnect() {
    this.isConnected = false;
    this.dispatchEvent(new CustomEvent('disconnected'));
  }

  async scanWifi() {
    return {
      cmd: 'SCAN_WIFI',
      status: 'ok',
      networks: [
        { ssid: 'Snippen-Guest', signal: 85, security: 'WPA2' },
        { ssid: 'Snippen-Styret', signal: 65, security: 'WPA3' },
      ],
    };
  }

  async testWifi(ssid, password) {
    return {
      cmd: 'TEST_WIFI',
      status: 'ok',
      connected: true,
      ssid,
      ip: '192.168.1.188',
      message: 'Simulated connection successful',
    };
  }

  async applyAndExit() {
    this.disconnect();
    return { cmd: 'APPLY_AND_EXIT', status: 'ok' };
  }
}
