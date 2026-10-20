import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const asar = require('./tools/node_modules/@electron/asar/lib/asar.js');
const [base, output, stage, overlay, report] = process.argv.slice(2);
if (![base, output, stage, overlay, report].every(Boolean)) {
  throw new Error('usage: patch.mjs base.asar output.asar stage overlay report.json');
}
const requiredRuntime = [
  'mmd/FASHION_ITEM_CONF.json',
  'mmd/HEADWEAR_HAIR_CONF.json',
  'mmd/HEADWEAR_TYPE_CONF.json',
  'mmd/HEADWEAR_OFFSET_CONF.json',
  'mmd/BAGWEAR_OFFSET_CONF.json',
  'mmd/ITEM_TRANS_CONF.json',
  'mmd/native-clothing-physics.json',
  'mmd/expression-v1/PC1/SKM_PC1.glb',
  'mmd/expression-v1/PC2/SKM_PC2.glb',
  'mmd/eye-expression-v1/PC1',
  'mmd/eye-expression-v1/PC2',
  'public/chroma-data.json',
  'public/chroma-assets',
  'public/chroma-icons',
];
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const walk = (dir, baseDir = dir) => fs.readdirSync(dir, { withFileTypes: true })
  .flatMap(entry => entry.isDirectory()
    ? walk(path.join(dir, entry.name), baseDir)
    : [path.relative(baseDir, path.join(dir, entry.name)).replaceAll('\\', '/')]);

if (fs.existsSync(stage) && fs.readdirSync(stage).length) {
  throw new Error(`Stage must be empty: ${stage}`);
}
fs.mkdirSync(stage, { recursive: true });
asar.extractAll(base, stage);
const missing = requiredRuntime.filter(rel => !fs.existsSync(path.join(stage, rel)));
if (missing.length) throw new Error(`Base package lacks runtime assets: ${missing.join(', ')}`);

const overlayFiles = walk(overlay);
for (const rel of overlayFiles) {
  const target = path.join(stage, rel);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(path.join(overlay, rel), target);
}
fs.mkdirSync(path.dirname(output), { recursive: true });
await asar.createPackageWithOptions(stage, output, {
  globOptions: { ignore: ['**/__pycache__/**'] },
});

const check = `${stage}.readback`;
if (fs.existsSync(check) && fs.readdirSync(check).length) {
  throw new Error(`Readback directory must be empty: ${check}`);
}
fs.mkdirSync(check, { recursive: true });
asar.extractAll(output, check);
for (const rel of overlayFiles) {
  if (sha(path.join(overlay, rel)) !== sha(path.join(check, rel))) {
    throw new Error(`Readback mismatch: ${rel}`);
  }
}
for (const rel of requiredRuntime) {
  if (!fs.existsSync(path.join(check, rel))) throw new Error(`Runtime asset lost: ${rel}`);
}
const result = {
  base_asar: path.resolve(base),
  base_sha256: sha(base),
  output_asar: path.resolve(output),
  output_sha256: sha(output),
  overlay_files: overlayFiles,
  runtime_assets_preserved: requiredRuntime,
  readback_verified: true,
  package_contains_game_files: false,
  note: 'This generated ASAR is local and inherits runtime assets from the user base package; it is not part of the code-only release ZIP.',
};
fs.writeFileSync(report, JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
