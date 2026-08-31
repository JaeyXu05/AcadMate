import assert from 'node:assert/strict';
import test from 'node:test';
import { createGalaxyDust, createNebulaDust, GALAXY_BACKGROUND, galaxyError } from './galaxyBackground';

test('galaxy dust is deterministic and contains arms, bands, and halo', () => {
  const first = createGalaxyDust(5000, 107, 'fine');
  const second = createGalaxyDust(5000, 107, 'fine');
  assert.deepEqual(first.positions, second.positions);
  assert.deepEqual(first.colors, second.colors);

  const familyCounts = [0, 0, 0];
  for (const family of first.families) familyCounts[family] += 1;
  assert.ok(familyCounts[0] > 3000, `spiral particles: ${familyCounts[0]}`);
  assert.ok(familyCounts[1] > 600, `band particles: ${familyCounts[1]}`);
  assert.ok(familyCounts[2] > 400, `halo particles: ${familyCounts[2]}`);
});

test('coherent error stays bounded and does not collapse to one sine wave', () => {
  const samples = Array.from({ length: 120 }, (_, index) => (
    galaxyError(index / 119, index * 0.17, 401)
  ));
  assert.ok(samples.every((value) => value >= -1 && value <= 1));
  assert.ok(Math.max(...samples) - Math.min(...samples) > 1.1);
  const uniqueRounded = new Set(samples.map((value) => value.toFixed(3)));
  assert.ok(uniqueRounded.size > 90);
});

test('generated positions remain finite and within the intended layered galaxy', () => {
  const dust = createGalaxyDust(6000, 401, 'mist');
  let maximumRadius = 0;
  for (let index = 0; index < dust.positions.length / 3; index += 1) {
    const x = dust.positions[index * 3];
    const y = dust.positions[index * 3 + 1];
    const z = dust.positions[index * 3 + 2];
    assert.ok(Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z));
    maximumRadius = Math.max(maximumRadius, Math.hypot(x, z));
  }
  assert.ok(maximumRadius > GALAXY_BACKGROUND.outerRadius);
  assert.ok(maximumRadius < GALAXY_BACKGROUND.outerRadius * 1.2);

  const uniqueColors = new Set<string>();
  for (let index = 0; index < dust.colors.length; index += 3) {
    uniqueColors.add(`${dust.colors[index].toFixed(2)},${dust.colors[index + 1].toFixed(2)},${dust.colors[index + 2].toFixed(2)}`);
  }
  assert.ok(uniqueColors.size > 80);
});

test('nebula dust forms a deterministic wide but shallow broken band', () => {
  const first = createNebulaDust(2400, 781);
  const second = createNebulaDust(2400, 781);
  assert.deepEqual(first.positions, second.positions);
  let maximumX = 0;
  let maximumZ = 0;
  for (let index = 0; index < first.positions.length; index += 3) {
    maximumX = Math.max(maximumX, Math.abs(first.positions[index]));
    maximumZ = Math.max(maximumZ, Math.abs(first.positions[index + 2]));
  }
  assert.ok(maximumX > 650);
  assert.ok(maximumZ > 120);
  assert.ok(maximumX > maximumZ * 2.5);
});
