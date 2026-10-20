export const chromaDataReady = fetch('/chroma-data.json')
  .then(r => { if (!r.ok) throw Error('chroma data'); return r.json(); })
  .catch(() => ({ presets: [], materials: {} }));
let activePreset = null;
export function getActiveChromaPreset() { return activePreset; }
export function selectChromaPreset(preset) {
  activePreset = preset;
  window.dispatchEvent(new CustomEvent('nrc-chroma-change', { detail: preset }));
}
