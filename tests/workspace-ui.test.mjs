import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { File } from 'node:buffer';
import test, { afterEach } from 'node:test';
import React, { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import ts from 'typescript';

// Compile the actual TSX components with the existing TypeScript dependency.
const require = createRequire(import.meta.url);
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(readFileSync(filename, 'utf8'), {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
      fileName: filename,
    });
    module._compile(outputText, filename);
  };
}
require.extensions['.css'] = module => module._compile('', module.filename);
const { SignalPlots } = require('../src/workspace/Charts.tsx');
const { ResultView } = require('../src/workspace/Results.tsx');
const { ImportDataset } = require('../src/workspace/WorkspaceApp.tsx');

const dom = new JSDOM('<!doctype html><body></body>', { url: 'http://localhost/', pretendToBeVisual: true });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.HTMLElement.prototype.scrollIntoView = function () {};

const names = ['reactor_temp_c', 'pressure_tx_kpa', 'pressure_backup_kpa', 'cooling_flow_m3h', 'feed_flow_m3h', 'cooling_valve_pct', 'pump_vibration_mms', 'separator_pressure_kpa'];
const dataset = (id, rows = 900) => ({ id, name: id, workspace_id: 'test', metadata: {
  rowCount: rows, columns: names.map(name => ({ name, missing: 0, min: 0, max: 100 })),
  time: { kind: 'numeric', column: 't', origin: null, start: 0, end: rows - 1 }, notes: [], sourceColumns: ['t', ...names], ignoredColumns: [], missingCount: 0,
} });
function seriesFor(url) {
  const query = new URL(url, 'http://localhost').searchParams;
  const start = Math.ceil(Number(query.get('start') || 0)), end = Math.floor(Number(query.get('end') || 899));
  const times = Array.from({ length: end - start + 1 }, (_, i) => start + i);
  return { times, values: Object.fromEntries(query.getAll('signal').map((name, i) => [name, times.map(t => Math.sin(t / 20) + i)])), sourceRows: times.length, displayRows: times.length };
}
function response(data) { return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } }); }
let container, root;
async function mount(element) {
  container = document.createElement('div'); document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(element));
}
afterEach(async () => { if (root) await act(async () => root.unmount()); container?.remove(); root = null; });
function curve(name) { return [...container.querySelectorAll('svg')].find(svg => svg.getAttribute('aria-label')?.startsWith(name + ' time series')); }
async function click(node) { assert.ok(node, 'control exists'); await act(async () => node.click()); }
function Controls({ data }) {
  const [selected, setSelected] = useState(names.slice(0, 3));
  return React.createElement(React.Fragment, null,
    ...names.map(name => React.createElement('input', { key: name, type: 'checkbox', 'aria-label': name, checked: selected.includes(name), onChange: e => setSelected(previous => e.target.checked ? [...previous, name] : previous.filter(n => n !== name)) })),
    React.createElement(SignalPlots, { dataset: data, signals: selected }),
  );
}

test('900×8 checkbox changes retain existing SVG nodes and reuse one full-data request', async () => {
  const requests = [];
  globalThis.fetch = async url => { requests.push(url); return response(seriesFor(url)); };
  await mount(React.createElement(Controls, { data: dataset('small-checkbox-workflow') }));
  assert.equal(requests.length, 1);
  assert.equal(new URL(requests[0], 'http://localhost').searchParams.getAll('signal').length, 8);
  const existing = names.slice(0, 3).map(curve);
  existing.forEach(node => assert.ok(node));
  for (const name of ['cooling_flow_m3h', 'cooling_valve_pct', 'cooling_flow_m3h', 'cooling_flow_m3h', 'cooling_valve_pct', 'cooling_valve_pct']) {
    await click(container.querySelector(`input[aria-label="${name}"]`));
    names.slice(0, 3).forEach((signal, i) => assert.equal(curve(signal), existing[i], 'existing curve stays mounted'));
    assert.ok(!container.textContent.includes('Loading'), 'no global or per-signal loading after prefetch');
  }
  assert.ok(curve('cooling_flow_m3h'));
  assert.ok(curve('cooling_valve_pct'));
  assert.equal(requests.length, 1, 'reselecting cached signals does not fetch again');
});

test('large-data requests can complete out of order without clearing curves or leaking across datasets', async () => {
  const requests = [];
  globalThis.fetch = url => new Promise(resolve => requests.push({ url, resolve }));
  const data = dataset('large-checkbox-workflow', 10000);
  await mount(React.createElement(Controls, { data }));
  await act(async () => requests[0].resolve(response(seriesFor(requests[0].url))));
  const existing = names.slice(0, 3).map(curve);
  await click(container.querySelector('input[aria-label="cooling_flow_m3h"]'));
  await click(container.querySelector('input[aria-label="cooling_valve_pct"]'));
  names.slice(0, 3).forEach((name, i) => assert.equal(curve(name), existing[i]));
  await click(container.querySelector('input[aria-label="cooling_flow_m3h"]'));
  await act(async () => requests[2].resolve(response(seriesFor(requests[2].url))));
  await act(async () => requests[1].resolve(response(seriesFor(requests[1].url))));
  assert.equal(curve('cooling_flow_m3h'), undefined, 'late hidden signal stays hidden');
  await click(container.querySelector('input[aria-label="cooling_flow_m3h"]'));
  assert.ok(curve('cooling_flow_m3h'));
  assert.equal(requests.length, 3);
  await click(container.querySelector('input[aria-label="pump_vibration_mms"]'));
  await act(async () => root.render(React.createElement(Controls, { data: dataset('another-dataset', 10000) })));
  assert.equal(curve(names[0]), undefined, 'new dataset does not show old measurements');
  await act(async () => requests[3].resolve(response(seriesFor(requests[3].url))));
  assert.equal(curve('pump_vibration_mms'), undefined, 'old pending response cannot populate the new dataset');
  await act(async () => requests[4].resolve(response(seriesFor(requests[4].url))));
  assert.ok(curve(names[0]));
});

test('key findings prioritize sustained events, retain short events, and focus related curves; old results still open', async () => {
  globalThis.fetch = async url => response(seriesFor(url));
  const contribution = names.map((signal, i) => ({ signal, value: 97.2 / (i + 1) }));
  const interval = (start, end, peakScore) => ({ start, end, samples: end - start + 1, peakScore, peakTime: start, signals: names.slice(0, 5), contributions: contribution });
  const intervals = [interval(250, 250, 200), interval(362, 469, 40), interval(610, 654, 97.2), interval(780, 829, 30)];
  const result = { id: 'result', name: 'Three process deviations', algorithmLabel: 'Robust Max-Z', completedAt: '2026-10-23T08:00:00Z', durationMs: 2,
    config: { signals: names, analysisRange: [200, 899], algorithm: 'robust-maxz', alpha: .01 }, times: [200, 250, 362, 469, 610, 654, 780, 829, 899], scores: [0, 200, 40, 20, 97.2, 30, 20, 30, 0], threshold: 3,
    intervals, relatedSignals: names, signalContributions: contribution, contributionMetric: 'absolute-robust-z', peakTime: 250,
    summary: { analysisSamples: 700, baselineSamples: 200, fitSamples: 140, calibrationSamples: 60, flaggedSamples: 204, peakScore: 200, firstDetection: 250, imputedValues: { analysis: 0 } }, model: {} };
  const props = { dataset: dataset('findings-workflow'), signalPicker: () => null };
  await mount(React.createElement(ResultView, { ...props, result }));
  const cards = [...container.querySelectorAll('.ws-finding')];
  assert.equal(cards.length, 3);
  assert.match(cards[0].textContent, /362 s.*469 s/);
  assert.match(cards[1].textContent, /780 s.*829 s/);
  assert.match(cards[2].textContent, /610 s.*654 s/);
  assert.equal(container.querySelectorAll('tbody tr').length, 4, 'short high peak remains in complete record');
  assert.match(container.querySelector('.ws-contributions').textContent, /97.2/);
  await click(cards[0].querySelector('button'));
  assert.match(container.querySelector('.ws-interval-detail').textContent, /Selected interval.*362 s.*469 s/s);
  assert.ok(curve(names[0]));
  await click([...container.querySelectorAll('button')].find(b => b.textContent === 'Show full analysis window'));
  assert.match(container.querySelector('.ws-interval-detail').textContent, /Highest-score sample/);
  const legacy = { ...result, id: 'legacy', signalContributions: undefined, contributionMetric: undefined, intervals: intervals.map(({ contributions, ...saved }) => saved) };
  await act(async () => root.render(React.createElement(ResultView, { ...props, key: 'legacy', result: legacy })));
  assert.match(container.querySelector('.ws-contributions').textContent, /saved run retains signal rankings/);
  assert.equal(container.querySelectorAll('tbody tr').length, 4);
});

test('custom upload control shows English text and selected filename while the native input stays hidden', async () => {
  globalThis.fetch = async () => response({ metadata: dataset('upload').metadata, series: seriesFor('/?signal=reactor_temp_c') });
  await mount(React.createElement(ImportDataset, { workspaceId: 'test', onImport: () => {} }));
  const button = [...container.querySelectorAll('button')].find(b => b.textContent === 'Choose file');
  const input = container.querySelector('input[type="file"]');
  assert.ok(button); assert.equal(button.type, 'button'); assert.ok(input.hidden);
  assert.match(container.textContent, /No file selected/);
  let opened = false;
  input.addEventListener('click', () => { opened = true; });
  await click(button); assert.ok(opened, 'custom button opens the real native picker');
  const file = new File(['t,reactor_temp_c\n0,80\n1,81\n'], 'process-eight-signals.csv', { type: 'text/csv' });
  Object.defineProperty(input, 'files', { value: [file] });
  await act(async () => { input.dispatchEvent(new dom.window.Event('change', { bubbles: true })); await file.arrayBuffer(); });
  assert.equal(container.querySelector('#csv-filename').textContent, 'process-eight-signals.csv');
  assert.ok(!container.textContent.includes('No file selected'));
});
