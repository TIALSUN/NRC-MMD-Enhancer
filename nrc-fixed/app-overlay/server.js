const express = require('express');
const path = require('path');
const fs = require('fs');
const os = require('os');
const crypto = require('crypto');
const { spawn } = require('child_process');

const DEFAULT_CONFIG_PATH = path.join(__dirname, 'config.json');
const DEFAULT_PUBLIC_ROOT = path.join(__dirname, 'public');
const DEFAULT_PROJECT_ROOT = __dirname;
const NAME_UNSAFE = /[\\/:*?"<>|\s]+/g;
// 动态炫彩：未烘焙底纹的衍生配色沿用预览器 getChromaPattern 的默认底纹。
const DEFAULT_CHROMA_PATTERN = '/chroma-assets/Tex_PetGlassy_007_D.png';

// MMD 导出：Blender 可执行文件与输出目录，写进用户配置后由设置界面修改。
const MMD_DEFAULTS = {
  mmdBlender: 'D:\\Blender_\\blender.exe',
  mmdOutDir: path.join(os.homedir(), 'Documents', 'NRC-MMD'),
  // 带表情（morph）的模型库：用它当身体就能导出带 39 个表情的 PMX；
  // 留空则用 modelRoot（那套没有 morph，导出后表情为空）。
  mmdMorphRoot: '',
  // 骨名体系：miku = 左腕/左ひじ（Miku 标准）；suffix = 腕.L/ひじ.L
  mmdNaming: 'miku',
  // 刚体与关节：on = 裙摆/头发/背包带物理（默认）；off = 只有骨骼动画
  mmdPhysics: 'on',
  mmdNativeExpressions: 'on',
};
// 打进 asar 的导出工具：运行时释放到 <输出目录>\.mmd-tools 再交给 Blender。
const MMD_TOOL_FILES = [
  ['mmd/roco-to-mmd.py', 'roco-to-mmd.py'],
  ['mmd/native_physics.py', 'native_physics.py'],
  ['mmd/native-clothing-physics.json', 'native-clothing-physics.json'],
  ['mmd/dynamic-chroma.py', 'dynamic-chroma.py'],
  ['mmd/bone-map.csv', 'bone-map.csv'],
  ['mmd/FASHION_ITEM_CONF.json', 'FASHION_ITEM_CONF.json'],
  ['mmd/ITEM_TRANS_CONF.json', 'ITEM_TRANS_CONF.json'],
  ['mmd/BAGWEAR_OFFSET_CONF.json', 'BAGWEAR_OFFSET_CONF.json'],
  ...['HEADWEAR_TYPE_CONF', 'HEADWEAR_HAIR_CONF', 'HEADWEAR_OFFSET_CONF'].map(name => [`mmd/${name}.json`, `${name}.json`]),
  ...['PC1', 'PC2'].flatMap(character => {
    const base = character === 'PC1' ? 10400001 : 20400001;
    const parts = Array.from({length: 15}, (_, i) => `SKM_${character}_Et_${base + i * 100}`);
    parts.push(`SKM_${character}_Fe_${character === 'PC1' ? 10200001 : 20200001}`);
    for (const slot of ['Hr', 'Hr_Ht']) parts.push(`SKM_${character}_${slot}_${character === 'PC1' ? 10100001 : 20100001}`);
    return parts.flatMap(name => ['glb', 'json'].map(ext => [`mmd/eye-expression-v1/${character}/${name}.${ext}`, `eye-expression-v1/${character}/${name}.${ext}`]));
  }),
  ...['PC1', 'PC2'].flatMap(character => [
    [`mmd/expression-v1/${character}/SKM_${character}.glb`, `expression-v1/${character}/SKM_${character}.glb`],
    [`mmd/expression-v1/${character}/manifest.json`, `expression-v1/${character}/manifest.json`],
  ]),
];

function loadConfig(configPath) {
  return JSON.parse(fs.readFileSync(configPath, 'utf8'));
}

function saveConfig(configPath, nextConfig) {
  fs.writeFileSync(configPath, `${JSON.stringify(nextConfig, null, 2)}\n`, 'utf8');
}

function pathExists(value) {
  return typeof value === 'string' && fs.existsSync(value);
}

function safeJoin(root, relativePath) {
  const base = path.resolve(root || '');
  const target = path.resolve(base, relativePath || '');
  if (target !== base && !target.startsWith(base + path.sep)) return null;
  return target;
}

const DEFAULT_PREFS_PATH = path.join(require('os').homedir(), '.nrc-closet-prefs.json');

function loadPrefs(prefsPath) {
  try { return JSON.parse(fs.readFileSync(prefsPath, 'utf8')); } catch { return {}; }
}

function savePrefs(prefsPath, prefs) {
  fs.writeFileSync(prefsPath, `${JSON.stringify(prefs, null, 2)}\n`, 'utf8');
}

function summarizeExportBones(report) {
  if (!report) return null;
  const clothing = Array.isArray(report.clothing_bones) ? report.clothing_bones : [];
  const declared = report.clothing_bones_summary || {};
  const weighted = Array.isArray(declared.weighted)
    ? declared.weighted
    : [...new Set(clothing.flatMap(entry => entry.weighted_bones || []))];
  const added = Array.isArray(declared.added)
    ? declared.added
    : [...new Set(clothing.flatMap(entry => entry.added_bones || []))];
  return {
    total: Number.isInteger(report.bones_after_rename) ? report.bones_after_rename : null,
    weightedPreserved: Array.isArray(report.weighted_bones_preserved)
      ? report.weighted_bones_preserved.length
      : null,
    clothingWeighted: [...weighted].sort(),
    clothingAdded: [...added].sort(),
  };
}

function createApp(options = {}) {
  const configPath = options.configPath || DEFAULT_CONFIG_PATH;
  const prefsPath  = options.prefsPath  || DEFAULT_PREFS_PATH;
  const publicRoot = options.publicRoot || DEFAULT_PUBLIC_ROOT;
  const projectRoot = options.projectRoot || DEFAULT_PROJECT_ROOT;
  const spawnImpl = options.spawn || spawn;
  let config = loadConfig(configPath);
  for (const [key, value] of Object.entries(MMD_DEFAULTS)) {
    if (typeof config[key] !== 'string' || !config[key]) config[key] = value;
  }
  const app = express();

  app.locals.nrcConfig = config;
  app.locals.nrcConfigPath = configPath;

  let textureIndexCache = null;
  async function getTextureIndex() {
    const root = path.resolve(config.modelRoot || '');
    if (textureIndexCache?.root === root && Date.now() - textureIndexCache.time < 60000) return textureIndexCache.promise;
    const promise = (async () => {
      const index = new Map();
      async function walk(dir) {
        let entries;
        try { entries = await fs.promises.readdir(dir, { withFileTypes: true }); } catch { return; }
        await Promise.all(entries.map(async entry => {
          const file = path.join(dir, entry.name);
          if (entry.isDirectory()) return walk(file);
          if (!entry.isFile() || !entry.name.toLowerCase().endsWith('.png')) return;
          const key = entry.name.toLowerCase();
          if (!index.has(key)) index.set(key, []);
          index.get(key).push(file);
        }));
      }
      if (config.modelRoot) await walk(root);
      return index;
    })();
    textureIndexCache = { root, time: Date.now(), promise };
    return promise;
  }

  app.get('/model-texture/:name', async (req, res) => {
    if (!/^[a-z0-9_-]+\.png$/i.test(req.params.name)) return res.status(400).send('Invalid texture name');
    try {
      const paths = (await getTextureIndex()).get(req.params.name.toLowerCase()) || [];
      if (!paths.length) return res.status(404).send('Texture not found');
      if (paths.length > 1) {
        const crypto = require('crypto');
        const hashes = await Promise.all(paths.map(async file => crypto.createHash('sha256')
          .update(await fs.promises.readFile(file)).digest('hex')));
        if (new Set(hashes).size > 1) return res.status(409).send('Ambiguous texture name');
      }
      res.sendFile(paths[0]);
    } catch { res.status(500).send('Texture lookup failed'); }
  });

  app.use(express.json({ limit: '128kb' }));

  // Static frontend and local three.js for both Web and Electron builds.
  app.use('/vendor/three', express.static(path.join(projectRoot, 'node_modules', 'three')));
  app.use(express.static(publicRoot));

  function configStatus() {
    return {
      dataRoot: pathExists(config.dataRoot),
      iconRoot: pathExists(config.iconRoot),
      suitsRoot: pathExists(config.suitsRoot),
      framesRoot: pathExists(config.framesRoot),
      modelRoot: pathExists(config.modelRoot),
      mmdBlender: pathExists(config.mmdBlender),
      mmdOutDir: pathExists(config.mmdOutDir),
      mmdMorphRoot: !config.mmdMorphRoot || pathExists(config.mmdMorphRoot),
    };
  }

  // ── MMD 导出 ────────────────────────────────────────────────
  const mmdJobs = new Map();
  let mmdActiveJobId = null;

  function prepareMmdTools(outDir) {
    const toolsDir = path.join(outDir, '.mmd-tools');
    fs.mkdirSync(toolsDir, { recursive: true });
    for (const [source, name] of MMD_TOOL_FILES) {
      const data = fs.readFileSync(path.join(__dirname, source));
      const target = path.join(toolsDir, name);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      let same = false;
      try { same = fs.readFileSync(target).equals(data); } catch { same = false; }
      if (!same) fs.writeFileSync(target, data);
    }
    return toolsDir;
  }

  function buildMmdArgs(request, pmxPath, toolsDir) {
    const character = Number(request.gender) === 1 ? 'PC1' : 'PC2';
    const exportRoot = path.resolve(config.modelRoot || '');
    // 有带 morph 的库就用它当身体（导出的 PMX 带表情），服装部位与贴图仍取原库
    const morphRoot = config.mmdMorphRoot ? path.resolve(config.mmdMorphRoot) : '';
    const morphBody = morphRoot ? path.join(morphRoot, 'NRC', 'Content', 'ArtRes', 'AnimSequence', 'Human', 'PC', character, `SKM_${character}.glb`) : '';
    const useMorphBody = morphBody && fs.existsSync(morphBody);
    const nativeBody = path.join(toolsDir, 'expression-v1', character, `SKM_${character}.glb`);
    const nativeManifest = path.join(toolsDir, 'expression-v1', character, 'manifest.json');
    const useNative = config.mmdNativeExpressions !== 'off';
    if (useNative && (!fs.existsSync(nativeBody) || !fs.existsSync(nativeManifest))) throw new Error('原生表情 v1 资源不完整');
    const bodyPath = useNative ? nativeBody : useMorphBody ? morphBody : path.join(exportRoot, character, `SKM_${character}.gltf`);
    const args = [
      '-b', '-noaudio', '--factory-startup', '--python-exit-code', '2',
      '--python', path.join(toolsDir, 'roco-to-mmd.py'), '--',
      '--body', bodyPath,
      '--out', pmxPath,
      '--mapping', path.join(toolsDir, 'bone-map.csv'),
      '--item-conf', path.join(toolsDir, 'FASHION_ITEM_CONF.json'),
      '--texture-root', exportRoot,
    ];
    if (useNative || useMorphBody) args.push('--part-root', exportRoot);
    if (useNative) args.push('--native-expressions-manifest', nativeManifest, '--no-eye-socket-fix');
    if (request.eyeAvatarId != null) args.push('--eye-avatar-id', String(request.eyeAvatarId));
    args.push('--naming', config.mmdNaming === 'suffix' ? 'suffix' : 'miku');
    for (const [field, flag] of [['hairColor', '--hair-color'], ['browColor', '--brow-color']]) {
      const color = Number(request[field] ?? 1);
      args.push(flag, String(Number.isInteger(color) && color >= 1 && color <= 5 ? color : 1));
    }
    // 沙龙选项：发型造型 / 瞳孔 / 肤色 / 面妆。转换器按 avatar/贴图编号解析，缺资源时忽略或报错。
    for (const [field, flag] of [
      ['hairAvatarId', '--hair-avatar-id'],
      ['pupilAvatarId', '--pupil-texture-id'],
      ['skinAvatarId', '--skin-avatar-id'],
      ['makeupAvatarId', '--makeup-avatar-id'],
    ]) {
      const value = Number(request[field]);
      if (Number.isInteger(value) && value > 0) args.push(flag, String(value));
    }
    if (request.dynamicRecipe) args.push('--dynamic-chroma', request.dynamicRecipe);
    if (config.mmdPhysics !== 'off') args.push('--physics');
    for (const item of request.items) args.push('--item', String(item));
    return args;
  }

  function startMmdJob(request) {
    const body = request || {};
    const fail = (message, code) => { const error = new Error(message); error.statusCode = code; throw error; };
    if (mmdActiveJobId && mmdJobs.get(mmdActiveJobId)?.status === 'running') fail('已有一个导出任务正在进行', 409);
    // 不选服装也允许导出：没有可替换的物品时按各槽位默认款装配
    const items = (Array.isArray(body.items) ? body.items : []).map(String).filter(Boolean);
    const gender = Number(body.gender);
    if (gender !== 1 && gender !== 2) fail('性别必须是 1（男）或 2（女）', 400);
    if (body.eyeAvatarId != null) {
      const index = (Number(body.eyeAvatarId) - (gender * 10000000 + 3000000)) / 1000;
      if (!Number.isInteger(index) || index < 0 || index >= 15) fail('眼型与当前角色不匹配，或眼型资源不受支持', 400);
    }
    if (!pathExists(config.mmdBlender)) fail(`找不到 Blender：${config.mmdBlender}`, 400);
    const exportRoot = path.resolve(config.modelRoot || '');
    if (!pathExists(exportRoot)) fail(`模型目录不存在：${exportRoot}`, 400);

    let dynamicPreset = null;
    if (body.dynamicChroma) {
      const data = JSON.parse(fs.readFileSync(path.join(publicRoot, 'chroma-data.json'), 'utf8'));
      const selected = data.presets.find(p => String(p.id) === String(body.chromaPresetId));
      if (!selected) fail('请先选择有效的炫彩配色', 400);
      dynamicPreset = JSON.parse(JSON.stringify(selected));
      if (body.chromaPatternTexture && !selected.source) {
        const pattern = data.basic_patterns.find(p => p.texture === body.chromaPatternTexture);
        if (!pattern) fail('炫彩花纹无效', 400);
        dynamicPreset.ornament = {...dynamicPreset.ornament, texture: pattern.texture, tiling: pattern.tiling};
      }
    }
    const outDir = path.resolve(config.mmdOutDir);
    fs.mkdirSync(outDir, { recursive: true });
    const toolsDir = prepareMmdTools(outDir);
    const character = gender === 1 ? 'PC1' : 'PC2';
    // 名字同时用于文件夹与 PMX 文件名：限制长度，避免 Blender 文件浏览器选不中/路径过长。
    const name = String(body.name || `NRC-MMD-${Date.now()}`).replace(NAME_UNSAFE, '_').replace(/_+$/g, '').slice(0, 60) || `NRC-MMD-${Date.now()}`;
    // 每次导出单独一个文件夹，PMX 与它的贴图（Blender 会写在同级的 Tex\ 下）放在一起
    let exportDir = path.join(outDir, name);
    for (let suffix = 2; fs.existsSync(exportDir); suffix++) exportDir = path.join(outDir, `${name}-${suffix}`);
    fs.mkdirSync(exportDir, { recursive: true });
    const pmxPath = path.join(exportDir, `${name}.pmx`);
    const job = {
      id: crypto.randomUUID(),
      status: 'running',
      message: null,
      log: '',
      pmx: pmxPath,
      exportDir,
      character,
      items,
      startedAt: Date.now(),
      result: null,
    };

    let dynamicRecipe;
    if (dynamicPreset) {
      const data = JSON.parse(fs.readFileSync(path.join(publicRoot, 'chroma-data.json'), 'utf8'));
      const assets = path.join(exportDir, 'Chroma'); fs.mkdirSync(assets, {recursive:true});
      const copy = url => {
        const source = safeJoin(publicRoot, String(url).replace(/^\//, ''));
        if (!source || !fs.existsSync(source)) fail('炫彩纹理缺失',400);
        const target = path.join(assets,path.basename(source)); fs.copyFileSync(source,target);
        return path.relative(exportDir,target).replaceAll('\\','/');
      };
      dynamicPreset.pattern = copy(dynamicPreset.pattern || DEFAULT_CHROMA_PATTERN);
      if (dynamicPreset.ornament?.texture) dynamicPreset.ornament.texture = copy(dynamicPreset.ornament.texture);
      dynamicRecipe = path.join(exportDir, '炫彩参数.json');
      fs.writeFileSync(dynamicRecipe,JSON.stringify({version:1,preset:dynamicPreset,materials:data.materials,model_root:exportRoot},null,2));
    }
    mmdJobs.set(job.id, job);
    while (mmdJobs.size > 8) mmdJobs.delete(mmdJobs.keys().next().value);
    mmdActiveJobId = job.id;
    const child = spawnImpl(config.mmdBlender, buildMmdArgs({ ...body, items, name, dynamicRecipe }, pmxPath, toolsDir),
      { windowsHide: true });
    const append = chunk => { job.log = (job.log + String(chunk)).slice(-4000); };
    child.stdout?.on('data', append);
    child.stderr?.on('data', append);
    child.on('error', error => {
      job.status = 'error';
      job.message = `启动 Blender 失败：${error.message}`;
    });
    child.on('close', code => {
      if (job.status === 'error') return;
      const reportPath = pmxPath.replace(/\.pmx$/i, '.report.json');
      if (code === 0 && fs.existsSync(pmxPath) && (!dynamicRecipe || fs.existsSync(pmxPath.replace(/\.pmx$/i, '-动态炫彩.blend')))) {
        job.status = 'done';
        job.result = {pmx: pmxPath, blend: dynamicRecipe ? pmxPath.replace(/\.pmx$/i, '-动态炫彩.blend') : undefined, report: null};
        try {
          job.result.report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
          job.result.boneSummary = summarizeExportBones(job.result.report);
        }
        catch { /* Artifact paths remain usable even if the optional report cannot be read. */ }
      } else {
        job.status = 'error';
        const detail = String(job.log || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean).slice(-1)[0] || '';
        job.message = code === 0 && dynamicRecipe
          ? '动态炫彩场景未生成，请查看导出日志'
          : `Blender 退出码 ${code}${detail ? '：' + detail.slice(-160) : ''}`;
      }
    });
    return job;
  }

  app.post('/api/mmd/export', (req, res) => {
    try {
      const job = startMmdJob(req.body);
      res.json({ jobId: job.id, status: job.status, pmx: job.pmx });
    } catch (error) {
      res.status(error.statusCode || 500).send(error.message);
    }
  });

  app.get('/api/mmd/export/:id', (req, res) => {
    const job = mmdJobs.get(req.params.id);
    if (!job) return res.status(404).send('未知的导出任务');
    res.json({
      id: job.id,
      status: job.status,
      message: job.message,
      pmx: job.pmx,
      exportDir: job.exportDir,
      result: job.result,
      log: job.log.slice(-1500),
    });
  });

  app.post('/api/mmd/reveal', (req, res) => {
    const target = String((req.body || {}).path || '');
    if (!target) return res.status(400).send('缺少 path');
    const dir = fs.existsSync(target) && fs.statSync(target).isDirectory() ? target : path.dirname(target);
    if (!fs.existsSync(dir)) return res.status(404).send('目录不存在');
    try {
      spawn('explorer.exe', [dir], { detached: true, windowsHide: false, stdio: 'ignore' }).unref();
    } catch (error) {
      return res.status(500).send(error.message);
    }
    res.json({ opened: dir });
  });

  function loadJson(filename) {
    const file = path.join(config.dataRoot, filename);
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  }

  function sendFile(res, filePath) {
    if (!fs.existsSync(filePath)) {
      return res.status(404).send('Not found');
    }
    res.sendFile(filePath);
  }

  app.get('/api/appearance-fit', (_req, res) => {
    const tables = {};
    for (const name of ['HEADWEAR_HAIR_CONF', 'HEADWEAR_TYPE_CONF', 'HEADWEAR_OFFSET_CONF', 'BAGWEAR_OFFSET_CONF', 'ITEM_TRANS_CONF']) {
      try { tables[name] = Object.values(loadJson(name + '.json').RocoDataRows || {}); }
      catch (error) { tables[name] = []; }
    }
    res.json(tables);
  });

  app.get('/api/tabs', (_req, res) => {
    const data = loadJson('CLOSET_TAB_CONF.json');
    res.json(data.RocoDataRows);
  });

  app.get('/api/items', (_req, res) => {
    const data = loadJson('FASHION_ITEM_CONF.json');
    res.json(data.RocoDataRows);
  });

  app.get('/api/suits', (_req, res) => {
    const data = loadJson('FASHION_SUITS_CONF.json');
    res.json(data.RocoDataRows);
  });

  app.get('/api/salon', (_req, res) => {
    const data = loadJson('SALON_ITEM_CONF.json');
    res.json(data.RocoDataRows);
  });

  app.get('/api/config', (_req, res) => {
    res.json({ ...config, status: configStatus() });
  });

  app.post('/api/config', (req, res) => {
    const allowed = ['dataRoot', 'iconRoot', 'suitsRoot', 'framesRoot', 'modelRoot', 'port',
      'mmdBlender', 'mmdOutDir', 'mmdMorphRoot', 'mmdNaming', 'mmdPhysics', 'mmdNativeExpressions'];
    const body = req.body || {};
    const next = { ...config };
    for (const key of allowed) {
      if (!(key in body)) continue;
      if (key === 'port') {
        const port = Number(body.port);
        if (Number.isInteger(port) && port > 0 && port < 65536) next.port = port;
      } else if (typeof body[key] === 'string') {
        next[key] = body[key].trim();
      }
    }
    config = next;
    app.locals.nrcConfig = config;
    saveConfig(configPath, config);
    res.json({ ...config, status: configStatus() });
  });

  app.get('/api/prefs', (_req, res) => {
    res.json(loadPrefs(prefsPath));
  });

  app.post('/api/prefs', (req, res) => {
    const current = loadPrefs(prefsPath);
    const next = { ...current, ...req.body };
    savePrefs(prefsPath, next);
    res.json(next);
  });

  app.use('/models', (req, res) => {
    let relativePath;
    try {
      relativePath = decodeURIComponent(req.path).replace(/^[/\\]+/, '');
    } catch {
      return res.status(400).send('Bad path');
    }
    const file = safeJoin(config.modelRoot, relativePath);
    if (!file) return res.status(400).send('Bad path');
    sendFile(res, file);
  });

  app.get('/assets/icon/:id', (req, res) => {
    sendFile(res, path.join(config.iconRoot, `${req.params.id}.png`));
  });

  app.get('/assets/suit/:name', (req, res) => {
    sendFile(res, path.join(config.suitsRoot, `${req.params.name}.png`));
  });

  app.get('/assets/frame/:name', (req, res) => {
    sendFile(res, path.join(config.framesRoot, `${req.params.name}.png`));
  });

  return app;
}

function startServer(options = {}) {
  const app = createApp(options);
  const port = options.port ?? app.locals.nrcConfig.port ?? 3000;
  const host = options.host || '127.0.0.1';

  return new Promise((resolve, reject) => {
    const server = app.listen(port, host, () => {
      const address = server.address();
      const actualPort = typeof address === 'object' && address ? address.port : port;
      resolve({
        app,
        server,
        port: actualPort,
        url: `http://${host}:${actualPort}`,
      });
    });
    server.on('error', reject);
  });
}

if (require.main === module) {
  startServer({ host: '0.0.0.0' })
    .then(({ url }) => {
      console.log(`NRC 服装预览工具已启动 -> ${url}`);
    })
    .catch(err => {
      console.error(err);
      process.exit(1);
    });
}

module.exports = {
  createApp,
  startServer,
};
