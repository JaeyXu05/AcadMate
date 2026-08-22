import assert from 'node:assert/strict';
import { markdownExportFilename } from '../src/utils/markdownExport.ts';

assert.equal(markdownExportFilename('Deliberation in Latent Space via Differentiable Cache Augmentation'), 'deliberation-in-latent-space-via-differentiable-cache-augmentation.md');
assert.equal(markdownExportFilename('Deliberation in Latent Space via Differentiable Cache Augmentation', { report: true }), 'deliberation-in-latent-space-via-differentiable-cache-augmentation-report.md');
assert.equal(markdownExportFilename('  A/B: C?  D  '), 'a-b-c-d.md');
assert.equal(markdownExportFilename('中文 论文'), '中文-论文.md');
assert.equal(markdownExportFilename(''), 'paper.md');
