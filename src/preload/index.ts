import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron';

export type AnonymizeStartOptions = {
  inputPath: string;
  outputPath?: string;
  dataPackPath?: string;
  device?: string;
  classes?: string[];
  manualRois?: Array<[number, number, number, number]>;
  pythonPath?: string;
  modelPath?: string;
  aesKey?: string;
  hmacKey?: string;
  style?: string;
  disableDetection?: boolean;
  embedPack?: boolean;
  embeddedOutputPath?: string;
};

export type AnonymizeEventPayload = {
  jobId: string;
  event: string;
  [key: string]: unknown;
};

type AnonymizeStartResult = {
  jobId: string;
  outputPath: string;
  dataPackPath: string;
  embeddedOutputPath?: string;
};

export type RestoreStartOptions = {
  anonymizedPath: string;
  dataPackPath?: string;
  outputPath?: string;
  aesKey: string;
  hmacKey?: string;
  pythonPath?: string;
  useEmbeddedPack?: boolean;
};

type RestoreStartResult = {
  jobId: string;
  outputPath: string;
};

const api = {
  ping: () => ipcRenderer.invoke('ping') as Promise<string>,
  startAnonymize: (options: AnonymizeStartOptions): Promise<AnonymizeStartResult> =>
    ipcRenderer.invoke('anonymize:start', options) as Promise<AnonymizeStartResult>,
  cancelAnonymize: (jobId: string): Promise<boolean> =>
    ipcRenderer.invoke('anonymize:cancel', jobId) as Promise<boolean>,
  onAnonymizeEvent: (callback: (payload: AnonymizeEventPayload) => void) => {
    const handler = (_event: IpcRendererEvent, payload: AnonymizeEventPayload) => callback(payload);
    ipcRenderer.on('anonymize:event', handler);
    return () => ipcRenderer.removeListener('anonymize:event', handler);
  },
  startRestore: (options: RestoreStartOptions): Promise<RestoreStartResult> =>
    ipcRenderer.invoke('restore:start', options) as Promise<RestoreStartResult>,
  cancelRestore: (jobId: string): Promise<boolean> =>
    ipcRenderer.invoke('restore:cancel', jobId) as Promise<boolean>,
  onRestoreEvent: (callback: (payload: AnonymizeEventPayload) => void) => {
    const handler = (_event: IpcRendererEvent, payload: AnonymizeEventPayload) => callback(payload);
    ipcRenderer.on('restore:event', handler);
    return () => ipcRenderer.removeListener('restore:event', handler);
  }
};

contextBridge.exposeInMainWorld('electronAPI', api);

export type ElectronApi = typeof api;
