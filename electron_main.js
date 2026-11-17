/**
 * Lanzador Nativo Electron para ApexRIP Studio Pro (Python + Electron Desktop App)
 * Inicia automáticamente el motor RIP en Python (FastAPI/Uvicorn) en segundo plano
 * y abre la ventana nativa de escritorio conectada a los puertos USB y Red TCP/IP locales.
 */

const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

let pyProc = null;
let mainWindow = null;
const PORT = 8765;

function startPythonBackend() {
  const backendDir = path.join(__dirname, 'backend');
  pyProc = spawn('python3', ['-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', String(PORT)], {
    cwd: backendDir,
    stdio: 'inherit',
  });
}

function waitForServer(url, timeoutMs = 10000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      http
        .get(url, (res) => {
          resolve();
        })
        .on('error', () => {
          if (Date.now() - start > timeoutMs) {
            reject(new Error('Tiempo de espera agotado iniciando motor Python RIP'));
          } else {
            setTimeout(check, 250);
          }
        });
    };
    check();
  });
}

async function createWindow() {
  startPythonBackend();
  await waitForServer(`http://127.0.0.1:${PORT}/api/config`);

  mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1100,
    minHeight: 720,
    title: 'ApexRIP Studio Pro v2.4 — Gran Formato (Ecosolvente, Sublimación, UV)',
    backgroundColor: '#0d1117',
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(`http://127.0.0.1:${PORT}/`);
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (pyProc) {
    pyProc.kill();
    pyProc = null;
  }
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
