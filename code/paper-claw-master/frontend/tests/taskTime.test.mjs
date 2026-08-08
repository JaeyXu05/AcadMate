import assert from 'node:assert/strict';
import { localTimeToUtcTime, utcTimeToLocalTime } from '../src/features/tasks/taskTime.ts';

assert.equal(utcTimeToLocalTime('00:30', 480), '08:30');
assert.equal(localTimeToUtcTime('08:30', 480), '00:30');
assert.equal(utcTimeToLocalTime('23:45', 90), '01:15');
assert.equal(localTimeToUtcTime('01:15', 90), '23:45');
assert.equal(utcTimeToLocalTime('00:15', -300), '19:15');
assert.equal(localTimeToUtcTime('19:15', -300), '00:15');
