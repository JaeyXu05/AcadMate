export type GalaxyLayer = 'fine' | 'mist';

export interface GalaxyDust {
  positions: Float32Array;
  colors: Float32Array;
  /** 0 = spiral arm, 1 = orbital band, 2 = diffuse halo. */
  families: Uint8Array;
}

export const GALAXY_BACKGROUND = {
  innerRadius: 54,
  outerRadius: 780,
  turns: 1.88,
  arms: 5,
} as const;

const TAU = Math.PI * 2;
const ARM_COLORS = [
  [0.08, 0.72, 1],
  [0.24, 0.38, 1],
  [0.61, 0.18, 1],
  [1, 0.12, 0.58],
  [0.04, 0.94, 0.66],
] as const;
const BAND_COLORS = [
  [0.1, 0.68, 1],
  [0.32, 0.34, 1],
  [0.66, 0.18, 1],
  [0.04, 0.9, 0.68],
  [0.88, 0.2, 0.92],
] as const;
const BAND_RADII = [0.2, 0.35, 0.52, 0.7, 0.9] as const;

function seededRandom(seed: number) {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let result = value;
    result = Math.imul(result ^ (result >>> 15), result | 1);
    result ^= result + Math.imul(result ^ (result >>> 7), result | 61);
    return ((result ^ (result >>> 14)) >>> 0) / 4294967296;
  };
}

function normal(random: () => number): number {
  const left = Math.max(1e-7, random());
  const right = Math.max(1e-7, random());
  return Math.sqrt(-2 * Math.log(left)) * Math.cos(TAU * right);
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function paletteColor(
  palette: readonly (readonly [number, number, number])[],
  position: number,
): readonly [number, number, number] {
  const wrapped = ((position % palette.length) + palette.length) % palette.length;
  const leftIndex = Math.floor(wrapped);
  const rightIndex = (leftIndex + 1) % palette.length;
  const rawMix = wrapped - leftIndex;
  const mix = rawMix * rawMix * (3 - 2 * rawMix);
  const left = palette[leftIndex];
  const right = palette[rightIndex];
  return [
    left[0] + (right[0] - left[0]) * mix,
    left[1] + (right[1] - left[1]) * mix,
    left[2] + (right[2] - left[2]) * mix,
  ];
}

/**
 * A small coherent error field. Harmonics keep neighbouring samples related while
 * the seed changes their phase, avoiding both a mathematically perfect spiral and
 * unbounded white-noise scatter.
 */
export function galaxyError(progress: number, angle: number, seed: number): number {
  const phase = (seed % 997) * 0.0137;
  return (
    Math.sin(progress * TAU * 2.3 + angle * 0.42 + phase) * 0.58
    + Math.sin(progress * TAU * 5.1 - angle * 0.19 + phase * 1.71) * 0.27
    + Math.sin(progress * TAU * 9.7 + angle * 0.11 - phase * 0.63) * 0.15
  );
}

function writeColor(
  colors: Float32Array,
  index: number,
  base: readonly [number, number, number],
  radiusProgress: number,
  random: () => number,
  layer: GalaxyLayer,
  localBrightness: number,
) {
  const innerLight = Math.pow(1 - radiusProgress, 2) * 0.2;
  const strength = ((layer === 'mist' ? 0.52 : 0.6) + random() * 0.34) * localBrightness;
  const coolCore: readonly [number, number, number] = [0.72, 0.9, 1];
  const quietBlue: readonly [number, number, number] = [0.36, 0.52, 0.82];
  const saturationMix = 0.78;
  const red = base[0] * saturationMix + quietBlue[0] * (1 - saturationMix);
  const green = base[1] * saturationMix + quietBlue[1] * (1 - saturationMix);
  const blue = base[2] * saturationMix + quietBlue[2] * (1 - saturationMix);
  colors[index * 3] = clamp((red * (1 - innerLight) + coolCore[0] * innerLight) * strength, 0, 1);
  colors[index * 3 + 1] = clamp((green * (1 - innerLight) + coolCore[1] * innerLight) * strength, 0, 1);
  colors[index * 3 + 2] = clamp((blue * (1 - innerLight) + coolCore[2] * innerLight) * strength, 0, 1);
}

/**
 * Builds a deterministic galaxy from three overlapping distributions:
 * five perturbed spiral arms, five imperfect orbital bands and a diffuse halo.
 * The result is static GPU data; no particle objects are created per frame.
 */
export function createGalaxyDust(count: number, seed: number, layer: GalaxyLayer): GalaxyDust {
  const random = seededRandom(seed);
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const families = new Uint8Array(count);
  const mistScale = layer === 'mist' ? 1.55 : 1;

  for (let index = 0; index < count; index += 1) {
    const choice = random();
    let radius = 0;
    let theta = 0;
    let vertical = 0;
    let radiusProgress = 0;
    let localBrightness = 1;
    let color: readonly [number, number, number];

    if (choice < 0.64) {
      families[index] = 0;
      const arm = Math.floor(random() * GALAXY_BACKGROUND.arms);
      const progress = 0.025 + random() * 0.975;
      const baseRadius = GALAXY_BACKGROUND.innerRadius
        + (GALAXY_BACKGROUND.outerRadius - GALAXY_BACKGROUND.innerRadius) * Math.pow(progress, 1.16);
      const armPhase = (arm * TAU) / GALAXY_BACKGROUND.arms;
      const pitchVariation = 0.94 + arm * 0.023;
      const coherent = galaxyError(progress, armPhase, seed + arm * 73);
      theta = armPhase + progress * GALAXY_BACKGROUND.turns * TAU * pitchVariation + coherent * 0.13;

      const armWidth = (14 + 44 * Math.pow(progress, 1.25)) * mistScale;
      const lateralSample = clamp(normal(random), -3.1, 3.1);
      const lateralError = lateralSample * armWidth;
      const radialError = clamp(normal(random), -2.5, 2.5) * (3.5 + progress * 8.5)
        + coherent * (5 + progress * 8);
      radius = baseRadius + radialError;
      theta += lateralError / Math.max(radius, 40);
      vertical = clamp(normal(random), -2.8, 2.8) * (2.4 + progress * 7.5) * mistScale
        + Math.sin(theta * 1.7 + arm) * 2.2;
      radiusProgress = progress;
      // Brightness fades continuously away from the arm ridge. Combined with
      // Gaussian sampling, this lets density and luminance reveal the arm.
      localBrightness = 0.46 + Math.exp(-0.72 * lateralSample * lateralSample) * 0.54;
      // The colour changes gradually along each arm, creating readable cyan,
      // blue, violet and magenta passages instead of a striped rainbow.
      color = paletteColor(ARM_COLORS, arm * 0.72 + progress * 2.35);
    } else if (choice < 0.82) {
      families[index] = 1;
      const band = Math.floor(random() * BAND_RADII.length);
      const bandProgress = BAND_RADII[band];
      theta = random() * TAU;
      const coherent = galaxyError(bandProgress, theta, seed + band * 131);
      const baseRadius = GALAXY_BACKGROUND.innerRadius
        + (GALAXY_BACKGROUND.outerRadius - GALAXY_BACKGROUND.innerRadius) * bandProgress;
      radius = baseRadius
        + coherent * (7 + bandProgress * 13)
        + clamp(normal(random), -2.8, 2.8) * (10 + bandProgress * 17) * mistScale;
      vertical = clamp(normal(random), -2.7, 2.7) * (3.5 + bandProgress * 7.5) * mistScale;
      radiusProgress = bandProgress;
      localBrightness = 0.48 + random() * 0.18;
      color = BAND_COLORS[band];
    } else {
      families[index] = 2;
      // Bias the quiet inter-arm dust slightly towards the core so the arm
      // ridges emerge gradually instead of being separated by empty channels.
      radiusProgress = Math.pow(random(), 1.18);
      radius = GALAXY_BACKGROUND.innerRadius * 0.7
        + GALAXY_BACKGROUND.outerRadius * 1.13 * radiusProgress;
      theta = random() * TAU + galaxyError(radiusProgress, random() * TAU, seed + 887) * 0.08;
      vertical = clamp(normal(random), -2.8, 2.8) * (13 + radiusProgress * 34) * mistScale;
      const haloIndex = Math.floor(random() * BAND_COLORS.length);
      color = BAND_COLORS[haloIndex];
      localBrightness = 0.28 + random() * 0.24;
    }

    positions[index * 3] = radius * Math.cos(theta);
    positions[index * 3 + 1] = vertical;
    positions[index * 3 + 2] = radius * Math.sin(theta);
    writeColor(colors, index, color, radiusProgress, random, layer, localBrightness);
  }

  return { positions, colors, families };
}

/** A broad, broken nebula band inspired by the reference video's lateral particle clouds. */
export function createNebulaDust(count: number, seed: number): GalaxyDust {
  const random = seededRandom(seed);
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const families = new Uint8Array(count);
  const centers = [-0.88, -0.5, -0.16, 0.18, 0.52, 0.86] as const;

  for (let index = 0; index < count; index += 1) {
    const cluster = Math.floor(random() * centers.length);
    const center = centers[cluster];
    const horizontal = clamp(normal(random), -2.8, 2.8);
    const local = center + horizontal * 0.14;
    const warp = galaxyError((local + 1.2) / 2.4, cluster * 0.7, seed + cluster * 97);
    const depth = clamp(normal(random), -2.7, 2.7);
    const x = local * 760;
    const z = depth * (48 + Math.abs(center) * 24) + warp * 62 + Math.sin(local * Math.PI * 2.4) * 28;
    const y = clamp(normal(random), -2.6, 2.6) * (18 + Math.abs(warp) * 12);
    positions[index * 3] = x;
    positions[index * 3 + 1] = y;
    positions[index * 3 + 2] = z;
    families[index] = 2;

    const base = BAND_COLORS[(cluster + 1) % BAND_COLORS.length];
    const fade = (0.56 + random() * 0.42) * (0.72 + (1 - Math.min(1, Math.abs(local))) * 0.28);
    colors[index * 3] = base[0] * fade;
    colors[index * 3 + 1] = base[1] * fade;
    colors[index * 3 + 2] = base[2] * fade;
  }

  return { positions, colors, families };
}
