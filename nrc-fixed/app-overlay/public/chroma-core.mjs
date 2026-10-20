export function getChromaMask(name, materials, textureId) {
  const base = String(name || '').toLowerCase();
  const variant = textureId ? base.replace(/\d{6,}/, String(textureId)) : base;
  return materials?.[variant]?.mask || materials?.[base]?.mask || null;
}
export function advanceChromaFlow(uniforms, deltaSeconds) {
  if (!Number.isFinite(deltaSeconds) || deltaSeconds <= 0 || !uniforms.nrcChromaEnabled.value) return;
  const speed = uniforms.nrcChromaFlowSpeed?.value, offset = uniforms.nrcChromaFlowOffset?.value;
  if (speed && offset) for (let i = 0; i < 2; i++) {
    const next = offset[i] + speed[i] * deltaSeconds;
    offset[i] = ((next % 1) + 1) % 1;
  }
  if (uniforms.nrcChromaStickPhase) uniforms.nrcChromaStickPhase.value = (uniforms.nrcChromaStickPhase.value + deltaSeconds * 0.25) % 1;
  // Same 0.25 / s phase as the stick reveal, taken from the decoded shader (time * 0.25 -> 4 s period).
  if (uniforms.nrcChromaSparklePhase) uniforms.nrcChromaSparklePhase.value = (uniforms.nrcChromaSparklePhase.value + deltaSeconds * 0.25) % 1;
}
export function updateChromaUniforms(uniforms, preset) {
  if (uniforms.nrcChromaFlowOffset) uniforms.nrcChromaFlowOffset.value = [0, 0];
  if (uniforms.nrcChromaFlowSpeed) uniforms.nrcChromaFlowSpeed.value = [0, 0];
  if (uniforms.nrcChromaStickPhase) uniforms.nrcChromaStickPhase.value = 0;
  if (uniforms.nrcChromaStickOffset) uniforms.nrcChromaStickOffset.value = [0, 0];
  if (uniforms.nrcChromaStickSpeed) uniforms.nrcChromaStickSpeed.value = [0, 0];
  if (uniforms.nrcChromaStickIntensity) uniforms.nrcChromaStickIntensity.value = 0;
  if (uniforms.nrcChromaSparklePhase) uniforms.nrcChromaSparklePhase.value = 0;
  if (uniforms.nrcChromaSparkleIntensity) uniforms.nrcChromaSparkleIntensity.value = 0;
  if (uniforms.nrcChromaSparkleDensity) uniforms.nrcChromaSparkleDensity.value = 0;
  if (uniforms.nrcChromaSparkleTiling) uniforms.nrcChromaSparkleTiling.value = 1;
  const valid = color => Array.isArray(color) && color.length === 3 && color.every(v => Number.isFinite(v) && v >= 0 && v <= 4);
  if (!preset || !valid(preset.mat_color_1) || !valid(preset.mat_color_2)) {
    uniforms.nrcChromaEnabled.value = 0;
    return;
  }
  uniforms.nrcChromaColor1.value = [...preset.mat_color_1];
  uniforms.nrcChromaColor2.value = [...preset.mat_color_2];
  if (uniforms.nrcChromaTiling) uniforms.nrcChromaTiling.value = Number.isFinite(preset.tiling) && preset.tiling > 0 ? preset.tiling : 1;
  if (uniforms.nrcChromaFlowSpeed && Array.isArray(preset.flow) && preset.flow.length === 2 && preset.flow.every(Number.isFinite)) {
    uniforms.nrcChromaFlowSpeed.value = [...preset.flow];
  }
  const stick = preset.ornament;
  if (stick && stick.colors?.length === 4 && stick.colors.every(valid)) {
    if (uniforms.nrcChromaStickTiling) uniforms.nrcChromaStickTiling.value = Number.isFinite(stick.tiling) && stick.tiling > 0 ? stick.tiling : 4;
    if (uniforms.nrcChromaStickIntensity) uniforms.nrcChromaStickIntensity.value = Number.isFinite(stick.intensity) ? Math.max(0, stick.intensity) : 0;
    if (uniforms.nrcChromaStickColors) uniforms.nrcChromaStickColors.value = new Float32Array(stick.colors.flat());
    if (uniforms.nrcChromaStickSpeed && stick.flow?.length === 2 && stick.flow.every(Number.isFinite)) uniforms.nrcChromaStickSpeed.value = [...stick.flow];
    // Game values are StarIntensity (0-10 seen so far) and StarDensity (0-20), where the shader builds its
    // star grid from the UV scaled by the density. Brightness is normalised to 0-1 so the layer stays in
    // range without the game's HDR post; density keeps the game's cell count.
    const sparkleBrightness = Number.isFinite(stick.sparkle_intensity) ? Math.min(Math.max(stick.sparkle_intensity / 10, 0), 1) : 0;
    if (uniforms.nrcChromaSparkleIntensity) uniforms.nrcChromaSparkleIntensity.value = sparkleBrightness;
    if (uniforms.nrcChromaSparkleDensity) uniforms.nrcChromaSparkleDensity.value = Number.isFinite(stick.sparkle_density) && stick.sparkle_density > 0 ? stick.sparkle_density : 8;
    if (uniforms.nrcChromaSparkleTiling) uniforms.nrcChromaSparkleTiling.value = Number.isFinite(stick.sparkle_tiling) && stick.sparkle_tiling > 0 ? stick.sparkle_tiling : 1;
  }
  uniforms.nrcChromaEnabled.value = 1;
}
export function patchChromaShader(shader, uniforms, mask, pattern) {
  Object.assign(shader.uniforms, uniforms, {
    nrcChromaMask: { value: mask },
    nrcChromaPattern: uniforms.nrcChromaPattern || { value: pattern },
    nrcChromaTiling: uniforms.nrcChromaTiling || { value: 1 },
    nrcChromaFlowOffset: uniforms.nrcChromaFlowOffset || { value: [0, 0] },
    nrcChromaSparklePhase: uniforms.nrcChromaSparklePhase || { value: 0 },
    nrcChromaSparkleIntensity: uniforms.nrcChromaSparkleIntensity || { value: 0 },
    nrcChromaSparkleDensity: uniforms.nrcChromaSparkleDensity || { value: 0 },
    nrcChromaSparkleTiling: uniforms.nrcChromaSparkleTiling || { value: 1 },
    nrcChromaSpecIntensity: uniforms.nrcChromaSpecIntensity || { value: 0.35 },
    nrcChromaSpecPow: uniforms.nrcChromaSpecPow || { value: 24 },
  });
  shader.fragmentShader = shader.fragmentShader.replace('void main() {', `
    uniform sampler2D nrcChromaMask;
    uniform sampler2D nrcChromaStickTexture;
    uniform float nrcChromaStickPhase;
    uniform float nrcChromaStickTiling;
    uniform float nrcChromaStickIntensity;
    uniform vec3 nrcChromaStickColors[4];
    uniform float nrcChromaSparklePhase;
    uniform float nrcChromaSparkleIntensity;
    uniform float nrcChromaSparkleDensity;
    uniform float nrcChromaSparkleTiling;
    uniform float nrcChromaSpecIntensity;
    uniform float nrcChromaSpecPow;
    uniform sampler2D nrcChromaPattern;
    uniform float nrcChromaEnabled;
    uniform float nrcChromaTiling;
    uniform vec2 nrcChromaFlowOffset;
    uniform vec3 nrcChromaColor1;
    uniform vec3 nrcChromaColor2;
    void main() {`);
  shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `#include <map_fragment>
    #ifdef USE_MAP
      if (nrcChromaEnabled > 0.5) {
        float nrcCoverage = clamp(texture2D(nrcChromaMask, vMapUv).r, 0.0, 1.0);
        vec2 nrcPattern = texture2D(nrcChromaPattern, vMapUv * nrcChromaTiling + nrcChromaFlowOffset).rg;
        float nrcLightness = dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722));
        vec3 nrcPalette = (nrcChromaColor1 * nrcPattern.r + nrcChromaColor2 * nrcPattern.g) / max(nrcPattern.r + nrcPattern.g, 0.0001);
        diffuseColor.rgb = mix(diffuseColor.rgb, nrcLightness * nrcPalette, nrcCoverage);
        if (nrcChromaStickIntensity > 0.0) {
          // ShaderArchive NRC / star-lion Glassy map / pixel shader 46590, DXBC lines 261-294.
          // Shape UV stays anchored. A periodic threshold reveals the packed R/G/B artwork.
          vec3 nrcStick = texture2D(nrcChromaStickTexture, vMapUv * nrcChromaStickTiling).rgb;
          float nrcTheta = nrcChromaStickPhase * 6.28318530718;
          float nrcReveal = mix(1.1 * abs(sin(nrcTheta)), 1.1 * abs(cos(nrcTheta)), nrcStick.g);
          float nrcColorPhase = clamp(nrcReveal, 0.0, 1.0) * 3.0;
          vec3 nrcStickColor = mix(nrcChromaStickColors[0], nrcChromaStickColors[1], min(nrcColorPhase, 1.0));
          nrcStickColor = mix(nrcStickColor, nrcChromaStickColors[2], clamp(nrcColorPhase - 1.0, 0.0, 1.0));
          nrcStickColor = mix(nrcStickColor, nrcChromaStickColors[3], max(nrcColorPhase - 2.0, 0.0));
          float nrcStickMask = smoothstep(0.01, 0.05, nrcStick.b * (nrcReveal - nrcStick.r));
          vec3 nrcStickLayer = nrcStickMask * nrcStickColor * nrcChromaStickIntensity * nrcLightness;
          diffuseColor.rgb = mix(diffuseColor.rgb, nrcStickLayer, nrcCoverage * nrcStickMask);
        }
        if (nrcChromaSparkleIntensity > 0.0) {
          // Pixel shader 46590 star branch: it samples the star artwork (StarStickTex) with a
          // time-scrolled UV - the shader multiplies time by (0.0056, 0.25) and takes the fraction -
          // and drives brightness from StarIntensity, density from StarDensity. The preview keeps that
          // artwork and those rates instead of inventing dots: the B channel carries the star / speckle
          // shapes, the G channel the large mask, so the fine glitter is the game texture repeated at the
          // branch's UV scale (v3.xy * 20 * StarTiling -> tiling * density here).
          // Not reproduced: the random lookup table and the neighbouring-cell loop that add extra stars.
          vec2 nrcGlitterUv = vMapUv * max(nrcChromaSparkleTiling * nrcChromaSparkleDensity, 1.0)
            + vec2(0.0056, 0.25) * (nrcChromaSparklePhase * 4.0);
          vec4 nrcGlitterTex = texture2D(nrcChromaStickTexture, nrcGlitterUv);
          float nrcGlitterShape = clamp(nrcGlitterTex.b, 0.0, 1.0);
          float nrcGlitterTwinkle = 0.55 + 0.45 * sin((nrcChromaSparklePhase * 2.0 + nrcGlitterTex.g) * 6.28318530718);
          vec3 nrcGlitterColor = mix(vec3(1.0), nrcPalette, 0.3);
          diffuseColor.rgb += nrcGlitterShape * nrcChromaSparkleIntensity * nrcGlitterTwinkle * nrcGlitterColor * nrcCoverage;
        }
      }
    #endif`);
  // The sheen needs the shading normal, which three declares later (normal_fragment_begin), so it is
  // injected after that chunk instead of inside map_fragment. Mask and palette are re-sampled here.
  shader.fragmentShader = shader.fragmentShader.replace('#include <normal_fragment_begin>', `#include <normal_fragment_begin>
    #ifdef USE_MAP
      if (nrcChromaEnabled > 0.5) {
        // Glassy sheen: MI_Avatar_Object_Glassy carries SpecIntensity2 = 1, SpecPow2 = 0.6 and MetalSpecInt = 3.
        // Folded into one preview highlight (exponent 24 -> nrcChromaSpecPow) instead of the UE specular lobe.
        // The half vector follows the scene main light (Pitch -70.85 / Yaw -45.68) seen from the preview camera.
        float nrcSheenCoverage = clamp(texture2D(nrcChromaMask, vMapUv).r, 0.0, 1.0);
        vec2 nrcSheenPattern = texture2D(nrcChromaPattern, vMapUv * nrcChromaTiling + nrcChromaFlowOffset).rg;
        vec3 nrcSheenPalette = (nrcChromaColor1 * nrcSheenPattern.r + nrcChromaColor2 * nrcSheenPattern.g) / max(nrcSheenPattern.r + nrcSheenPattern.g, 0.0001);
        float nrcSheen = pow(max(dot(normalize(normal), vec3(-0.146, 0.596, 0.783)), 0.0), nrcChromaSpecPow);
        diffuseColor.rgb += nrcChromaSpecIntensity * nrcSheen * mix(vec3(1.0), nrcSheenPalette, 0.5) * nrcSheenCoverage;
      }
    #endif`);
}
