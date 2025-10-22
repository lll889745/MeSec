import { contextBridge, ipcRenderer } from 'electron';

type AllowedChannels = 'ping';

const api = {
  invoke: async (channel: AllowedChannels, ...args: unknown[]) => ipcRenderer.invoke(channel, ...args)
};

contextBridge.exposeInMainWorld('electronAPI', api);

export type ElectronApi = typeof api;
