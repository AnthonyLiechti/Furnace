const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('furnaceAPI', {
  readAllocations: () => ipcRenderer.invoke('read-json', 'allocations.json'),
  writeAllocations: (data) => ipcRenderer.invoke('write-json', 'allocations.json', data),
  readActuals: () => ipcRenderer.invoke('read-json', 'actuals.json'),
  writeActuals: (data) => ipcRenderer.invoke('write-json', 'actuals.json', data),
  openCsvDialog: () => ipcRenderer.invoke('open-csv-dialog'),
  readCsv: (filePath) => ipcRenderer.invoke('read-csv', filePath),
});
