const { app, BrowserWindow } = require('electron');
const path = require('path');
const fs = require('fs');
const { startServer } = require('../server');

let serverHandle = null;
let mainWindow = null;

function getProjectRoot() {
  return app.getAppPath();
}

function ensureUserConfig(projectRoot) {
  const userConfigPath = path.join(app.getPath('userData'), 'config.json');
  if (!fs.existsSync(userConfigPath)) {
    const defaultConfigPath = path.join(projectRoot, 'config.json');
    fs.copyFileSync(defaultConfigPath, userConfigPath);
  }
  return userConfigPath;
}

async function createWindow() {
  const projectRoot = getProjectRoot();
  const configPath = ensureUserConfig(projectRoot);
  const prefsPath  = path.join(app.getPath('userData'), 'prefs.json');
  const publicRoot = path.join(projectRoot, 'public');

  serverHandle = await startServer({
    host: '127.0.0.1',
    configPath,
    prefsPath,
    publicRoot,
    projectRoot,
  }).catch(async error => {
    // 端口被占用时（比如误开了第二个实例）也要能把窗口打开，改用临时端口。
    console.warn('[main] 配置端口不可用，改用临时端口启动：', error.message);
    return startServer({ host: '127.0.0.1', configPath, prefsPath, publicRoot, projectRoot, port: 0 });
  });

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: 'NRC 服装预览工具',
    backgroundColor: '#13141a',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  await mainWindow.loadURL(serverHandle.url);
}

// 只允许一个实例：重复启动时把已有窗口唤到前台，避免两个实例抢同一个端口导致窗口空白。
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  app.whenReady().then(createWindow);
}

app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', () => {
  if (serverHandle?.server) serverHandle.server.close();
});
