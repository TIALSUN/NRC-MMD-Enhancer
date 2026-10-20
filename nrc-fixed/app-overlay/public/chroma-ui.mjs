import { chromaDataReady, selectChromaPreset } from './chroma-state.mjs';
const root = document.getElementById('chroma-controls');
const swatches = document.getElementById('chroma-swatches');
const label = document.getElementById('chroma-label');
const hint = document.getElementById('chroma-hint');
const buttons = [...root.querySelectorAll('.chroma-mode-btn')];
const data = await chromaDataReady;
let chosen = data.presets.find(preset => preset.id === 1) || data.presets[0] || null;
let enabled = false;
let supported = 0;
let chosenPattern = data.basic_patterns?.[0];
const shapeGroup = document.createElement('div');
shapeGroup.className = 'hidden'; shapeGroup.id = 'chroma-patterns';
shapeGroup.setAttribute('role', 'group'); shapeGroup.setAttribute('aria-label', '基础炫彩花纹');
swatches.after(shapeGroup);
function effectivePreset() {
  if (!enabled || !chosen) return null;
  if (chosen.source || !chosenPattern) return chosen;
  return { ...chosen, ornament: { ...chosen.ornament, texture: chosenPattern.texture, tiling: chosenPattern.tiling }, pattern_name: chosenPattern.name };
}
function applySelection() { selectChromaPreset(effectivePreset()); }
for (const pattern of data.basic_patterns || []) {
  const btn = document.createElement('button'); btn.type = 'button';
  btn.className = 'chroma-mode-btn'; btn.textContent = pattern.name;
  btn.dataset.patternId = String(pattern.id);
  btn.setAttribute('aria-pressed', String(pattern.id === chosenPattern?.id));
  btn.addEventListener('click', () => { chosenPattern = pattern; applySelection(); render(); });
  if (pattern.icon) { const img = document.createElement('img'); img.src = pattern.icon; img.alt = ''; btn.prepend(img); }
  shapeGroup.appendChild(btn);
}
function render() {
  buttons.forEach(btn => {
    const active = (btn.dataset.chromaMode === 'chroma') === enabled;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', String(active));
    if (btn.dataset.chromaMode === 'chroma') btn.disabled = !data.presets.length || !supported;
  });
  swatches.classList.toggle('hidden', !enabled);
  shapeGroup.classList.toggle('hidden', !enabled || !!chosen?.source);
  shapeGroup.querySelectorAll('button').forEach(btn => { const active = btn.dataset.patternId === String(chosenPattern?.id); btn.setAttribute('aria-pressed', String(active)); btn.classList.toggle('active', active); });
  root.querySelectorAll('.chroma-pattern-overlay').forEach(img => { img.src = chosenPattern?.overlay || ''; });
  const sparkle = chosen?.ornament?.sparkle_intensity > 0 ? ' · 星点' : '';
  const motion = (chosen?.ornament?.motion_source === 'dxbc-46590' ? ' · 花纹显隐' : chosen?.ornament?.flow?.some(value => value !== 0) ? ' · 花纹流动' : chosen?.flow?.some(value => value !== 0) ? ' · 底纹流动' : ' · 静态') + sparkle;
  label.textContent = enabled ? (chosen?.name || '') + (!chosen?.source && chosenPattern ? ' · ' + chosenPattern.name : '') + motion : '原色';
  hint.textContent = !data.presets.length ? '炫彩配色加载失败' : supported ? (enabled && chosen?.reference ? '参考配色 · 花纹显隐与星点按游戏着色器重建' : (enabled ? '花纹显隐按游戏着色器重建 · 星点与光泽为近似 · 光照取自游戏衣柜场景' : '仅对服装可染色区域生效')) : '当前服装暂无可预览的炫彩区域';
  root.querySelectorAll('.chroma-swatch').forEach(btn => btn.setAttribute('aria-pressed', String(enabled && String(chosen?.id) === btn.dataset.paletteId)));
}
for (const preset of data.presets) {
  const btn = document.createElement('button');
  btn.type = 'button'; btn.className = 'chroma-swatch'; btn.dataset.paletteId = String(preset.id);
  btn.title = preset.name; btn.setAttribute('aria-label', preset.name); btn.setAttribute('aria-pressed', 'false');
  btn.style.setProperty('--chroma-first', preset.ui_color_1); btn.style.setProperty('--chroma-second', preset.ui_color_2);
  btn.addEventListener('click', () => { chosen = preset; applySelection(); render(); });
  if (preset.icon) { const img = document.createElement('img'); img.src = preset.icon; img.alt = ''; img.draggable = false; btn.appendChild(img); btn.classList.add('has-game-icon'); }
  if (!preset.source && chosenPattern?.overlay) {
    const overlay = document.createElement('img'); overlay.className = 'chroma-pattern-overlay'; overlay.src = chosenPattern.overlay; overlay.alt = ''; overlay.draggable = false; btn.appendChild(overlay);
  }
  swatches.appendChild(btn);
}
buttons.forEach(btn => btn.addEventListener('click', () => {
  enabled = btn.dataset.chromaMode === 'chroma'; applySelection(); render();
}));
window.addEventListener('nrc-chroma-support', e => { supported = e.detail.count; render(); });
// preview.js may have finished loading before this module's handlers were installed.
supported = window.getChromaSupportCount?.() || 0;
render();

window.addEventListener('nrc-chroma-error', () => { hint.textContent = '配色纹理加载失败，已显示原色'; });
