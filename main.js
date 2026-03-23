const { app, BrowserWindow, ipcMain, dialog, safeStorage } = require('electron');
const fs = require('fs');
const path = require('path');
const https = require('https');

const DATA_DIR = path.join(__dirname, 'data');

// --- Spark Auth Helpers ---

const SPARK_AUTH_FILE = path.join(app.getPath('userData'), 'spark-auth.enc');

function sparkHttpPost(url, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const postData = JSON.stringify(body);
    const req = https.request({
      hostname: parsed.hostname,
      port: 443,
      path: parsed.pathname + parsed.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData),
        ...headers,
      },
    }, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
        catch { resolve({ status: res.statusCode, body: data }); }
      });
    });
    req.on('error', reject);
    req.write(postData);
    req.end();
  });
}

function readSparkAuth() {
  try {
    const encrypted = fs.readFileSync(SPARK_AUTH_FILE);
    const decrypted = safeStorage.decryptString(encrypted);
    return JSON.parse(decrypted);
  } catch { return null; }
}

function writeSparkAuth(authData) {
  const encrypted = safeStorage.encryptString(JSON.stringify(authData));
  fs.writeFileSync(SPARK_AUTH_FILE, encrypted);
}

function deleteSparkAuth() {
  try { fs.unlinkSync(SPARK_AUTH_FILE); } catch {}
}

function readSparkConfig() {
  try {
    return JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'spark-config.json'), 'utf8'));
  } catch { return null; }
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    title: 'Furnace — Forge Portfolio Tracker',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  win.loadFile('index.html');
}

// --- IPC Handlers ---

ipcMain.handle('read-json', async (_event, filename) => {
  const filePath = path.join(DATA_DIR, filename);
  try {
    const content = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(content);
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw err;
  }
});

ipcMain.handle('write-json', async (_event, filename, data) => {
  const filePath = path.join(DATA_DIR, filename);
  const tmpPath = filePath + '.tmp';
  const content = JSON.stringify(data, null, 2) + '\n';
  fs.writeFileSync(tmpPath, content, 'utf8');
  fs.renameSync(tmpPath, filePath);
  return true;
});

ipcMain.handle('open-csv-dialog', async () => {
  const result = await dialog.showOpenDialog({
    title: 'Import Actuals CSV',
    filters: [{ name: 'CSV Files', extensions: ['csv'] }],
    properties: ['openFile'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

ipcMain.handle('read-csv', async (_event, filePath) => {
  return fs.readFileSync(filePath, 'utf8');
});

// --- Spark Auth IPC Handlers ---

ipcMain.handle('spark-login', async () => {
  const config = readSparkConfig();
  if (!config) return { ok: false, error: 'Spark config not found. Check data/spark-config.json.' };

  // Open Google OAuth via Supabase in a popup window
  return new Promise((resolve) => {
    const redirectUrl = `${config.supabaseUrl}/auth/v1/callback`;
    const oauthUrl = `${config.supabaseUrl}/auth/v1/authorize?provider=google&redirect_to=${encodeURIComponent('https://forge-spark.vercel.app')}`;

    const authWin = new BrowserWindow({
      width: 600,
      height: 700,
      title: 'Sign in to Spark',
      webPreferences: { nodeIntegration: false, contextIsolation: true },
    });

    let resolved = false;

    // Watch for the redirect that contains the access token in the URL hash
    authWin.webContents.on('will-redirect', (event, url) => {
      handleAuthUrl(url);
    });

    authWin.webContents.on('will-navigate', (event, url) => {
      handleAuthUrl(url);
    });

    // Also poll the URL periodically (some OAuth flows don't trigger will-redirect)
    const pollInterval = setInterval(() => {
      if (resolved || authWin.isDestroyed()) { clearInterval(pollInterval); return; }
      try {
        const currentUrl = authWin.webContents.getURL();
        handleAuthUrl(currentUrl);
      } catch {}
    }, 500);

    function handleAuthUrl(url) {
      if (resolved) return;
      // Supabase returns tokens in URL hash: #access_token=...&refresh_token=...
      if (url.includes('access_token=') && url.includes('refresh_token=')) {
        resolved = true;
        clearInterval(pollInterval);

        // Parse hash fragment (may be after # or after ?)
        const hashPart = url.includes('#') ? url.split('#')[1] : url.split('?')[1];
        const params = new URLSearchParams(hashPart);
        const access_token = params.get('access_token');
        const refresh_token = params.get('refresh_token');
        const expires_in = parseInt(params.get('expires_in') || '3600');

        if (access_token && refresh_token) {
          // Decode the JWT to get user email
          let email = 'unknown';
          try {
            const payload = JSON.parse(Buffer.from(access_token.split('.')[1], 'base64').toString());
            email = payload.email || payload.sub || 'unknown';
          } catch {}

          writeSparkAuth({
            access_token,
            refresh_token,
            expires_at: Date.now() + (expires_in * 1000) - 60000,
            user_email: email,
          });

          authWin.close();
          resolve({ ok: true, email });
        } else {
          authWin.close();
          resolve({ ok: false, error: 'Missing tokens in OAuth response' });
        }
      }
    }

    authWin.on('closed', () => {
      clearInterval(pollInterval);
      if (!resolved) {
        resolved = true;
        resolve({ ok: false, error: 'Sign-in window was closed' });
      }
    });

    authWin.loadURL(oauthUrl);
  });
});

ipcMain.handle('spark-get-token', async () => {
  const auth = readSparkAuth();
  if (!auth) return null;

  // Check if token is expired
  if (Date.now() >= auth.expires_at) {
    const config = readSparkConfig();
    if (!config) return null;

    try {
      const res = await sparkHttpPost(
        `${config.supabaseUrl}/auth/v1/token?grant_type=refresh_token`,
        { refresh_token: auth.refresh_token },
        { apikey: config.supabaseAnonKey }
      );

      if (res.status !== 200) {
        deleteSparkAuth();
        return null;
      }

      const { access_token, refresh_token, expires_in } = res.body;
      writeSparkAuth({
        access_token,
        refresh_token,
        expires_at: Date.now() + (expires_in * 1000) - 60000,
        user_email: auth.user_email,
      });
      return access_token;
    } catch {
      deleteSparkAuth();
      return null;
    }
  }

  return auth.access_token;
});

ipcMain.handle('spark-get-status', async () => {
  const auth = readSparkAuth();
  if (!auth) return { connected: false };
  return { connected: true, email: auth.user_email };
});

ipcMain.handle('spark-logout', async () => {
  deleteSparkAuth();
  return true;
});

ipcMain.handle('spark-config-read', async () => {
  return readSparkConfig();
});

ipcMain.handle('spark-config-write', async (_event, config) => {
  const filePath = path.join(DATA_DIR, 'spark-config.json');
  const tmpPath = filePath + '.tmp';
  fs.writeFileSync(tmpPath, JSON.stringify(config, null, 2) + '\n', 'utf8');
  fs.renameSync(tmpPath, filePath);
  return true;
});

// --- App Lifecycle ---

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
