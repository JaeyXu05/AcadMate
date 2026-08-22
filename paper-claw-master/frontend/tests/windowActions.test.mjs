import assert from 'node:assert/strict';
import { windowRerunActionLabel } from '../src/features/tasks/windowActions.ts';

assert.equal(windowRerunActionLabel('failed'), 'Retry window');
assert.equal(windowRerunActionLabel('succeeded'), 'Recheck window');
assert.equal(windowRerunActionLabel('running'), null);
assert.equal(windowRerunActionLabel('pending'), null);
