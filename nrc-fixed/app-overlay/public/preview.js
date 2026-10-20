// ════════════════════════════════════════════════════════════
//  NRC 服装预览工具  —  preview.js  (Three.js 3D 模型预览)
// ════════════════════════════════════════════════════════════

import * as THREE from 'three';
import { getChromaMask, updateChromaUniforms, patchChromaShader, advanceChromaFlow } from './chroma-core.mjs';
import { chromaDataReady, getActiveChromaPreset } from './chroma-state.mjs';

const chromaUniforms = {
  nrcChromaFlowSpeed: { value: [0, 0] },
  nrcChromaFlowOffset: { value: [0, 0] },
  nrcChromaStickPhase: { value: 0 },
  nrcChromaStickTexture: { value: null },
  nrcChromaStickOffset: { value: [0, 0] },
  nrcChromaStickSpeed: { value: [0, 0] },
  nrcChromaStickTiling: { value: 4 },
  nrcChromaStickIntensity: { value: 0 },
  nrcChromaStickColors: { value: new Float32Array(12).fill(1) },
  nrcChromaSparklePhase: { value: 0 },
  nrcChromaSparkleIntensity: { value: 0 },
  nrcChromaSparkleDensity: { value: 0 },
  nrcChromaSparkleTiling: { value: 1 },
  nrcChromaSpecIntensity: { value: 0.35 },
  nrcChromaSpecPow: { value: 24 },
  nrcChromaEnabled: { value: 0 },
  nrcChromaPattern: { value: null },
  nrcChromaTiling: { value: 1 },
  nrcChromaColor1: { value: [1, 1, 1] },
  nrcChromaColor2: { value: [1, 1, 1] },
};
let lastChromaFrameTime = null;
import { GLTFLoader }    from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// Exact material modes recovered from local FModel exports; no inference from texture Alpha.
const MATERIAL_RENDER_RULES = {"mi_pc1_bg_11200501_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":11200501},"mi_pc1_bg_11202501_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":11202501},"mi_pc1_bg_11203501_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":11203501},"mi_pc1_bg_11210601_im":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":11210601},"mi_pc1_bg_11210901_im":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":11210901},"mi_pc1_bg_11210901_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":11210901},"mi_pc1_cup_1070250101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":1070250101},"mi_pc1_ps_1070370101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":1070370101},"mi_pc1_cup_1070660101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":1070660101},"mi_pc1_cup_1070760101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":1070760101},"mi_pc1_cup_1071050101_im":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":1071050101},"mi_pc1_cup_1071060101_im":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":1071060101},"mi_pc1_ps_1071080101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":1071080101},"mi_pc1_cup_1071090101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":1071090101},"mi_pc1_ps_1071100101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":1071100101},"mi_pc1_fi_12203801_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":12203801},"mi_pc1_fi_12203901_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":12203901},"mi_pc1_fi_12209101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":12209101},"mi_pc1_fi_12250001_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":12250001},"mi_pc1_fi_12250101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":12250101},"mi_pc1_hg_12709201_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Hg","id":12709201},"mi_pc1_hi_12105301_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Hi","id":12105301},"mi_pc1_hi_12110601_im":{"blendMode":2,"alphaTest":0.3333,"folder":"Hi","id":12110601},"mi_pc1_hi_12110901_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Hi","id":12110901},"mi_pc1_hi_12111001_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Hi","id":12111001},"mi_pc1_ht_11303901_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Ht","id":11303901},"mi_pc1_ht_11310801_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Ht","id":11310801},"mi_pc1_ht_11350001_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Ht","id":11350001},"mi_pc1_ht_11350201_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Ht","id":11350201},"mi_pc2_bg_21202501_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":21202501},"mi_pc2_bg_21203501_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":21203501},"mi_pc2_bg_21204901_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":21204901},"mi_pc2_bg_21205401_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":21205401},"mi_pc2_bg_21207701_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":21207701},"mi_pc2_bg_21209101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":21209101},"mi_pc2_bg_21210901_im":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":21210901},"mi_pc2_bg_21210901_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Bg","id":21210901},"mi_pc2_ps_2070250101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2070250101},"mi_pc2_cup_2070350101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2070350101},"mi_pc2_ps_2070370101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2070370101},"mi_pc2_cup_2070390101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2070390101},"mi_pc2_ps_2070530101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2070530101},"mi_pc2_ps_2070660101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2070660101},"mi_pc2_cup_2070760101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2070760101},"mi_pc2_cup_2070770101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2070770101},"mi_pc2_ps_2070910101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2070910101},"mi_pc2_cup_2071050101_im":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2071050101},"mi_pc2_cup_2071060101_im":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2071060101},"mi_pc2_cup_2071060101_op":{"blendMode":1,"alphaTest":0.3333,"folder":"Cup","id":2071060101},"mi_pc2_ps_2071080101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2071080101},"mi_pc2_cup_2071090101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2071090101},"mi_pc2_cup_2071100101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Cup","id":2071100101},"mi_pc2_fi_22201301_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":22201301},"mi_pc2_fi_22203801_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":22203801},"mi_pc2_fi_22203901_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":22203901},"mi_pc2_fi_22209101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":22209101},"mi_pc2_fi_22250001_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":22250001},"mi_pc2_fi_22250101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Fi","id":22250101},"mi_pc2_ge_up_20803701_op":{"blendMode":1,"alphaTest":0.3333,"folder":"Ge","id":20803701},"mi_pc2_hg_22709201_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Hg","id":22709201},"mi_pc2_hi_22109101_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Hi","id":22109101},"mi_pc2_hi_22110901_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Hi","id":22110901},"mi_pc2_hi_22111001_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Hi","id":22111001},"mi_pc2_hp_22807301_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Hp","id":22807301},"mi_pc2_ht_21303901_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Ht","id":21303901},"mi_pc2_ht_21350001_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Ht","id":21350001},"mi_pc2_ht_21350201_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Ht","id":21350201},"mi_pc2_se_21102501_op":{"blendMode":2,"alphaTest":0.3333,"folder":"Se","id":21102501},"mi_pc2_ps_2070890101":{"folder":"Ps","id":2090890101,"blendMode":0}};

let appearanceFit = {};
const appearanceFitReady = fetch('/api/appearance-fit').then(r => {
  if (!r.ok) throw new Error('appearance fit data unavailable');
  return r.json();
}).then(data => { appearanceFit = data; }).catch(error => console.warn('[preview]', error));

// 游戏内只有材质贴图、没有网格模型的服饰（CUE4Parse 完整索引核对结果）。
// 这些物品缺的是网格资源本身，界面上要与「本地导出漏了」区分开。
const unreleasedItems = new Map();
const unreleasedReady = fetch('/unreleased-items.json').then(r => {
  if (!r.ok) throw new Error('unreleased item list unavailable');
  return r.json();
}).then(data => {
  for (const item of data?.items || []) unreleasedItems.set(String(item.id), item);
}).catch(error => console.warn('[preview]', error));

function unreleasedLabel(desc) {
  if (!desc?.assetId) return null;
  const item = unreleasedItems.get(String(desc.assetId));
  if (!item) return null;
  return item.name ? `${item.name}（${item.id}）` : String(item.id);
}

// 预览状态文案：区分「游戏未实装」（游戏内只有材质贴图）与「本地资源缺失」。
function previewStatusText(missingDescs, loadedSize, hairFallback) {
  const names = (missingDescs || []).map(unreleasedLabel);
  const onlyUnreleased = names.length > 0 && names.every(name => !!name);
  if (onlyUnreleased) return `游戏未实装：${names.join('、')} 在游戏内只有材质贴图，没有网格模型`;
  if (names.length > 0 || loadedSize === 0) return '模型缺失';
  return hairFallback ? '戴帽版缺失，已使用普通发型' : '';
}

function resolveHeadwearFit(headwearName, hairName) {
  const type = (appearanceFit.HEADWEAR_TYPE_CONF || []).find(r => r.HeadWearName === headwearName);
  const hair = (appearanceFit.HEADWEAR_HAIR_CONF || []).find(r => r.HairName === hairName);
  if (!hair) return null;
  const wearType = type?.HeadWearType || 0;
  const info = (hair.Info || []).find(r => (r.WearType || 0) === wearType);
  if (!info) return null;
  const pair = (appearanceFit.HEADWEAR_OFFSET_CONF || []).find(r => r.HeadWearName === headwearName);
  const index = pair?.HairName?.indexOf(hairName) ?? -1;
  return { bone: info.BoneName, wearType, base: info.offset,
    extra: index >= 0 ? pair.Offset?.[index] : null };
}

function gameFitMatrix(value) {
  const fields = String(value || '0,0,0|0,0,0|1,1,1').split('|').map(s => s.split(',').map(Number));
  if (fields.length !== 3 || fields.some(a => a.length !== 3 || a.some(n => !Number.isFinite(n)))) return new THREE.Matrix4();
  const [t, r, scale] = fields;
  const [pitch, yaw, roll] = r.map(n => n * Math.PI / 360);
  const sp = Math.sin(pitch), cp = Math.cos(pitch), sy = Math.sin(yaw), cy = Math.cos(yaw), sr = Math.sin(roll), cr = Math.cos(roll);
  // Unreal FRotator quaternion, then the same Y/Z reflection used by the mesh exporter.
  const qx = cr * sp * sy - sr * cp * cy;
  const qy = -cr * sp * cy - sr * cp * sy;
  const qz = cr * cp * sy - sr * sp * cy;
  const qw = cr * cp * cy + sr * sp * sy;
  return new THREE.Matrix4().compose(new THREE.Vector3(t[0], t[2], t[1]).multiplyScalar(.01),
    new THREE.Quaternion(-qx, -qz, -qy, qw), new THREE.Vector3(scale[0], scale[2], scale[1]));
}

function modelAssetName(record) {
  return decodeURIComponent(record?.modelUrl || record?.desc?.primary || '').split('/').pop()?.replace(/\.gltf$/i, '') || '';
}

function mountConfiguredHeadwear(record) {
  const hair = [...loadedParts.values()].find(r => r.desc.folder === 'Hr');
  const fit = resolveHeadwearFit(modelAssetName(record), modelAssetName(hair));
  const anchor = fit && masterSkeletonScene && findBoneByName(masterSkeletonScene, fit.bone);
  if (!anchor) return false;
  const part = record.object;
  if (!part.userData.nrcAuthoredMatrix) part.userData.nrcAuthoredMatrix = part.matrix.clone();
  anchor.add(part);
  const matrix = gameFitMatrix(fit.base).multiply(gameFitMatrix(fit.extra)).multiply(part.userData.nrcAuthoredMatrix);
  matrix.decompose(part.position, part.quaternion, part.scale);
  part.updateMatrixWorld(true);
  part.userData.nrcAppearanceFit = { hair: modelAssetName(hair), ...fit };
  return true;
}

// ── 等待 DOM 就绪 ─────────────────────────────────────────────
const canvas = document.getElementById('preview-canvas');
if (!canvas) throw new Error('[preview] canvas#preview-canvas not found');

// ── 场景 / 渲染器 ─────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1b24);

// ── 相机 ──────────────────────────────────────────────────────
const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 50);
camera.position.set(0, 1.1, 3.2);
camera.lookAt(0, 0.9, 0);

// ── 控制器 ────────────────────────────────────────────────────
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 0.9, 0);
controls.enableDamping   = true;
controls.dampingFactor   = 0.08;
controls.minDistance     = 0.5;
controls.maxDistance     = 8;
controls.update();

// ── 光照 ──────────────────────────────────────────────────────
// 数值取自游戏便捷换装场景 NRC/Content/ArtRes/Level/UI/QuickChange/Level/L_QuickChange：
//   MainLight  方向光  Intensity 5.024  LightColor #F4EDFA  RelativeRotation Pitch -70.85238° Yaw -45.676987°
//   SkyLight   天光    LightColor #B1B1B1（UE 默认强度 1）
//   EnvSpotLightActor 0/1/2：0.4 #FFE3E7、20.0 白、1.0 #F0A7FF
// UE 以勒克斯/坎德拉计量并叠加后处理曝光，与 Three.js 单位不同：主光与天光按原值取用，
// 两盏彩色环境光按 0.5 倍折算成方向补光以保留颜色与相对强弱；强度 20 的白色环境聚光作用于
// 整个游戏场景，预览里已由主光与天光覆盖，未单独复刻。灯光位置不参与取景，相机与背景保持工具原样。
const ueLightForward = (pitchDeg, yawDeg) => {
  const pitch = (pitchDeg * Math.PI) / 180;
  const yaw = (yawDeg * Math.PI) / 180;
  return new THREE.Vector3(Math.cos(pitch) * Math.cos(yaw), Math.sin(pitch), Math.cos(pitch) * Math.sin(yaw));
};
const ueToThree = vector => new THREE.Vector3(vector.x, vector.z, vector.y);
scene.add(new THREE.AmbientLight(0xb1b1b1, 1.0));

const sun = new THREE.DirectionalLight(0xf4edfa, 5.024);
sun.position.copy(ueToThree(ueLightForward(-70.85238, -45.676987)).multiplyScalar(-8));
scene.add(sun);

const envFill = new THREE.DirectionalLight(0xf0a7ff, 0.5);
envFill.position.set(-3, 2, -2);
scene.add(envFill);

const envRim = new THREE.DirectionalLight(0xffe3e7, 0.2);
envRim.position.set(2, 2.5, -3);
scene.add(envRim);

// ── 地板网格 ──────────────────────────────────────────────────
const grid = new THREE.GridHelper(4, 10, 0x2e2f3e, 0x252635);
scene.add(grid);

// ── 尺寸响应 ──────────────────────────────────────────────────
function resizeToContainer() {
  const wrap = document.getElementById('preview-canvas-wrap');
  if (!wrap) return;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  if (w < 1 || h < 1) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

const wrapEl = document.getElementById('preview-canvas-wrap');
if (wrapEl) {
  new ResizeObserver(resizeToContainer).observe(wrapEl);
}
resizeToContainer();
// 延迟再次触发以防首帧布局未就绪
setTimeout(resizeToContainer, 0);

// ── 渲染循环 ──────────────────────────────────────────────────
(function animate(timestamp = performance.now()) {
  requestAnimationFrame(animate);
  const deltaSeconds = lastChromaFrameTime === null ? 0 : (timestamp - lastChromaFrameTime) / 1000;
  lastChromaFrameTime = timestamp;
  advanceChromaFlow(chromaUniforms, deltaSeconds);
  controls.update();
  renderer.render(scene, camera);
})();

// ── PC1 / PC2 固定基础部位（面部、眼睛、耳、眉）──────────────
const PC1_BASE = '/models/PC1/Avatar';
const PC2_BASE = '/models/PC2/Avatar';
const DEFAULT_PC1_SKIN_AVATAR_ID = 30000001;
const DEFAULT_PC1_SKIN_TEXTURE_ID = 10400001;
const DEFAULT_PC1_BODY_SKIN_TEXTURE_ID = 10000001;
const DEFAULT_PC1_BROW_MODEL_ID = 10300001;
const DEFAULT_PC1_EYESOCKET_MODEL_ID = 10400001;
const DEFAULT_PC2_SKIN_AVATAR_ID = 30000001;
const DEFAULT_PC2_SKIN_TEXTURE_ID = 20400001;
const DEFAULT_PC2_BROW_MODEL_ID = 20300001;
const DEFAULT_PC2_EYESOCKET_MODEL_ID = 20400001;
const DEFAULT_PC_PUPIL_TEXTURE_ID = 34000001;

const PC1_SKIN_TEXTURE_ID = {
  30000001: 10400001,
  30000002: 10400002,
  30000003: 10400003,
  30000007: 10400007,
};

const PC1_BODY_SKIN_TEXTURE_ID = {
  30000001: 10000001,
  30000002: 10000002,
  30000003: 10000003,
  30000007: 10000007,
};

// 肤色 avatar_id → Et 贴图 id。Fe 脸部与 Et 睫毛/眼眶共用这张肤色贴图。
const PC2_SKIN_TEXTURE_ID = {
  30000001: 20400001,
  30000002: 20400002,
  30000003: 20400003,
  30000007: 20400007,
};

// 肤色 avatar_id → By 身体皮肤贴图 id。服装材质里的 By 槽用这组索引。
const PC2_BODY_SKIN_TEXTURE_ID = {
  30000001: 20000001,
  30000002: 20000002,
  30000003: 20000003,
  30000007: 20000007,
};

const PC1_BROW_MODEL_ID = {
  12000001: 10300001,
  12001001: 10300101,
  12002001: 10300201,
  12003001: 10300301,
  12004001: 10300401,
};

// Br 眉毛 avatar_id → PC2 Br 模型 id。
const PC2_BROW_MODEL_ID = {
  22000001: 20300001,
  22001001: 20300101,
  22002001: 20300201,
  22003001: 20300301,
  22004001: 20300401,
};

const PC1_EYESOCKET_MODEL_ID = {
  13000000: 10400001,
  13001000: 10400101,
  13002000: 10400201,
  13003000: 10400301,
  13004000: 10400401,
  13005000: 10400501,
  13006000: 10400601,
  13007000: 10400701,
  13008000: 10400801,
  13010000: 10401001,
  13011000: 10401101,
  // 后续批次：规律同前（1300k000 -> 10400k01）；
  // 其中 13012000/13014000 的对应关系由 SALON_ITEM_CONF 的图标字段直接印证
  // （id 378 图标 10401201、id 362 图标 10401401）
  13009000: 10400901,
  13012000: 10401201,
  13013000: 10401301,
  13014000: 10401401,
};

// Et 睫毛/眼眶 avatar_id → PC2 Et 模型 id。
const PC2_EYESOCKET_MODEL_ID = {
  23000000: 20400001,
  23001000: 20400101,
  23002000: 20400201,
  23003000: 20400301,
  23004000: 20400401,
  23005000: 20400501,
  23006000: 20400601,
  23007000: 20400701,
  23008000: 20400801,
  23010000: 20401001,
  23011000: 20401101,
  // 同 PC1：2300k000 -> 20400k01
  23009000: 20400901,
  23012000: 20401201,
  23013000: 20401301,
  23014000: 20401401,
};

const DEFAULT_PC_BROW_COLOR = '4F2317FF';
const PC_BROW_TEXTURE_ROOT = '/models/PC_Br/Tex';
const PC_BROW_COLOR_TEXTURE_ID = {
  '563027FF': '4F2317FF',
  '3E3F40FF': '261A1EFF',
  '93A6ABFF': '9F91A1FF',
  '9D7447FF': 'AC6931FF',
  '671D2AFF': '8F291AFF',
};

function normalizeColorTextureId(color, fallback = DEFAULT_PC_BROW_COLOR) {
  const colorId = String(color || fallback).replace(/^#/, '').toUpperCase();
  return PC_BROW_COLOR_TEXTURE_ID[colorId] || colorId;
}

function buildPCBrowTextureUrl(color) {
  const colorId = normalizeColorTextureId(color);
  return `${PC_BROW_TEXTURE_ROOT}/T_PC1_Br_${colorId}_D.png`;
}

function getSelectedSalonAvatarId(selected, slot, fallback) {
  return Number(selected?.[slot]?.item?.avatar_id) || fallback;
}

function getPC1SkinTextureUrl(selected) {
  const avatarId = getSelectedSalonAvatarId(selected, 'salon_undefined', DEFAULT_PC1_SKIN_AVATAR_ID);
  const textureId = PC1_SKIN_TEXTURE_ID[avatarId] || DEFAULT_PC1_SKIN_TEXTURE_ID;
  return `${PC1_BASE}/Et/10400001/Tex/T_PC1_Et_${textureId}_D.png`;
}

function getPC2SkinTextureUrl(selected) {
  const avatarId = getSelectedSalonAvatarId(selected, 'salon_undefined', DEFAULT_PC2_SKIN_AVATAR_ID);
  const textureId = PC2_SKIN_TEXTURE_ID[avatarId] || DEFAULT_PC2_SKIN_TEXTURE_ID;
  return `${PC2_BASE}/Et/20400001/Tex/T_PC2_Et_${textureId}_D.png`;
}

function getPC1BodySkinTextureId(selected) {
  const avatarId = getSelectedSalonAvatarId(selected, 'salon_undefined', DEFAULT_PC1_SKIN_AVATAR_ID);
  return PC1_BODY_SKIN_TEXTURE_ID[avatarId] || DEFAULT_PC1_BODY_SKIN_TEXTURE_ID;
}

function getPC2BodySkinTextureId(selected) {
  const avatarId = getSelectedSalonAvatarId(selected, 'salon_undefined', DEFAULT_PC2_SKIN_AVATAR_ID);
  return PC2_BODY_SKIN_TEXTURE_ID[avatarId] || 20000001;
}

function getPC1BrowModelId(selected) {
  const avatarId = getSelectedSalonAvatarId(selected, 'salon_2', null);
  return PC1_BROW_MODEL_ID[avatarId] || DEFAULT_PC1_BROW_MODEL_ID;
}

function getPC2BrowModelId(selected) {
  const avatarId = getSelectedSalonAvatarId(selected, 'salon_2', null);
  return PC2_BROW_MODEL_ID[avatarId] || DEFAULT_PC2_BROW_MODEL_ID;
}

function getPC2BrowTextureCandidates(selected) {
  const color = selected?.salon_2?.item?.colour_id?.[0];
  const colorUrl = buildPCBrowTextureUrl(color);
  const defaultUrl = buildPCBrowTextureUrl(DEFAULT_PC_BROW_COLOR);
  return colorUrl === defaultUrl ? defaultUrl : [colorUrl, defaultUrl];
}

function getPC1EyesocketModelId(selected) {
  const avatarId = getSelectedSalonAvatarId(selected, 'salon_3', null);
  return PC1_EYESOCKET_MODEL_ID[avatarId] || DEFAULT_PC1_EYESOCKET_MODEL_ID;
}

function getPC2EyesocketModelId(selected) {
  const avatarId = getSelectedSalonAvatarId(selected, 'salon_3', null);
  return PC2_EYESOCKET_MODEL_ID[avatarId] || DEFAULT_PC2_EYESOCKET_MODEL_ID;
}

function getPCPupilTextureId(selected) {
  return getSelectedSalonAvatarId(selected, 'salon_4', DEFAULT_PC_PUPIL_TEXTURE_ID);
}

function getPC1MakeupTextureUrl(selected) {
  const avatarId = getSelectedSalonAvatarId(selected, 'salon_5', null);
  if (!avatarId) return null;
  const suffixNumber = Number(avatarId) - 15000000;
  if (suffixNumber <= 0) return null;
  const suffix = String(suffixNumber).padStart(2, '0');
  return `${PC1_BASE}/Mp/T_PC1_Mp_${suffix}.png`;
}

function getPC2MakeupTextureUrl(selected) {
  const avatarId = getSelectedSalonAvatarId(selected, 'salon_5', null);
  if (!avatarId) return null;
  const suffixNumber = Number(avatarId) - 25000000;
  if (suffixNumber <= 0) return null;
  const suffix = String(suffixNumber).padStart(2, '0');
  return `${PC2_BASE}/Mp/T_PC2_Mp_${suffix}.png`;
}

function getPC1BaseParts(selected = {}) {
  const skinTexture = getPC1SkinTextureUrl(selected);
  const makeupTexture = getPC1MakeupTextureUrl(selected);
  const browModelId = getPC1BrowModelId(selected);
  const eyesocketModelId = getPC1EyesocketModelId(selected);
  const browTexture = getPC2BrowTextureCandidates(selected);
  const pupilTextureId = getPCPupilTextureId(selected);
  const skinMakeupTexture = makeupTexture
    ? { url: skinTexture, overlay: { url: makeupTexture } }
    : skinTexture;

  return [
    {
      key: 'base:Fe',
      primary: `${PC1_BASE}/Fe/10200001/SKM_PC1_Fe_10200001.gltf`,
      materialTextures: {
        default: skinMakeupTexture,
      },
    },
    {
      key: 'base:Es',
      primary: `${PC1_BASE}/Es/10500001/SKM_PC1_Es_10500001.gltf`,
      materialTextures: {
        MI_PC_Es_A_LR: { url: `/models/PC_Es/Tex/T_PC_Es_${pupilTextureId}.png`, uvRepeat: [2, 1] },
        MI_PC1_Es_A_LR: { url: `/models/PC_Es/Tex/T_PC_Es_${pupilTextureId}.png`, uvRepeat: [2, 1] },
      },
    },
    {
      key: 'base:Et',
      primary: `${PC1_BASE}/Et/${eyesocketModelId}/SKM_PC1_Et_${eyesocketModelId}.gltf`,
      materialTextures: {
        default: skinMakeupTexture,
      },
    },
    {
      key: 'base:Br',
      primary: `${PC1_BASE}/Br/${browModelId}/SKM_PC1_Br_${browModelId}.gltf`,
      materialTextures: {
        MI_PC1_Br: browTexture,
        MI_PC_Br: browTexture,
        default: browTexture,
      },
    },
    {
      key: 'base:Er',
      primary: `${PC1_BASE}/Er/10600001/SKM_PC1_Er_10600001.gltf`,
      g: 'PC1',
      folder: 'Er',
      textureId: 10600001,
    },
  ];
}

function getPC2BaseParts(selected = {}) {
  const skinTexture = getPC2SkinTextureUrl(selected);
  const makeupTexture = getPC2MakeupTextureUrl(selected);
  const browModelId = getPC2BrowModelId(selected);
  const eyesocketModelId = getPC2EyesocketModelId(selected);
  const browTexture = getPC2BrowTextureCandidates(selected);
  const pupilTextureId = getPCPupilTextureId(selected);
  const skinMakeupTexture = makeupTexture
    ? { url: skinTexture, overlay: { url: makeupTexture } }
    : skinTexture;

  return [
    {
      key: 'base:Fe',
      primary: `${PC2_BASE}/Fe/20200001/SKM_PC2_Fe_20200001.gltf`,
      materialTextures: {
        default: skinMakeupTexture,
      },
    },
    {
      key: 'base:Es',
      primary: `${PC2_BASE}/Es/20500001/SKM_PC2_Es_20500001.gltf`,
      materialTextures: {
        MI_PC_Es_A_LR: { url: `/models/PC_Es/Tex/T_PC_Es_${pupilTextureId}.png`, uvRepeat: [2, 1] },
      },
    },
    {
      key: 'base:Et',
      primary: `${PC2_BASE}/Et/${eyesocketModelId}/SKM_PC2_Et_${eyesocketModelId}.gltf`,
      materialTextures: {
        default: skinMakeupTexture,
      },
    },
    {
      key: 'base:Br',
      primary: `${PC2_BASE}/Br/${browModelId}/SKM_PC2_Br_${browModelId}.gltf`,
      materialTextures: {
        MI_PC2_Br: browTexture,
        MI_PC_Br: browTexture,
        default: browTexture,
      },
    },
    {
      key: 'base:Er',
      primary: `${PC2_BASE}/Er/20600001/SKM_PC2_Er_20600001.gltf`,
      g: 'PC2',
      folder: 'Er',
      textureId: 20600001,
    },
  ];
}// ── 模型加载映射 ──────────────────────────────────────────────
// type_name → { folder, prefix }
const SLOT_FOLDER = {
  '上衣': { folder: 'Cup', prefix: 'SKM' },
  '下装': { folder: 'Ps',  prefix: 'SKM' },
  '袜子': { folder: 'So',  prefix: 'SKM' },
  '鞋子': { folder: 'Se',  prefix: 'SKM' },
  '手饰': { folder: 'Ge',  prefix: 'SKM' },
  '帽子': { folder: 'Ht',  prefix: 'SKM' },
  '背包': { folder: 'Bg',  prefix: 'SKM' },
  '头饰': { folder: 'Hi',  prefix: 'SM'  },
  '面饰': { folder: 'Fi',  prefix: 'SM'  },
  // 连体服 使用 type_name='上衣'，走相同的 Cup 路径
};

// 资产槽位规则：物品 ID 的第 2-3 位决定模型所在文件夹（与游戏资源目录一致）。
// 07 上衣/连衣 → Cup，14 玩偶服 → Wh，24 包挂饰 → PC3/Avatar/Bi，25 法杖 → PC3/Avatar/Mw，
// 26 口罩 → Ms，27/28 头套 → Hg/Hp。
const SLOT_BY_ID = {
  '07': { folder: 'Cup' },
  '08': { folder: 'Ge' },
  '09': { folder: 'Ps' },
  '10': { folder: 'So' },
  '11': { folder: 'Se' },
  '12': { folder: 'Bg' },
  '13': { folder: 'Ht' },
  '14': { folder: 'Wh' },
  '21': { folder: 'Hi' },
  '22': { folder: 'Fi' },
  '24': { folder: 'Bi', gender: 'PC3' },
  '25': { folder: 'Mw', gender: 'PC3' },
  '26': { folder: 'Ms' },
  '27': { folder: 'Hg' },
  '28': { folder: 'Hp' },
};

function slotModelInfo(item) {
  const slot = SLOT_BY_ID[String(item.id).slice(1, 3)];
  if (!slot) return null;
  const prefix = slot.folder === 'Hi' || slot.folder === 'Fi' ? 'SM' : 'SKM';
  return { folder: slot.folder, prefix, gender: slot.gender || null };
}

const HEAD_ATTACHED_FOLDERS = new Set(['Hi', 'Fi', 'Ms', 'Hg', 'Hp']);
const HEAD_BONE_NAME = 'Bip001-Head';
const HEAD_ACCESSORY_Z_ROTATION = THREE.MathUtils.degToRad(0);

function shouldAttachToHead(folder) {
  return HEAD_ATTACHED_FOLDERS.has(folder);
}

function getAttachmentBone(folder) {
  if (folder === 'Mw') return 'locator_right_hand';
  if (folder === 'Bi') return 'Bone_Bag_root';
  return shouldAttachToHead(folder) ? HEAD_BONE_NAME : null;
}

// 发型资产规则：avatar_id 11014015 → 模型目录 10101401
//   （首位性别码 + '01' + 第 4-6 位循环右移一位 + '01'）。
// 2026-10-13：原先 5 个缺失网格的发型（10103201/10103501/20103201/20103401/20103501）
// 已从游戏内全部导出补齐，黑名单清空。
const HAIR_MODEL_GAPS = new Set();

function deriveHairModelId(avatarId) {
  const s = String(avatarId);
  if (s.length !== 8) return null;
  const modelId = Number(`${s[0]}01${s[5]}${s[3]}${s[4]}01`);
  if (HAIR_MODEL_GAPS.has(modelId)) return null;
  return modelId;
}

// 换色机制：变色款不带独立模型，与基础款共用同一 Mesh。
// 8位ID: 末2位为变体编号，非 01 时 fallback 到 末2位=01
// 10位ID: 末4位为 {变体2位}{01}，变体非 01 时 fallback 到 末4位=0101
function getBaseId(id) {
  const s = String(id);
  if (s.length === 8  && s.slice(-2)     !== '01') return s.slice(0, -2)  + '01';
  if (s.length === 10 && s.slice(-4, -2) !== '01') return s.slice(0, -4)  + '0101';
  return null;
}

function buildPartUrl(g, info, id) {
  return `/models/${g}/Avatar/${info.folder}/${id}/${info.prefix}_${g}_${info.folder}_${id}.gltf`;
}

function buildMasterSkeletonUrl(g) {
  return `/models/${g}/SKM_${g}.gltf`;
}
function buildHairUrl(g, id, hasHat) {
  const suffix = hasHat ? 'Hr_Ht' : 'Hr';
  return `/models/${g}/Avatar/Hr/${id}/SKM_${g}_${suffix}_${id}.gltf`;
}

function addTextureOffset(modelId, textureId) {
  return Number(modelId) + Math.max((textureId || 1) - 1, 0);
}

function getModelDir(modelUrl) {
  return modelUrl.slice(0, modelUrl.lastIndexOf('/'));
}

function buildTextureUrl(g, folder, dirId, textureId) {
  return `/models/${g}/Avatar/${folder}/${dirId}/Tex/T_${g}_${folder}_${textureId}_D.png`;
}

function buildTextureUrlInModelDir(modelUrl, g, folder, textureId) {
  return buildTextureUrlInModelDirWithSuffix(modelUrl, g, folder, textureId, 'D');
}

function buildTextureUrlInModelDirWithSuffix(modelUrl, g, folder, textureId, suffix) {
  return `${getModelDir(modelUrl)}/Tex/T_${g}_${folder}_${textureId}_${suffix}.png`;
}

function parseMaterialSlot(materialName) {
  const rule = MATERIAL_RENDER_RULES[(materialName || '').toLowerCase()];
  if (rule?.folder && rule.id) return { folder: rule.folder, id: rule.id };
  if (/_outline$/i.test(materialName || '')) return null;
  const match = /^MI_PC[123]_([A-Za-z]+)(?:_[A-Za-z]+)*_([0-9]{6,})(?:_[A-Za-z][A-Za-z0-9]*)?$/i.exec(materialName || '');
  if (!match) return null;
  return { folder: match[1], id: Number(match[2]) };
}

function normalizeTextureCandidate(candidate) {
  return typeof candidate === 'string' ? { url: candidate } : candidate;
}

function textureCandidatesForMaterial(material, desc, modelUrl) {
  const manual = desc.materialTextures?.[material?.name] ?? desc.materialTextures?.default;
  if (manual) {
    const list = Array.isArray(manual) ? manual : [manual];
    return list.map(normalizeTextureCandidate).filter(c => c?.url);
  }

  const slot = parseMaterialSlot(material?.name);
  if (!slot || !desc.g || !desc.folder || !desc.textureId) return [];

  if (slot.folder === 'By' && desc.bodySkinTextureId) return [
    buildTextureUrl(desc.g, slot.folder, slot.id, desc.bodySkinTextureId),
    buildTextureUrl(desc.g, slot.folder, slot.id, slot.id),
  ].map(url => ({ url }));
  const stem = material.name.replace(/^MI_/i, 'T_');
  const variantStem = stem.replace(String(slot.id), String(desc.textureId));
  const dir = getModelDir(modelUrl);
  const genericVariant = `T_${desc.g}_${slot.folder}_${desc.textureId}`;
  const genericBase = `T_${desc.g}_${slot.folder}_${slot.id}`;
  const urls = [
    `${dir}/Tex/${variantStem}_D.png`,
    `/model-texture/${encodeURIComponent(variantStem + '_D.png')}`,
    `${dir}/Tex/${genericVariant}_D.png`,
    `/model-texture/${encodeURIComponent(genericVariant + '_D.png')}`,
    `${dir}/Tex/${stem}_D.png`,
    `/model-texture/${encodeURIComponent(stem + '_D.png')}`,
    `${dir}/Tex/${genericBase}_D.png`,
    buildTextureUrl(desc.g, slot.folder, slot.id, slot.id),
    `/model-texture/${encodeURIComponent(genericBase + '_D.png')}`,
  ];
  return [...new Set(urls)].map(url => ({ url }));
}

function loadTexture(candidate) {
  const options = normalizeTextureCandidate(candidate);
  return new Promise(resolve => {
    textureLoader.load(options.url, texture => {
      texture.colorSpace = options.colorSpace === 'linear'
        ? THREE.LinearSRGBColorSpace
        : THREE.SRGBColorSpace;
      texture.flipY = false;
      texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
      if (options.filter === 'nearest') {
        texture.magFilter = THREE.NearestFilter;
        texture.minFilter = THREE.NearestFilter;
        texture.generateMipmaps = false;
      }
      if (options.wrap === 'repeat') {
        texture.wrapS = THREE.RepeatWrapping;
        texture.wrapT = THREE.RepeatWrapping;
      }
      if (options.wrap === 'clamp') {
        texture.wrapS = THREE.ClampToEdgeWrapping;
        texture.wrapT = THREE.ClampToEdgeWrapping;
      }
      texture.userData.nrcUrl = options.url;
      texture.userData.nrcOptions = { ...options };
      resolve(texture);
    }, undefined, () => resolve(null));
  });
}

async function loadFirstTexture(candidates, textureCache) {
  for (const candidate of candidates) {
    if (!textureCache.has(candidate.url)) textureCache.set(candidate.url, loadTexture(candidate));
    const texture = await textureCache.get(candidate.url);
    if (!texture) continue;

    const options = { ...candidate };
    if (candidate.overlay) {
      const overlay = normalizeTextureCandidate(candidate.overlay);
      if (overlay?.url) {
        if (!textureCache.has(overlay.url)) textureCache.set(overlay.url, loadTexture(overlay));
        options.overlayTexture = await textureCache.get(overlay.url);
      }
    }
    return { texture, options };
  }
  return null;
}

function addShaderPatch(material, key, patch) {
  const previous = material.onBeforeCompile;
  const previousKey = material.customProgramCacheKey;
  material.onBeforeCompile = shader => {
    previous?.(shader);
    patch(shader);
  };
  material.customProgramCacheKey = () => `${previousKey ? previousKey.call(material) : ''}|${key}`;
}

function patchUvRepeatShader(material, uvRepeat) {
  if (!uvRepeat) return;
  const [u, v] = uvRepeat;
  addShaderPatch(material, `nrc-uv-repeat-${u}-${v}`, shader => {
    shader.fragmentShader = shader.fragmentShader.replace(
      '#include <map_fragment>',
      `#ifdef USE_MAP
        vec2 nrcRepeatedMapUv = fract(vMapUv * vec2(${u.toFixed(6)}, ${v.toFixed(6)}));
        vec4 sampledDiffuseColor = texture2D(map, nrcRepeatedMapUv);
        #ifdef DECODE_VIDEO_TEXTURE
          sampledDiffuseColor = sRGBTransferEOTF(sampledDiffuseColor);
        #endif
        diffuseColor *= vec4(sampledDiffuseColor.rgb, 1.0);
      #endif`
    );
  });
}

function patchOverlayTextureShader(material, overlayTexture) {
  if (!overlayTexture) return;
  addShaderPatch(material, 'nrc-overlay-texture', shader => {
    shader.uniforms.nrcOverlayMap = { value: overlayTexture };
    shader.fragmentShader = shader.fragmentShader.replace(
      'void main() {',
      `uniform sampler2D nrcOverlayMap;

      void main() {`
    );
    shader.fragmentShader = shader.fragmentShader.replace(
      '#include <map_fragment>',
      `#include <map_fragment>
      vec4 nrcOverlayColor = texture2D(nrcOverlayMap, vMapUv);
      diffuseColor.rgb = mix(diffuseColor.rgb, nrcOverlayColor.rgb, nrcOverlayColor.a);`
    );
  });
}
const chromaPatternCache = new Map();
function getChromaPattern(url = '/chroma-assets/Tex_PetGlassy_007_D.png') {
  if (!chromaPatternCache.has(url)) chromaPatternCache.set(url, loadTexture({ url, colorSpace: 'linear', wrap: 'repeat' }));
  return chromaPatternCache.get(url);
}
let chromaPaletteSerial = 0;

async function applyChromaPreset(preset) {
  const serial = ++chromaPaletteSerial;
  updateChromaUniforms(chromaUniforms, null);
  if (!preset) return;
  const [pattern, ornament] = await Promise.all([
    getChromaPattern(preset.pattern),
    preset.ornament?.texture ? getChromaPattern(preset.ornament.texture) : Promise.resolve(null)
  ]);
  if (serial !== chromaPaletteSerial) return;
  if (!pattern || (preset.ornament?.texture && !ornament)) {
    window.dispatchEvent(new CustomEvent('nrc-chroma-error'));
    return;
  }
  chromaUniforms.nrcChromaPattern.value = pattern;
  chromaUniforms.nrcChromaStickTexture.value = ornament;
  updateChromaUniforms(chromaUniforms, preset);
}
window.addEventListener('nrc-chroma-change', event => applyChromaPreset(event.detail));
applyChromaPreset(getActiveChromaPreset());
function getChromaSupportCount() {
  const materials = new Set();
  for (const { object } of loadedParts.values()) object.traverse(obj => {
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
    for (const mat of mats) if (mat?.userData?.nrcChromaMaskUrl) materials.add(mat);
  });
  return materials.size;
}
window.getChromaSupportCount = getChromaSupportCount;
function reportChromaSupport() {
  window.dispatchEvent(new CustomEvent('nrc-chroma-support', { detail: { count: getChromaSupportCount() } }));
}
function cloneMaterialWithTexture(material, textureInfo) {
  const next = material.clone();
  next.map = textureInfo.texture;
  next.color?.set(0xffffff);
  next.vertexColors = false;
  // clone 保留资源声明的透明、裁切和深度写入方式；纹理 Alpha 不一定是透明度。
  const rule = MATERIAL_RENDER_RULES[(material.name || '').toLowerCase()];
  if (rule?.blendMode === 2) {
    next.transparent = true;
    next.depthWrite = false;
  } else if (rule?.blendMode === 1) {
    next.transparent = false;
    next.alphaTest = rule.alphaTest;
    next.depthWrite = true;
  }
  patchUvRepeatShader(next, textureInfo.options?.uvRepeat);
  patchOverlayTextureShader(next, textureInfo.options?.overlayTexture);
  next.userData.nrcBaseTextureUrl = textureInfo.options?.url || textureInfo.texture?.userData?.nrcUrl || null;
  next.userData.nrcTextureOptions = { ...(textureInfo.options || {}) };
  if (textureInfo.options?.overlayTexture) {
    next.userData.nrcOverlayTextureUrl = textureInfo.options.overlayTexture.userData?.nrcUrl || null;
    next.userData.nrcExtraTextures = [textureInfo.options.overlayTexture];
  }
  if (textureInfo.chromaMask) {
    if (!chromaUniforms.nrcChromaPattern.value) chromaUniforms.nrcChromaPattern.value = textureInfo.chromaPattern;
    addShaderPatch(next, 'nrc-chroma-v1', shader => patchChromaShader(shader, chromaUniforms, textureInfo.chromaMask, textureInfo.chromaPattern));
    next.userData.nrcChromaMaskUrl = textureInfo.chromaMask.userData.nrcUrl;
    next.userData.nrcExtraTextures = [...(next.userData.nrcExtraTextures || []), textureInfo.chromaMask];
  }
  next.needsUpdate = true;
  return next;
}

async function applyTextureToScene(scenePart, desc, modelUrl) {
  scenePart.userData.nrcPreview = { key: desc.key, modelUrl };
  if (!desc.materialTextures && (!desc.folder || !desc.textureId)) return scenePart;

  const chromaData = await chromaDataReady;
  const materialToTexture = new Map();
  const textureCache = new Map();
  const materials = new Set();

  scenePart.traverse(obj => {
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
    mats.filter(Boolean).forEach(m => materials.add(m));
  });

  await Promise.all([...materials].map(async material => {
    const candidates = textureCandidatesForMaterial(material, desc, modelUrl);
    if (!candidates.length) return;
    const textureInfo = await loadFirstTexture(candidates, textureCache);
    if (textureInfo) {
      const maskUrl = getChromaMask(material.name, chromaData.materials, desc.textureId);
      if (maskUrl) {
        textureInfo.chromaPattern = await getChromaPattern();
        if (textureInfo.chromaPattern) textureInfo.chromaMask = await loadTexture({ url: maskUrl, colorSpace: 'linear' });
      }
      materialToTexture.set(material, textureInfo);
    }
  }));

  scenePart.traverse(obj => {
    if (!obj.isMesh && !obj.isSkinnedMesh) return;
    const apply = material => {
      const textureInfo = materialToTexture.get(material);
      return textureInfo ? cloneMaterialWithTexture(material, textureInfo) : material;
    };
    obj.material = Array.isArray(obj.material)
      ? obj.material.map(apply)
      : apply(obj.material);
  });

  return scenePart;
}

async function loadPart(desc) {
  try {
    const gltf = await loadGltf(desc.primary);
    return applyTextureToScene(gltf.scene, desc, desc.primary);
  } catch {
    if (!desc.fallback) return null;
    try {
      console.log('[preview] model fallback:', desc.fallback);
      const gltf = await loadGltf(desc.fallback);
      if (desc.folder === 'Hr') gltf.scene.userData.nrcHairFallback = true;
      return applyTextureToScene(gltf.scene, desc, desc.fallback);
    } catch {
      return null;
    }
  }
}

function displayItemAssetId(item) {
  return (appearanceFit.ITEM_TRANS_CONF || []).find(row => row.id === item.id)?.trans_id || item.id;
}

// 帽子槽里也可能是「资源其实是静态头饰」的物品。全库只有男款 12108501（头饰-画间沉铁兽印象）
// 一件：物品类型是帽子，网格却在 Hi，并且在 HEADWEAR_HAIR_CONF 里带 WearType 4 的偏移。
// 这类物品若按帽子处理，头发会切到戴帽版，而戴帽版所有偏移都是 0，头饰就会掉到脖子位置。
function wearsHatMesh(selected) {
  const item = selected?.['帽子']?.item;
  if (!item) return false;
  const info = slotModelInfo(item) || SLOT_FOLDER[item.type_name];
  return info?.folder === 'Ht';
}

function getModelUrl(gender, slotKey, item, source, selected) {
  const g = `PC${gender}`;
  const bodySkinTextureId = gender === 1
    ? getPC1BodySkinTextureId(selected)
    : getPC2BodySkinTextureId(selected);
  if (source === 'salon') {
    if (item.type === 1) {
      const av = item.avatar_id;
      const modelId = deriveHairModelId(av);
      if (!modelId) return null;
      const hasHat = wearsHatMesh(selected);
      return {
        key: `slot:${slotKey}`,
        primary: buildHairUrl(g, modelId, hasHat),
        fallback: hasHat ? buildHairUrl(g, modelId, false) : null,
        g,
        folder: 'Hr',
        textureId: addTextureOffset(modelId, item.texture_id),
      };
    }
    return null;
  }
  const typeName = item.type_name;
  const info = slotModelInfo(item) || SLOT_FOLDER[typeName];
  if (!info) return null;
  const id = displayItemAssetId(item);
  const fbId = getBaseId(id);
  const partG = info.gender || g;   // 包挂饰/法杖等资产存放在 PC3 骨架目录
  return {
    key: `slot:${slotKey}`,
    primary:  buildPartUrl(partG, info, id),
    fallback: fbId ? buildPartUrl(partG, info, fbId) : null,
    g: partG,
    folder: info.folder,
    textureId: id,
    assetId: id,
    bodySkinTextureId,
    attachToBone: getAttachmentBone(info.folder),
  };
}

// ── 模型状态 ──────────────────────────────────────────────────
const loader = new GLTFLoader();
const textureLoader = new THREE.TextureLoader();
let modelGroup = null;          // 当前场景中的模型组
let masterSkeletonScene = null; // 当前性别的主骨骼
let skeletonContext = null;     // 主骨骼名称映射
let loadedParts = new Map();    // key -> { object, signature, desc, modelUrl }
let currentGender = null;
let loadSerial = 0;             // 防止旧请求覆盖新结果
let lastPreviewRequestSignature = null;

function setStatus(msg) {
  const el = document.getElementById('preview-status');
  if (el) el.textContent = msg;
}

function disposeMaterial(material) {
  if (!material) return;
  material.map?.dispose();
  material.normalMap?.dispose();
  material.roughnessMap?.dispose();
  material.metalnessMap?.dispose();
  material.alphaMap?.dispose();
  material.userData?.nrcExtraTextures?.forEach(texture => texture.dispose());
  material.dispose();
}

function disposeGroup(group) {
  group.traverse(obj => {
    obj.geometry?.dispose();
    if (Array.isArray(obj.material))
      obj.material.forEach(disposeMaterial);
    else
      disposeMaterial(obj.material);
  });
}

function normalizeImportedPbr(gltf) {
  if (!/SharpGLTF/i.test(gltf.parser?.json?.asset?.generator || '')) return gltf;
  gltf.scene.traverse(obj => {
    const materials = Array.isArray(obj.material) ? obj.material : [obj.material];
    for (const material of materials.filter(Boolean)) {
      const index = gltf.parser.associations.get(material)?.materials;
      const pbr = gltf.parser.json.materials?.[index]?.pbrMetallicRoughness;
      if (pbr && pbr.metallicFactor === undefined && !pbr.metallicRoughnessTexture) material.metalness = 0;
    }
  });
  return gltf;
}

async function loadGltf(url) {
  return new Promise((resolve, reject) =>
    loader.load(url, gltf => resolve(normalizeImportedPbr(gltf)), undefined, err => reject(err))
  );
}

function hideSkeletonSourceMeshes(root) {
  root.traverse(obj => {
    if (!obj.isMesh && !obj.isSkinnedMesh) return;
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
    mats.filter(Boolean).forEach(material => { material.visible = false; });
  });
}

function createSkeletonContext(root) {
  const bonesByName = new Map();
  root.traverse(obj => {
    if (obj.isBone) bonesByName.set(obj.name, obj);
  });
  return { root, bonesByName };
}

function removeDetachedSkeletonBones(root) {
  const skeletonRoots = [];
  root.traverse(obj => {
    if (obj.isBone && !obj.parent?.isBone) skeletonRoots.push(obj);
  });
  skeletonRoots.forEach(bone => bone.parent?.remove(bone));
}

function rebindSkinnedMeshesToSkeleton(root, skeletonContext) {
  if (!skeletonContext) return false;
  // 先刷新部件与主骨架的世界矩阵，下面要用它们的 rest 姿态做对齐修正。
  root.updateWorldMatrix(true, true);
  skeletonContext.root.updateWorldMatrix(true, true);
  let didRebind = false;
  let failed = false;
  root.traverse(obj => {
    if (!obj.isSkinnedMesh || !obj.skeleton) return;
    const mappedBones = obj.skeleton.bones.map(bone => skeletonContext.bonesByName.get(bone.name));
    if (mappedBones.some(bone => !bone)) {
      const missing = obj.skeleton.bones
        .filter(bone => !skeletonContext.bonesByName.has(bone.name))
        .map(bone => bone.name)
        .slice(0, 8)
        .join(', ');
      console.warn(`[preview] skeleton rebind skipped for ${obj.name || 'mesh'}; missing bones: ${missing}`);
      failed = true;
      return;
    }
    // rest 姿态对齐：部件自带的 rest 姿态可能与主骨架不同（悬浮/穿模的根因），
    // 把两者的差异并入 bind 矩阵：newInv = mainRest⁻¹ · partRest · oldInv。
    // 主骨架处于自身 rest 姿态时，顶点将还原到部件 bind pose 的正确位置；
    // 主骨架姿态变化时部件仍会正确跟随。
    const boneInverses = obj.skeleton.boneInverses.map((matrix, i) => {
      const partBone = obj.skeleton.bones[i];
      const mainBone = mappedBones[i];
      const correction = new THREE.Matrix4()
        .copy(mainBone.matrixWorld)
        .invert()
        .multiply(partBone.matrixWorld);
      return correction.multiply(matrix.clone());
    });
    const sharedSkeleton = new THREE.Skeleton(mappedBones, boneInverses);
    obj.bind(sharedSkeleton, obj.bindMatrix.clone());
    didRebind = true;
  });
  if (didRebind && !failed) removeDetachedSkeletonBones(root);
  return didRebind && !failed;
}

async function loadMasterSkeleton(gender) {
  const g = `PC${gender}`;
  try {
    const gltf = await loadGltf(buildMasterSkeletonUrl(g));
    hideSkeletonSourceMeshes(gltf.scene);
    gltf.scene.updateMatrixWorld(true);
    return gltf.scene;
  } catch (err) {
    console.warn(`[preview] master skeleton not available for ${g}; parts keep their own skeletons.`, err);
    return null;
  }
}
function findBoneByName(root, name) {
  let found = null;
  root.traverse(obj => {
    if (!found && obj.isBone && obj.name === name) found = obj;
  });
  return found;
}

function mountHeadAccessories(group, accessories) {
  if (!accessories.length) return;
  const headBone = findBoneByName(group, HEAD_BONE_NAME);
  if (!headBone) {
    accessories.forEach(part => group.add(part));
    console.warn(`[preview] ${HEAD_BONE_NAME} not found; head accessories kept in model root.`);
    return;
  }
  group.updateMatrixWorld(true);
  for (const part of accessories) {
    headBone.add(part);
    part.rotation.z += HEAD_ACCESSORY_Z_ROTATION;
    part.updateMatrixWorld(true);
  }
}

function mountConfiguredBagCharm(record) {
  const backpack = [...loadedParts.values()].find(r => r.desc.folder === 'Bg');
  const fit = (appearanceFit.BAGWEAR_OFFSET_CONF || []).find(r => r.BagWearName === modelAssetName(backpack));
  const anchor = fit && masterSkeletonScene && findBoneByName(masterSkeletonScene, 'Bone_Bag_20');
  if (!anchor) return false;
  const part = record.object;
  if (!part.userData.nrcAuthoredMatrix) { part.updateMatrix(); part.userData.nrcAuthoredMatrix = part.matrix.clone(); }
  anchor.add(part);
  gameFitMatrix(fit.Offset).multiply(part.userData.nrcAuthoredMatrix).decompose(part.position, part.quaternion, part.scale);
  part.updateMatrixWorld(true);
  part.userData.nrcAppearanceFit = { backpack: modelAssetName(backpack), offset: fit.Offset };
  return true;
}

function mountIndependentAccessory(desc, part) {
  const anchor = masterSkeletonScene && (findBoneByName(masterSkeletonScene, desc.attachToBone)
    || findBoneByName(masterSkeletonScene, desc.folder === 'Mw' ? 'Bip001-R-Hand' : 'Bip001-Spine1'));
  if (!anchor) {
    modelGroup.add(part);
    console.warn(`[preview] attachment anchor unavailable for ${desc.folder}`);
    return;
  }
  anchor.add(part);
  part.position.set(0, 0, 0);
  modelGroup.updateWorldMatrix(true, true);
  // PC3 retains its own internal rig. Keep its authored upright axis in this static preview.
  part.quaternion.copy(anchor.getWorldQuaternion(new THREE.Quaternion())).invert()
    .multiply(modelGroup.getWorldQuaternion(new THREE.Quaternion()));
  if (desc.folder === 'Bi') {
    const backpack = [...loadedParts.values()].find(r => r.desc.folder === 'Bg');
    const target = anchor.getWorldPosition(new THREE.Vector3());
    if (backpack) {
      const box = new THREE.Box3().setFromObject(backpack.object);
      target.set(box.min.x + (box.max.x - box.min.x) * 0.75,
        box.min.y + (box.max.y - box.min.y) * 0.65, box.min.z - 0.015);
    } else {
      target.add(new THREE.Vector3(0, 0, -0.18)
        .applyQuaternion(modelGroup.getWorldQuaternion(new THREE.Quaternion())));
    }
    part.position.copy(anchor.worldToLocal(target));
  }
  modelGroup.updateMatrixWorld(true);
  part.traverse(obj => {
    if (!obj.isSkinnedMesh) return;
    obj.skeleton.update();
    obj.computeBoundingBox();
  });
}

function alignDolphinAccessory(record) {
  if (!['12150001', '22150001'].includes(String(record.desc.textureId))) return;
  const hair = [...loadedParts.values()].find(r => r.desc.folder === 'Hr');
  const face = loadedParts.get('base:Fe');
  const reference = hair || face;
  if (!reference || !record.object.parent) return;
  modelGroup.updateWorldMatrix(true, true);
  const referenceTop = new THREE.Box3().setFromObject(reference.object).max.y;
  const bottom = new THREE.Box3().setFromObject(record.object).min.y;
  const target = record.object.getWorldPosition(new THREE.Vector3());
  target.y += referenceTop + (hair ? -0.025 : 0.045) - bottom;
  record.object.position.copy(record.object.parent.worldToLocal(target));
  record.object.updateWorldMatrix(true, true);
}

function resetHeadwearAttachment(record) {
  const part = record.object;
  const anchor = masterSkeletonScene && findBoneByName(masterSkeletonScene, HEAD_BONE_NAME);
  (anchor || modelGroup).add(part);
  (part.userData.nrcAuthoredMatrix || new THREE.Matrix4()).decompose(part.position, part.quaternion, part.scale);
  delete part.userData.nrcAppearanceFit;
  part.updateMatrixWorld(true);
}

function refreshAccessoryAttachments() {
  for (const record of loadedParts.values()) {
    if (record.desc.folder === 'Mw' || record.desc.folder === 'Bi') {
      if (record.desc.folder !== 'Bi' || !mountConfiguredBagCharm(record)) mountIndependentAccessory(record.desc, record.object);
    }
    if (record.desc.folder === 'Hi' && !mountConfiguredHeadwear(record)) {
      resetHeadwearAttachment(record);
      alignDolphinAccessory(record);
    }
  }
}
function getDesiredPartDescs(selected, gender) {
  const entries = Object.entries(selected || {});
  const partDescs = entries
    .map(([slotKey, { item, source }]) => getModelUrl(gender, slotKey, item, source, selected))
    .filter(Boolean);
  const basePartDescs = gender === 1
    ? getPC1BaseParts(selected)
    : getPC2BaseParts(selected);
  return [...basePartDescs, ...partDescs];
}

function getDescSignature(desc) {
  return JSON.stringify({
    primary: desc.primary,
    fallback: desc.fallback || null,
    g: desc.g || null,
    folder: desc.folder || null,
    textureId: desc.textureId || null,
    bodySkinTextureId: desc.bodySkinTextureId || null,
    attachToBone: desc.attachToBone || null,
    materialTextures: desc.materialTextures || null,
  });
}

function resetPreviewGroup() {
  if (modelGroup) {
    scene.remove(modelGroup);
    disposeGroup(modelGroup);
  }
  modelGroup = null;
  masterSkeletonScene = null;
  skeletonContext = null;
  loadedParts = new Map();
  currentGender = null;
}

function getPreviewRequestSignature(gender, desiredDescs) {
  const parts = desiredDescs
    .map(desc => [desc.key, getDescSignature(desc)])
    .sort((a, b) => a[0].localeCompare(b[0]));
  return JSON.stringify({ gender, parts });
}

async function ensurePreviewGroup(gender, serial) {
  if (modelGroup && currentGender === gender && skeletonContext) return true;

  const nextGroup = new THREE.Group();
  const nextSkeleton = await loadMasterSkeleton(gender);
  if (serial !== loadSerial) {
    if (nextSkeleton) disposeGroup(nextSkeleton);
    disposeGroup(nextGroup);
    return false;
  }
  resetPreviewGroup();
  modelGroup = nextGroup;
  currentGender = gender;
  masterSkeletonScene = nextSkeleton;
  if (masterSkeletonScene) {
    modelGroup.add(masterSkeletonScene);
    skeletonContext = createSkeletonContext(masterSkeletonScene);
  }
  scene.add(modelGroup);
  return true;
}

function removeLoadedPart(key) {
  const record = loadedParts.get(key);
  if (!record) return;
  record.object.parent?.remove(record.object);
  disposeGroup(record.object);
  loadedParts.delete(key);
}

function addLoadedPart(desc, signature, part) {
  if (desc.folder === 'Hi' || desc.folder === 'Bi') { part.updateMatrix(); part.userData.nrcAuthoredMatrix = part.matrix.clone(); }
  const independentRig = desc.folder === 'Mw' || desc.folder === 'Bi';
  if (skeletonContext && !independentRig) rebindSkinnedMeshesToSkeleton(part, skeletonContext);
  if (independentRig) {
    mountIndependentAccessory(desc, part);
  } else if (desc.attachToBone === HEAD_BONE_NAME) {
    mountHeadAccessories(modelGroup, [part]);
  } else modelGroup.add(part);
  loadedParts.set(desc.key, {
    object: part,
    signature,
    desc: { ...desc },
    modelUrl: part.userData?.nrcPreview?.modelUrl || desc.primary,
  });
}

function serializeTextureCandidate(candidate) {
  const options = normalizeTextureCandidate(candidate);
  if (!options?.url) return null;
  const out = { url: options.url };
  if (options.uvRepeat) out.uvRepeat = options.uvRepeat;
  if (options.colorSpace) out.colorSpace = options.colorSpace;
  if (options.filter) out.filter = options.filter;
  if (options.wrap) out.wrap = options.wrap;
  const overlayUrl = options.overlay?.url || options.overlayTexture?.userData?.nrcUrl;
  if (overlayUrl) out.overlay = { url: overlayUrl };
  return out;
}

function serializeTextureDef(def) {
  const list = Array.isArray(def) ? def : [def];
  return list.map(serializeTextureCandidate).filter(Boolean);
}

function getMaterialTextureDefs(desc) {
  if (!desc.materialTextures) return [];
  return Object.entries(desc.materialTextures).map(([material, def]) => ({
    material,
    candidates: serializeTextureDef(def),
  }));
}

function getTextureRule(desc, modelUrl) {
  if (!desc.g || !desc.folder || !desc.textureId) return null;
  if (desc.bodySkinTextureId) {
    return {
      mode: 'material-slot',
      note: 'By 材质槽使用当前肤色贴图；其他材质槽优先使用当前模型目录 Tex。',
      modelDirectoryPattern: `${getModelDir(modelUrl)}/Tex/T_${desc.g}_${desc.folder}_${desc.textureId}_D.png`,
      bodySkinTextureId: desc.bodySkinTextureId,
    };
  }
  return {
    mode: 'material-slot',
    note: '根据材质名中的部位和 ID 生成贴图候选，优先使用当前模型目录 Tex。',
    modelDirectoryPattern: `${getModelDir(modelUrl)}/Tex/T_${desc.g}_${desc.folder}_${desc.textureId}_D.png`,
  };
}

function getLoadedMaterialManifest(record) {
  if (!record?.object) return [];
  const rows = [];
  record.object.traverse(obj => {
    if (!obj.isMesh && !obj.isSkinnedMesh) return;
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
    mats.filter(Boolean).forEach((material, index) => {
      const candidates = record.desc && record.modelUrl
        ? textureCandidatesForMaterial(material, record.desc, record.modelUrl).map(serializeTextureCandidate).filter(Boolean)
        : [];
      const baseTextureUrl = material.userData?.nrcBaseTextureUrl || material.map?.userData?.nrcUrl || null;
      const overlayTextureUrl = material.userData?.nrcOverlayTextureUrl || null;
      rows.push({
        mesh: obj.name || null,
        material: material.name || null,
        materialIndex: index,
        materialSlot: parseMaterialSlot(material.name),
        baseTexture: baseTextureUrl ? { url: baseTextureUrl } : null,
        overlayTexture: overlayTextureUrl ? { url: overlayTextureUrl } : null,
        uvRepeat: material.userData?.nrcTextureOptions?.uvRepeat || null,
        candidates,
      });
    });
  });
  return rows;
}

function getPartManifest(desc) {
  const record = loadedParts.get(desc.key);
  const modelUrl = record?.modelUrl || desc.primary;
  return {
    key: desc.key,
    kind: desc.key?.startsWith('base:') ? 'base' : 'slot',
    slot: desc.key?.startsWith('slot:') ? desc.key.slice(5) : null,
    basePart: desc.key?.startsWith('base:') ? desc.key.slice(5) : null,
    loaded: !!record,
    model: {
      primaryUrl: desc.primary,
      fallbackUrl: desc.fallback || null,
      loadedUrl: modelUrl,
      folder: desc.folder || null,
      textureId: desc.textureId || null,
      bodySkinTextureId: desc.bodySkinTextureId || null,
      attachToBone: desc.attachToBone || null,
    },
    manualTextures: getMaterialTextureDefs(desc),
    textureRule: getTextureRule(desc, modelUrl),
    loadedMaterials: getLoadedMaterialManifest(record),
  };
}

function buildPreviewManifest(selected, gender) {
  const g = `PC${gender}`;
  const desiredDescs = getDesiredPartDescs(selected, gender);
  return {
    gender,
    character: g,
    masterSkeleton: {
      url: buildMasterSkeletonUrl(g),
      loaded: currentGender === gender && !!masterSkeletonScene,
    },
    parts: desiredDescs.map(getPartManifest),
  };
}
// ── 对外接口：更新预览 ────────────────────────────────────────
async function updatePreview(selected, gender) {
  await appearanceFitReady;
  await unreleasedReady;
  const desiredDescs = getDesiredPartDescs(selected, gender);
  const requestSignature = getPreviewRequestSignature(gender, desiredDescs);
  if (requestSignature === lastPreviewRequestSignature) return;
  lastPreviewRequestSignature = requestSignature;

  const serial = ++loadSerial;
  setStatus('加载中…');

  console.log('[preview] incremental update', desiredDescs.length, 'parts, gender', gender);
  if (serial !== loadSerial) return;
  const ready = await ensurePreviewGroup(gender, serial);
  if (!ready || serial !== loadSerial) return;

  const desiredByKey = new Map(desiredDescs.map(desc => [desc.key, desc]));
  for (const key of [...loadedParts.keys()]) {
    if (!desiredByKey.has(key)) removeLoadedPart(key);
  }

  const jobs = [];
  for (const desc of desiredDescs) {
    const signature = getDescSignature(desc);
    const current = loadedParts.get(desc.key);
    if (current?.signature === signature) continue;
    removeLoadedPart(desc.key);
    jobs.push({ desc, signature, promise: loadPart(desc) });
  }

  const results = await Promise.all(jobs.map(async job => ({ ...job, part: await job.promise })));
  if (serial !== loadSerial) {
    results.forEach(({ part }) => { if (part) disposeGroup(part); });
    return;
  }

  let failedCount = 0;
  for (const { desc, signature, part } of results) {
    if (!part) {
      failedCount++;
      continue;
    }
    addLoadedPart(desc, signature, part);
  }
  refreshAccessoryAttachments();
  reportChromaSupport();
  const missingDescs = desiredDescs.filter(desc => !loadedParts.has(desc.key));
  const hairFallback = [...loadedParts.values()].some(r => r.object.userData.nrcHairFallback);
  setStatus(previewStatusText(missingDescs, loadedParts.size, hairFallback));
}
// 挂载到全局，供 app.js 调用
window.updatePreview = updatePreview;
window.buildPreviewManifest = buildPreviewManifest;

// 若 app.js 的 init() 已完成，立即拉取当前状态渲染一次
if (window._getPreviewState) {
  const { selected, gender } = window._getPreviewState();
  updatePreview(selected, gender);
}





































