import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/comparison.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { viewFor, buildComparisonReport, comparisonCutoffs } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString('base64')}`);
const analysis = (name, time) => ({
  time,
  diagnosis: { candidates: [{ name, score: 55, confidence: 'moderate' }], status: 'investigating',
    firstDetection: 33, health: { a: { usable: true }, b: { usable: false } }, nextMeasurements: [{ tag: 'PI-102' }] },
  alarms: { eventCount: 3, uniqueConditions: 1, clusters: ['reactor'], reannunciations: 2 },
});
const incident = id => ({ id, title: id, ...analysis('full window', 240),
  snapshots: comparisonCutoffs.filter(t => t !== 240).map(t => analysis(`prefix ${t}`, t)),
  recovery: { base: { trip: 118 }, actions: [{ latest: 90 }, { latest: null }, { latest: 95 }] },
  groundTruth: 'excluded simulator label', rows: [{ futureSecret: true }],
});

test('every declared comparison uses its matching observation window', () => {
  const value = incident('a');
  for (const time of comparisonCutoffs) {
    const view = viewFor(value, time);
    assert.equal(view.leading.name, time === 240 ? 'full window' : `prefix ${time}`);
    assert.equal(view.recovery === null, time !== 240);
  }
});
test('early exports never read future diagnosis or recovery', () => {
  const a = incident('a'), b = incident('b');
  const before = buildComparisonReport(a, b, 40, 'test model');
  a.diagnosis.candidates[0].name = 'future mutation';
  Object.defineProperty(a, 'recovery', { get() { throw Error('future recovery read'); } });
  assert.deepEqual(buildComparisonReport(a, b, 40, 'test model'), before);
  assert.equal(JSON.stringify(before).includes('groundTruth'), false);
  assert.equal(JSON.stringify(before).includes('futureSecret'), false);
});
test('full-window JSON round trip retains conditional recovery and distinct cases', () => {
  const report = buildComparisonReport(incident('a'), incident('b'), 240, 'model');
  assert.deepEqual(JSON.parse(JSON.stringify(report)), report);
  assert.equal(report.left.recovery.lastRecoverableStart, 95);
  assert.equal(report.right.recovery.modelTrip, 118);
  assert.equal(buildComparisonReport(incident('a'), incident('a'), 40, 'model'), null);
});
test('missing or unsupported cutoffs cannot fall back to future evidence', () => {
  const value = incident('a');
  value.snapshots = [];
  for (const time of [40, 39, 241, NaN]) assert.equal(viewFor(value, time), null);
});
