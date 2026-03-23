const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, 'data');

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

// --- App Lifecycle ---

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
