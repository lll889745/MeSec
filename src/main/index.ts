import { app, BrowserWindow, ipcMain, shell, webContents } from 'electron';
import { ChildProcess, spawn } from 'child_process';
import { randomUUID } from 'crypto';
import { existsSync, mkdirSync } from 'fs';
import { basename, dirname, extname, join } from 'path';
import { cpus, release } from 'os';

// Disable GPU acceleration on Windows 7 to avoid issues with transparency APIs.
if (release().startsWith('6.1')) {
  app.disableHardwareAcceleration();
}

// Enable single instance lock to avoid duplicate background processes.
if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

const isDevelopment = !app.isPackaged;

type JobChannel = 'anonymize' | 'restore';

type AnonymizeStartOptions = {
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
  workerCount?: number;
};

type RestoreStartOptions = {
  anonymizedPath: string;
  dataPackPath: string;
  outputPath?: string;
  aesKey: string;
  hmacKey?: string;
  pythonPath?: string;
};

type RunningJob = {
  process?: ChildProcess;
  service?: 'anonymize';
  webContentsId: number;
  channel: JobChannel;
};

const runningJobs = new Map<string, RunningJob>();

type ServiceJob = {
  webContentsId: number;
};

let anonymizeService: ChildProcess | null = null;
let anonymizeServiceStdoutBuffer = '';
const anonymizeServiceJobs = new Map<string, ServiceJob>();

function getPythonExecutable(explicit?: string): string {
  if (explicit && explicit.trim().length > 0) {
    return explicit;
  }
  if (process.env.MESEC_PYTHON && process.env.MESEC_PYTHON.trim().length > 0) {
    return process.env.MESEC_PYTHON;
  }
  if (process.platform === 'win32') {
    return 'python';
  }
  return 'python3';
}

function resolveScriptPath(scriptName: string): string {
  const appPath = app.getAppPath();
  const candidate = join(appPath, 'scripts', scriptName);
  if (existsSync(candidate)) {
    return candidate;
  }
  const cwdCandidate = join(process.cwd(), 'scripts', scriptName);
  if (existsSync(cwdCandidate)) {
    return cwdCandidate;
  }
  return candidate;
}

function ensureParentDir(path: string): void {
  const dir = dirname(path);
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
}

function handleServicePayload(payload: Record<string, unknown>): void {
  const event = String(payload.event ?? '');
  if (!event) {
    return;
  }
  if (event === 'service_error') {
    console.warn('[anonymize-service]', payload.message);
    return;
  }
  const jobId = typeof payload.jobId === 'string' ? payload.jobId : undefined;
  if (!jobId) {
    return;
  }
  const jobEntry = anonymizeServiceJobs.get(jobId);
  const runningJob = runningJobs.get(jobId);
  if (!jobEntry || !runningJob) {
    return;
  }
  sendJobEvent(jobEntry.webContentsId, runningJob.channel, payload);
  if (event === 'exit') {
    anonymizeServiceJobs.delete(jobId);
    runningJobs.delete(jobId);
  }
}

function ensureAnonymizeService(pythonExecutable: string, pythonEnv: NodeJS.ProcessEnv): ChildProcess {
  if (anonymizeService && !anonymizeService.killed) {
    return anonymizeService;
  }

  const servicePath = resolveScriptPath('anonymize_service.py');
  const child = spawn(pythonExecutable, [servicePath], {
    cwd: dirname(servicePath),
    env: pythonEnv,
    stdio: ['pipe', 'pipe', 'pipe']
  });

  anonymizeService = child;
  anonymizeServiceStdoutBuffer = '';

  if (child.stdout) {
    child.stdout.setEncoding('utf-8');
    child.stdout.on('data', (chunk: string) => {
      anonymizeServiceStdoutBuffer += chunk;
      const parts = anonymizeServiceStdoutBuffer.split(/\r?\n/);
      anonymizeServiceStdoutBuffer = parts.pop() ?? '';
      for (const part of parts) {
        const line = part.trim();
        if (!line) {
          continue;
        }
        try {
          const payload = JSON.parse(line) as Record<string, unknown>;
          handleServicePayload(payload);
        } catch (error) {
          console.warn('[anonymize-service] Failed to parse line', line, error);
        }
      }
    });
  }

  if (child.stderr) {
    child.stderr.setEncoding('utf-8');
    child.stderr.on('data', (chunk: string) => {
      const message = chunk.toString().trim();
      if (message) {
        console.warn('[anonymize-service stderr]', message);
      }
    });
  }

  child.on('exit', (code, signal) => {
    anonymizeService = null;
    anonymizeServiceStdoutBuffer = '';
    if (anonymizeServiceJobs.size > 0) {
      for (const [jobId, job] of anonymizeServiceJobs.entries()) {
        sendJobEvent(job.webContentsId, 'anonymize', {
          jobId,
          event: 'error',
          message: `匿名服务中断，退出码 ${code ?? '未知'}`
        });
        sendJobEvent(job.webContentsId, 'anonymize', {
          jobId,
          event: 'exit',
          code,
          signal
        });
        runningJobs.delete(jobId);
      }
      anonymizeServiceJobs.clear();
    }
  });

  return child;
}

function sendServiceCommand(command: Record<string, unknown>): void {
  if (!anonymizeService || !anonymizeService.stdin) {
    throw new Error('Anonymization service is not running');
  }
  anonymizeService.stdin.write(`${JSON.stringify(command)}\n`);
}

function sendJobEvent(webContentsId: number, channel: JobChannel, payload: Record<string, unknown>): void {
  const target = webContents.fromId(webContentsId);
  if (!target || target.isDestroyed()) {
    return;
  }
  target.send(`${channel}:event`, payload);
}

async function createWindow(): Promise<void> {
  const browserWindow = new BrowserWindow({
    title: '可逆视频匿名化工具',
    width: 1200,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#121212',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  browserWindow.on('ready-to-show', () => {
    browserWindow.show();
    if (isDevelopment) {
      browserWindow.webContents.openDevTools({ mode: 'detach' });
    }
  });

  if (isDevelopment && process.env.VITE_DEV_SERVER_URL) {
    // In typical electron-vite dev runs this env var is injected. Use it when available.
    await browserWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    // If the dev server URL isn't injected for some environments, fall back to the
    // known dev server address (Vite default). This avoids trying to load the
    // missing `dist/index.html` during development.
    if (isDevelopment) {
      const fallbackDevUrl = process.env.VITE_DEV_SERVER_URL ?? 'http://localhost:5173';
      console.log('[main] VITE_DEV_SERVER_URL not set, falling back to', fallbackDevUrl);
      try {
        await browserWindow.loadURL(fallbackDevUrl);
        return;
      } catch (err) {
        console.error('[main] Failed to load dev server URL fallback', err);
      }
    }

    const rendererIndex = join(__dirname, '../../dist/index.html');
    await browserWindow.loadFile(rendererIndex);
  }

  browserWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url).catch((error) => console.error('Failed to open url in browser', error));
    return { action: 'deny' };
  });
}

app.whenReady().then(() => {
  createWindow().catch((error) => {
    console.error('Failed to create main window', error);
    app.quit();
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow().catch((error) => console.error('Failed to recreate window', error));
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  if (anonymizeService) {
    try {
      sendServiceCommand({ type: 'shutdown' });
    } catch (error) {
      console.warn('[main] Failed to send shutdown to anonymize service', error);
    }
    try {
      anonymizeService.kill();
    } catch (error) {
      console.warn('[main] Failed to terminate anonymize service', error);
    }
    anonymizeService = null;
    anonymizeServiceJobs.clear();
  }

  for (const job of runningJobs.values()) {
    if (job.process) {
      try {
        job.process.kill();
      } catch (error) {
        console.warn('[main] Failed to terminate child process', error);
      }
    }
  }
  runningJobs.clear();
});

ipcMain.handle('anonymize:start', async (event, options: AnonymizeStartOptions) => {
  if (!options || !options.inputPath) {
    throw new Error('缺少输入视频路径');
  }

  const inputPath = options.inputPath;
  if (!existsSync(inputPath)) {
    throw new Error(`输入视频不存在: ${inputPath}`);
  }

  const scriptPath = resolveScriptPath('anonymize_video.py');
  const pythonExecutable = getPythonExecutable(options.pythonPath);

  const inputDir = dirname(inputPath);
  const baseName = basename(inputPath, extname(inputPath));
  const outputPath = options.outputPath ?? join(inputDir, `${baseName}_anonymized.mp4`);
  const dataPackPath = options.dataPackPath ?? join(inputDir, `${baseName}_anonymized_encrypted_data.pack`);

  ensureParentDir(outputPath);
  ensureParentDir(dataPackPath);

  const pythonEnv = {
    ...process.env,
    PYTHONIOENCODING: 'utf-8'
  };

  const jobId = randomUUID();
  const webContentsId = event.sender.id;
  const manualRoisPayload = options.manualRois?.map((roi) =>
    roi.map((value) => Math.round(Number(value)))
  ) as Array<[number, number, number, number]> | undefined;

  const cpuCount = cpus().length || 1;
  const suggestedWorkers = options.disableDetection ? 1 : Math.min(2, Math.max(1, cpuCount - 1));
  const workerCount = Math.max(1, options.workerCount ?? suggestedWorkers);

  try {
    ensureAnonymizeService(pythonExecutable, pythonEnv);
  } catch (error) {
    throw new Error(`无法启动匿名服务: ${(error as Error).message}`);
  }

  const payload: Record<string, unknown> = {
    inputPath,
    outputPath,
    dataPackPath,
    device: options.device ?? 'auto',
    workerCount,
    disableDetection: Boolean(options.disableDetection)
  };

  if (options.modelPath) {
    payload.modelPath = options.modelPath;
  }
  if (typeof options.classes !== 'undefined') {
    payload.classes = options.classes;
  }
  if (manualRoisPayload && manualRoisPayload.length > 0) {
    payload.manualRois = manualRoisPayload;
  }
  if (options.aesKey) {
    payload.aesKey = options.aesKey;
  }
  if (options.hmacKey) {
    payload.hmacKey = options.hmacKey;
  }
  if (options.style) {
    payload.style = options.style;
  }

  try {
    sendServiceCommand({ type: 'start', jobId, payload });
  } catch (error) {
    throw new Error(`匿名服务请求失败: ${(error as Error).message}`);
  }

  const channel: JobChannel = 'anonymize';
  runningJobs.set(jobId, { service: 'anonymize', webContentsId, channel });
  anonymizeServiceJobs.set(jobId, { webContentsId });

  return {
    jobId,
    outputPath,
    dataPackPath
  };
});

ipcMain.handle('anonymize:cancel', async (_event, jobId: string) => {
  const job = runningJobs.get(jobId);
  if (!job) {
    return false;
  }
  if (job.service === 'anonymize') {
    try {
      sendServiceCommand({ type: 'cancel', jobId });
    } catch (error) {
      console.warn('[main] Failed to cancel anonymize job via service', error);
      sendJobEvent(job.webContentsId, job.channel, {
        jobId,
        event: 'error',
        message: '无法取消匿名任务'
      });
      return false;
    }
    return true;
  }

  if (job.process) {
    job.process.kill();
    runningJobs.delete(jobId);
    sendJobEvent(job.webContentsId, job.channel, { jobId, event: 'cancelled' });
    return true;
  }
  return true;
});

ipcMain.handle('restore:start', async (event, options: RestoreStartOptions) => {
  if (!options || !options.anonymizedPath || !options.dataPackPath || !options.aesKey) {
    throw new Error('缺少恢复所需的参数');
  }

  const anonymizedPath = options.anonymizedPath;
  const dataPackPath = options.dataPackPath;
  if (!existsSync(anonymizedPath)) {
    throw new Error(`匿名视频不存在: ${anonymizedPath}`);
  }
  if (!existsSync(dataPackPath)) {
    throw new Error(`数据包不存在: ${dataPackPath}`);
  }

  const scriptPath = resolveScriptPath('restore_video.py');
  const pythonExecutable = getPythonExecutable(options.pythonPath);

  const outputPath = options.outputPath
    ? options.outputPath
    : join(dirname(anonymizedPath), `${basename(anonymizedPath, extname(anonymizedPath))}_restored.mp4`);

  ensureParentDir(outputPath);

  const args: string[] = [
    scriptPath,
    '--anonymized-video',
    anonymizedPath,
    '--data-pack',
    dataPackPath,
    '--output',
    outputPath,
    '--key',
    options.aesKey,
    '--json-progress'
  ];

  if (options.hmacKey) {
    args.push('--hmac-key', options.hmacKey);
  }

  const pythonEnv = {
    ...process.env,
    PYTHONIOENCODING: 'utf-8'
  };

  const jobId = randomUUID();
  const channel: JobChannel = 'restore';
  const webContentsId = event.sender.id;

  const child = spawn(pythonExecutable, args, {
    cwd: dirname(scriptPath),
    env: pythonEnv,
    stdio: ['ignore', 'pipe', 'pipe']
  });

  runningJobs.set(jobId, { process: child, webContentsId, channel });

  sendJobEvent(webContentsId, channel, {
    jobId,
    event: 'started',
    anonymized: anonymizedPath,
    data_pack: dataPackPath,
    output: outputPath
  });

  let stdoutBuffer = '';

  if (child.stdout) {
    child.stdout.setEncoding('utf-8');
    child.stdout.on('data', (chunk: string) => {
      stdoutBuffer += chunk;
      const parts = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = parts.pop() ?? '';
      for (const part of parts) {
        const line = part.trim();
        if (!line) {
          continue;
        }
        try {
          const payload = JSON.parse(line) as Record<string, unknown>;
          sendJobEvent(webContentsId, channel, { jobId, ...payload });
        } catch (error) {
          console.warn('[main] Failed to parse restore progress line', line, error);
          sendJobEvent(webContentsId, channel, { jobId, event: 'log', message: line });
        }
      }
    });
  }

  if (child.stderr) {
    child.stderr.setEncoding('utf-8');
    child.stderr.on('data', (chunk: string) => {
      const message = chunk.toString().trim();
      if (message) {
        sendJobEvent(webContentsId, channel, { jobId, event: 'log', stream: 'stderr', message });
      }
    });
  }

  child.on('error', (error) => {
    sendJobEvent(webContentsId, channel, { jobId, event: 'error', message: error.message });
  });

  child.on('close', (code, signal) => {
    runningJobs.delete(jobId);

    if (stdoutBuffer.trim().length > 0) {
      try {
        const payload = JSON.parse(stdoutBuffer.trim()) as Record<string, unknown>;
        sendJobEvent(webContentsId, channel, { jobId, ...payload });
      } catch (error) {
        sendJobEvent(webContentsId, channel, { jobId, event: 'log', message: stdoutBuffer.trim() });
      }
    }

    sendJobEvent(webContentsId, channel, { jobId, event: 'exit', code, signal });
  });

  return {
    jobId,
    outputPath
  };
});

ipcMain.handle('restore:cancel', async (_event, jobId: string) => {
  const job = runningJobs.get(jobId);
  if (!job) {
    return false;
  }
  if (job.process) {
    job.process.kill();
    runningJobs.delete(jobId);
    sendJobEvent(job.webContentsId, job.channel, { jobId, event: 'cancelled' });
    return true;
  }
  return false;
});

ipcMain.handle('ping', async () => {
  return 'pong';
});
