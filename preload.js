const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('furnaceAPI', {
  // Existing data I/O
  readAllocations: () => ipcRenderer.invoke('read-json', 'allocations.json'),
  writeAllocations: (data) => ipcRenderer.invoke('write-json', 'allocations.json', data),
  readActuals: () => ipcRenderer.invoke('read-json', 'actuals.json'),
  writeActuals: (data) => ipcRenderer.invoke('write-json', 'actuals.json', data),
  openCsvDialog: () => ipcRenderer.invoke('open-csv-dialog'),
  readCsv: (filePath) => ipcRenderer.invoke('read-csv', filePath),

  // Spark auth
  sparkLogin: (email, password) => ipcRenderer.invoke('spark-login', email, password),
  sparkGetToken: () => ipcRenderer.invoke('spark-get-token'),
  sparkGetStatus: () => ipcRenderer.invoke('spark-get-status'),
  sparkLogout: () => ipcRenderer.invoke('spark-logout'),

  // Spark config
  sparkReadConfig: () => ipcRenderer.invoke('spark-config-read'),
  sparkWriteConfig: (config) => ipcRenderer.invoke('spark-config-write', config),

  // OOP Schedule
  readOopSchedule: () => ipcRenderer.invoke('read-json', 'oop-schedule.json'),
  writeOopSchedule: (data) => ipcRenderer.invoke('write-json', 'oop-schedule.json', data),
});
