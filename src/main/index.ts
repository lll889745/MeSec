import { app, BrowserWindow, ipcMain, shell } from 'electron';
import { join } from 'path';
import { release } from 'os';

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

ipcMain.handle('ping', async () => {
  return 'pong';
});
