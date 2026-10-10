import assert from 'node:assert/strict';
import test from 'node:test';

import { getDailyTrafficDisplay } from './dailyTrafficDisplay.js';

test('Hormuz and Bab el-Mandeb use the same daily traffic card format', () => {
  const hormuz = getDailyTrafficDisplay({
    chokepoint: 'Strait of Hormuz',
    date: '2026-10-10',
    source: 'TankerMap',
    tankers: 0,
  });
  const babElMandeb = getDailyTrafficDisplay({
    chokepoint: 'Bab el-Mandeb',
    date: '2026-10-10',
    source: 'TankerMap',
    tankers: 6,
  });

  assert.deepEqual(hormuz, {
    value: '0 tankers/day',
    date: 'TankerMap data as of 2026-10-10',
    source: 'Source: TankerMap daily tanker transits',
  });
  assert.deepEqual(babElMandeb, {
    value: '6 tankers/day',
    date: 'TankerMap data as of 2026-10-10',
    source: 'Source: TankerMap daily tanker transits',
  });
});

test('missing daily data has the same unavailable state for either chokepoint', () => {
  assert.deepEqual(getDailyTrafficDisplay(null), {
    value: 'Unavailable',
    date: 'No source data available',
    source: 'Source: Unavailable',
  });
});
