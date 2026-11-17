import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { File } from 'node:buffer';
import test, { afterEach } from 'node:test';
import React, { act, useState } from 'react';
import { JSDOM } from 'jsdom';
import ts from 'typescript';

// Compile the actual TSX components with the existing TypeScript dependency.
const require = createRequire(import.meta.url);
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(readFileSync(filename, 'utf8'), {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
      fileName: filename,
    });
    module._compile(outputText, filename);
  };
}
require.extensions['.css'] = module => module._compile('', module.filename);
const dom = new JSDOM(readFileSync(new URL('../index.html', import.meta.url), 'utf8'), { url: 'http://localhost/', pretendToBeVisual: true });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.Element = dom.window.Element;
globalThis.SVGElement = dom.window.SVGElement;
globalThis.requestAnimationFrame = dom.window.requestAnimationFrame.bind(dom.window);
globalThis.cancelAnimationFrame = dom.window.cancelAnimationFrame.bind(dom.window);
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.HTMLElement.prototype.scrollIntoView = function () {};
dom.window.scrollTo = () => {};
dom.window.matchMedia = () => ({ matches: true, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
const { createRoot } = await import('react-dom/client');
const { Plot, SignalPlots } = require('../src/workspace/Charts.tsx');
const { LiveEvidence } = require('../src/workspace/data/LiveEvidence.tsx');
const { ResultView } = require('../src/workspace/monitoring/Results.tsx');
const { ImportDataset, AnalysisPage } = require('../src/workspace/WorkspaceApp.tsx');
const GuidedDemo = require('../src/workspace/investigation/GuidedDemo.tsx').default;
const App = require('../src/App.tsx').default;
const { analysisPath } = require('../src/workspace/api.ts');
const { RuntimeWorkbench } = require('../src/workspace/modeling/RuntimeWorkbench.tsx');
const { IncidentsPage, IncidentDetail } = require('../src/workspace/investigation/Incidents.tsx');
const { SignalWorkspace, SignalEditor, QualityExplorer, TimeReferenceEditor, CursorReadout } = require('../src/workspace/data/SignalWorkspace.tsx');
const { TransformationWorkspace, TransformationLineage } = require('../src/workspace/data/TransformationWorkspace.tsx');
const { ExperimentWorkspace, newExperimentConfig } = require('../src/workspace/investigation/ExperimentWorkspace.tsx');
const { ExperimentLabels } = require('../src/workspace/investigation/ExperimentLabels.tsx');
const { ExperimentReport } = require('../src/workspace/investigation/ExperimentReport.tsx');
const { ExperimentComparison } = require('../src/workspace/investigation/ExperimentComparison.tsx');
const { ModelWorkspace } = require('../src/workspace/modeling/ModelWorkspace.tsx');
const { ControlWorkspace } = require('../src/workspace/modeling/ControlWorkspace.tsx');
const { ControlResults } = require('../src/workspace/modeling/ControlResults.tsx');
const { defaultProtocol } = require('../src/workspace/modeling/controlTypes.ts');
const { CalibrationWorkspace, observationReference } = require('../src/workspace/modeling/CalibrationWorkspace.tsx');
const { CalibrationResults } = require('../src/workspace/modeling/CalibrationResults.tsx');
const { ScenarioEditor } = require('../src/workspace/modeling/ScenarioEditor.tsx');
const { ModelSimulation } = require('../src/workspace/modeling/ModelSimulation.tsx');
const { SavedRunView } = require('../src/workspace/modeling/RuntimeWorkbench.tsx');
const { ModelResearch } = require('../src/workspace/modeling/ModelResearch.tsx');
const { EstimationWorkspace, EstimationResults } = require('../src/workspace/modeling/EstimationWorkspace.tsx');
const { EstimationProvenance } = require('../src/workspace/modeling/EstimationProvenance.tsx');
const { TEPWorkspace } = require('../src/workspace/investigation/TEPWorkspace.tsx');
const { IndependentTraining } = require('../src/workspace/investigation/IndependentTraining.tsx');
const { SensorHealthWorkspace, SensorHealthResult, newHealthConfig } = require('../src/workspace/monitoring/SensorHealthWorkspace.tsx');
const { TEPBenchmark } = require('../src/workspace/investigation/TEPBenchmark.tsx');
const { TEPStudyDashboard } = require('../src/workspace/investigation/TEPStudyDashboard.tsx');
const { ReplayWorkspace } = require('../src/workspace/monitoring/ReplayWorkspace.tsx');
const { RegimeWorkspace } = require('../src/workspace/monitoring/RegimeWorkspace.tsx');
const { ResilienceWorkspace } = require('../src/workspace/reliability/ResilienceWorkspace.tsx');
const { t, runtimeText } = require('../src/lib/text.ts');
const { errorMessage } = require('../src/lib/text.ts');

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

test('live display can pause without writing to the gateway and bad values remain raw evidence', async () => {
  const mappings = [
    { signal_id: 'tank-level', display_name: 'Tank level', node_id: 'ns=2;s=Level', unit: 'm' },
    { signal_id: 'pump', display_name: 'Pump running', node_id: 'ns=2;s=Pump', unit: '' },
  ];
  const session = {
    id: 'tanks', workspace_id: 'test', name: 'Coupled tanks', state: 'recording',
    config: { endpoint: 'opc.tcp://127.0.0.1:4840/l5/tanks/' }, mappings,
    started_at: '2026-01-01T00:00:00.000000+00:00', stopped_at: null,
  };
  function observation(id, time, mapping, value, quality = 'good') {
    const stamp = `2026-01-01T00:00:0${time}.123456+00:00`;
    return { id, signal_id: mapping.signal_id, node_id: mapping.node_id, value, quality,
      status_code: quality === 'good' ? 0 : 0x80000000, status_name: quality === 'good' ? 'Good' : 'Bad',
      timestamp: stamp, timestamp_origin: 'source', source_timestamp: stamp, server_timestamp: stamp, received_at: stamp };
  }
  const good = observation(2, 1, mappings[0], 1.25);
  const bad = observation(3, 2, mappings[0], 98765, 'bad');
  const recovered = observation(4, 3, mappings[0], 1.3);
  const quiet = observation(1, 0, mappings[1], true);
  const writes = [], reads = [], datasets = [];
  const converted = dataset('captured-tanks');
  let samples = [good, bad];
  globalThis.fetch = async (url, options) => {
    if (url.endsWith('/dataset')) {
      writes.push({ url, body: JSON.parse(options.body) });
      return response(converted);
    }
    assert.equal(options.method, 'GET');
    reads.push({ url, signal: options.signal });
    return response({ samples, latest: [samples.at(-1), quiet],
      events: [{ id: 1, kind: 'sampling_gap', timestamp: bad.timestamp, detail: 'No recent data changes. A steady signal may also be quiet.', node_id: bad.node_id }] });
  };
  const props = { prefix: '/workspaces/test/live', session, onDataset: data => datasets.push(data) };
  await mount(React.createElement(LiveEvidence, props));
  const levelPlot = curve('Tank level (m)');
  assert.ok(levelPlot);
  assert.equal(levelPlot.querySelectorAll('circle').length, 1, 'the bad value does not extend the line or create a plotted point');
  assert.match(container.querySelector('.live-quality[data-quality="bad"]').closest('tr').textContent, /98765.*Bad.*00:00:02\.123456Z/);
  assert.match([...container.querySelectorAll('tbody tr')].find(row => row.textContent.includes('Pump running')).textContent, /On.*Good/);
  assert.match(container.querySelector('.live-event-log').textContent, /Sampling gap.*ns=2;s=Level/);
  await click(button('Pause display'));
  assert.equal(reads[0].signal.aborted, true);
  assert.equal(writes.length, 0);
  assert.match(container.textContent, /Display paused\. Acquisition continues\./);
  samples = [...samples, recovered];
  assert.equal(reads.length, 1);
  await click(button('Resume display'));
  assert.equal(reads.length, 2);
  assert.equal(curve('Tank level (m)').querySelectorAll('circle').length, 2);
  assert.equal(writes.length, 0);
  await act(async () => root.render(React.createElement(LiveEvidence, {
    ...props, session: { ...session, state: 'completed', stopped_at: recovered.received_at },
  })));
  await click(button('Use displayed time range'));
  const query = new URL(reads.at(-1).url, 'http://localhost').searchParams;
  assert.equal(query.get('start'), good.timestamp);
  assert.equal(query.get('end'), recovered.timestamp);
  await click(button('Create dataset'));
  assert.deepEqual(writes, [{ url: '/api/workspaces/test/live/sessions/tanks/dataset',
    body: { name: 'Coupled tanks', start: good.timestamp, end: recovered.timestamp } }]);
  assert.deepEqual(datasets, [converted]);
  assert.ok(container.querySelector('a[href="#/workspaces/test/datasets/captured-tanks"]'));
});

function Controls({ data }) {
  const [selected, setSelected] = useState(names.slice(0, 3));
  return React.createElement(React.Fragment, null,
    ...names.map(name => React.createElement('input', { key: name, type: 'checkbox', 'aria-label': name, checked: selected.includes(name), onChange: e => setSelected(previous => e.target.checked ? [...previous, name] : previous.filter(n => n !== name)) })),
    React.createElement(SignalPlots, { dataset: data, signals: selected }),
  );
}

test('guided demo connects the live API steps to saved results, incident and localized report', async () => {
  const data = dataset('guided-ui-data', 241);
  const plan = { baselineRange: [0, 79.8], analysisRange: [80, 240], onset: 120, step: .2,
    signals: names.slice(0, 2), contextSignals: names.slice(2, 4), persistence: 3 };
  let session = null;
  const source = { workspaceId: 'test', datasetId: data.id, experimentId: 'guided-ui-experiment', runId: null, incidentId: null };
  const incident = { id: 'guided-ui-incident', workspace_id: 'test', title: 'Inlet flow loss' };
  const tasks = ['Robust Max-Z', 'EWMA'].map((algorithmLabel, i) => {
    const start = 121 + i;
    const result = { id: `guided-ui-analysis-${i}`, workspaceId: 'test', algorithmLabel,
      times: [80, 120, start, 240], scores: [1, 2, 8, 15], threshold: 4, peakTime: 240,
      summary: { firstDetection: start }, relatedSignals: plan.signals,
      intervals: [{ start, end: 240, peakTime: 240, signals: plan.signals, contributions: [{ signal: plan.signals[0], value: 15 }] }] };
    return { result, task: { status: 'succeeded', result_id: result.id,
      metrics: { labelled: { event: { firstDetectionDelay: i + 1, falseAlarmEvents: 0 } } } } };
  });
  const actions = [];
  globalThis.fetch = async (url, options) => {
    if (options?.method === 'POST') actions.push(url);
    if (url === '/api/guided-demo') {
      if (options.method === 'POST') session = source;
      return response({ plan, session });
    }
    if (url === '/api/guided-demo/run') {
      session = { ...session, runId: 'guided-ui-run' };
      return response({ plan, session });
    }
    if (url === '/api/guided-demo/incident') {
      session = { ...session, incidentId: incident.id };
      return response({ plan, session });
    }
    if (url === '/api/experiment-runs/guided-ui-run') return response({ id: 'guided-ui-run', status: 'succeeded', tasks: tasks.map(a => a.task) });
    if (url.startsWith('/api/analyses/')) return response(tasks.find(a => url.endsWith(a.result.id)).result);
    if (url.startsWith(`/api/datasets/${data.id}/series`)) return response(seriesFor(url));
    if (url === `/api/datasets/${data.id}`) return response(data);
    if (url === `/api/incidents/${incident.id}`) return response(incident);
    if (url === `/api/incidents/${incident.id}/report.html`) return new Response('<h1>Incident report</h1>', { headers: { 'Content-Type': 'text/html' } });
    throw Error(`Unexpected request ${url}`);
  };
  const button = label => [...container.querySelectorAll('button')].find(node => node.textContent === label);
  await mount(React.createElement(GuidedDemo, { onPrepared() {} }));
  assert.ok(!button('Run both detectors'));
  await click(button('Load the scenario'));
  assert.ok(curve(plan.signals[0]).querySelector('[data-truth-onset="120"]'));
  await click(button('Inlet flow and pump command'));
  assert.ok(curve(plan.contextSignals[0]));
  await click(button('Run both detectors'));
  assert.equal(container.querySelectorAll('.guided-result').length, 2);
  await click(container.querySelector('button[aria-label="Inspect EWMA"]'));
  assert.ok(curve('EWMA'));
  assert.match(container.querySelector('.guided-evidence').textContent, /122 s.*240 s/);
  await click(button('Create linked incident'));
  assert.ok(container.querySelector('a[href="#/workspaces/test/incidents/guided-ui-incident"]'));
  await click(button("Generate report"));
  assert.match(container.querySelector('iframe').srcdoc, /Incident report/);
  assert.deepEqual(actions, ['/api/guided-demo', '/api/guided-demo/run', '/api/guided-demo/incident']);
});

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


// Exercise the real runtime UI with deliberately non-cancellable, deferred responses.
const processSignals = require('../src/lib/processMetadata.ts').default.signals;
const simulationConfig = { fault:'cooling_valve', start:40, severity:1, operating:0, noise:1, response:1, delay:0, seed:7, duration:600, step:1 };
const simulation = id => ({ id, title:`Session ${id}`, config:simulationConfig, rows:Array.from({length:601},(_,t)=>({t,...Object.fromEntries(processSignals.map(s=>[s.key,s.nominal+t/10]))})), workspaceId:null, datasetId:null, createdAt:'2026-10-24T00:00:00Z' });
function runtimeAPI({ deferSessions = false } = {}) {
  const analyses = [], operations = [], loads = [];
  globalThis.fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    if (url.endsWith('/catalog')) return response({faults:{healthy:'Healthy',cooling_valve:'Cooling valve',pump_degradation:'Cooling pump'},defaults:simulationConfig,signals:processSignals,actions:[{id:'bypass',name:'Open cooling bypass'}],actionParameters:{bypassFlow:{default:40,min:0,max:100}},tools:['inspect_signal_window','simulate_fault']});
    if (url === '/api/simulations') return response({simulations:[simulation('A'),simulation('B'),simulation('C')]});
    if (url === '/api/workspaces') return response({workspaces:[]});
    if (url.endsWith('/analysis')) return new Promise(resolve=>analyses.push({url,body,resolve,signal:options.signal}));
    if (url.endsWith('/runs')) return response({runs:[]});
    if (url.endsWith('/tools') || url.endsWith('/interventions') || url === '/api/analyze') return new Promise(resolve=>operations.push({url,body,resolve}));
    const id = url.match(/^\/api\/simulations\/([^/]+)$/)?.[1];
    if (id) return deferSessions ? new Promise(resolve=>loads.push({id,resolve})) : response(simulation(id));
    throw new Error(`Unexpected runtime request: ${url}`);
  };
  return {analyses,operations,loads};
}
function observed(request, leader = request.body.asOf > 200 ? 'cooling_valve' : 'pump_degradation') {
  const {asOf,windowStart} = request.body;
  const first = Math.ceil(windowStart), last = Math.floor(asOf);
  return {asOf,windowStart:first,observedThrough:last,samples:last-first+1,
    diagnosis:{status:'diagnosed',candidates:[leader,...['cooling_valve','pump_degradation'].filter(id=>id!==leader)].map((id,i)=>({id,name:`${id} at ${windowStart}–${asOf}`,score:90-i*20,confidence:'high',support:[`Evidence through ${last}s`],against:[],unresolved:[],topology:0,parts:[]})),firstDetection:last-1,detections:{valve:{time:last-1,onset:last-1,direction:1}},health:Object.fromEntries(processSignals.map(s=>[s.key,{status:'healthy',usable:true,missing:0,detail:'Available',freshness:0}])),changes:{valve:0},clock:{regular:true,gaps:0,step:1},paths:[],controllers:[],nextMeasurements:[]},
    alarms:{eventCount:0,uniqueConditions:0,reannunciations:0,firstAlarm:null,clusters:[],floods:[],events:[],conditions:[],rationalization:[]},trace:[],sop:{id:'SOP',revision:'1',title:'Inspect current evidence',preconditions:[],applicable:true,action:'Inspect',status:'Ready',conflict:''}};
}
async function resolveAnalysis(request, leader) { assert.ok(request, 'analysis request exists'); await act(async()=>request.resolve(response(observed(request,leader)))); }
async function debounceAnalysis() { await act(async()=>new Promise(resolve=>setTimeout(resolve,210))); }
function field(label) { const node=[...container.querySelectorAll('label')].find(node=>node.textContent.startsWith(label)); assert.ok(node, `field ${label} exists`); return node.querySelector('input,select'); }
function button(text) { return [...container.querySelectorAll('button')].find(node=>node.textContent.startsWith(t(text))); }
async function setField(node,value) {
  assert.ok(node);
  await act(async()=>{
    const prototype = node.tagName === 'SELECT' ? dom.window.HTMLSelectElement.prototype : node.tagName === 'TEXTAREA' ? dom.window.HTMLTextAreaElement.prototype : dom.window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype,'value').set.call(node,String(value));
    node.dispatchEvent(new dom.window.Event(node.tagName === 'SELECT' ? 'change' : 'input',{bubbles:true}));
  });
}

test('monitoring prepares explicitly, replays, seeks to an alarm and opens saved evidence in either language', async () => {
  const source = dataset('monitoring-source');
  source.metadata.suggestedRanges = { baselineRange: [0, 99], analysisRange: [100, 899] };
  const signals = names.slice(0, 3);
  const calls = [];
  const alarm = { id: 1, start: 125, end: 125, peakTime: 125, peakIndex: 1, peakScore: 8, samples: 1,
    signals: [signals[0]], status: 'active', durationSeconds: 0, transitionTime: null, contributions: [{ signal: signals[0], value: 8 }] };
  function series(through) {
    return { first: 0, times: [100, 125, 125.1].slice(0, through), states: ['normal', 'alarm', 'normal'].slice(0, through),
      scores: [1, 8, 1].slice(0, through), scoreSegments: [1, 1, 1].slice(0, through),
      values: Object.fromEntries(signals.map(signal => [signal, [1, 8, 1].slice(0, through)])),
      signalSegments: Object.fromEntries(signals.map(signal => [signal, [1, 1, 1].slice(0, through)])) };
  }
  globalThis.fetch = async (url, init) => {
    const body = JSON.parse(init.body);
    calls.push([url.split('/').at(-1), body]);
    if (url.endsWith('/replays')) return response({ id: 'replay-a', config: body, threshold: 3, start: 100, end: 125.1,
      sampleCount: 3, fitSamples: 70, calibrationSamples: 30, alarmPageSize: 20 });
    if (url.endsWith('/frame')) {
      const through = body.at < 125 ? 1 : body.at < 125.1 ? 2 : 3;
      return response({ through, series: series(through), nextTime: [125, 125.1, null][through - 1],
        alarmCount: through === 1 ? 0 : 1, alarms: through === 1 ? [] : [alarm] });
    }
    if (url.endsWith('/evidence')) return response({ alarm, series: series(body.through) });
    if (url.endsWith('/incident')) return response({ id: 'incident-a' });
    throw new Error(`Unexpected replay request ${url}`);
  };
  await mount(React.createElement(ReplayWorkspace, { workspaceId: 'test', datasets: [source] }));
  assert.ok(button('Prepare replay').disabled);
  await click(container.querySelector('.replay-confirm input'));
  await click(button('Prepare replay'));
  assert.deepEqual(calls[0][1].baselineRange, [0, 99]);
  assert.match(container.textContent, /0 \/ 3 observations/);
  await click(button('Start'));
  assert.match(container.textContent, /1 \/ 3 observations/);
  await click(button('Pause'));
  assert.ok(button('Resume'));
  const slider = container.querySelector('input[type="range"]');
  await setField(slider, 125);
  await click(button('Seek'));
  assert.match(container.textContent, /2 \/ 3 observations/);
  assert.match(container.textContent, /Alarm active/);
  await click(button('Inspect'));
  assert.deepEqual(calls.at(-1), ['evidence', { alarmId: 1, through: 2 }]);
  await click(button('Save alarm as incident'));
  assert.equal(container.querySelector('.replay-evidence a').getAttribute('href'), '#/workspaces/test/incidents/incident-a');
  assert.match(container.textContent, /Process Replay & Monitoring/);
  assert.match(container.textContent, /Contribution at peak/);
  await setField(slider, 100);
  await click(button('Seek'));
  assert.doesNotMatch(container.textContent, /Open saved incident/);
  await click(button('Restart'));
  assert.match(container.textContent, /0 \/ 3 observations/);
});

function isMasked(node) { return Boolean(node?.closest('[aria-hidden="true"][inert]')); }

test('resilience composer localizes, saves stable fault schedules and exports only a run reference', async () => {
  const base = '/api/workspaces/test/resilience';
  const signal = {key:'level1', tag:'LT-101', unit:'m', label:'Tank 1 measured level'};
  const initial = {name:'Tank trial',model_id:'coupled-tanks',initial:{},parameters:{},duration:10,sample_interval:1,integration_step:.05,seed:1,
    measurement:{noise:0,missing_fraction:0,physical_noise:0,signals:['level1']},faults:[]};
  const catalog = {models:[{id:initial.model_id,name:'Coupled tanks',version:'1',initial:[],parameters:[],signals:[signal]}],
    fault_types:[{id:'pump_degradation',targets:['pump'],parameters:[]}],
    profiles:[{id:'step',parameters:[]}],defaults:initial,limits:{max_faults:24,max_samples:6001},
    algorithms:{'robust-maxz':'Robust Max-Z'},default_detectors:[{algorithm:'robust-maxz',signals:['level1']}],
    max_cases:64,max_search_cases:32,objectives:['missed'],benchmark_version:'v1',benchmark_detectors:[{algorithm:'robust-maxz'}]};
  const stamp = '2026-11-13T00:00:00Z';
  let simulation, saved, exportedRequest;
  const exported = dataset('resilience-dataset',2);
  exported.metadata.columns = [{name:'level1',id:'catalog-level1'}];
  globalThis.fetch = async (url, request) => {
    const body = request.body ? JSON.parse(request.body) : null;
    if (url === `${base}/catalog`) return response(catalog);
    if (url === `${base}/scenarios` && !body) return response({scenarios:[]});
    if (url === `${base}/scenarios` && body) return response(saved={id:'scenario',...body});
    if (url === `${base}/runs`) return response({runs:[]});
    if (url === `${base}/campaigns`) return response({campaigns:[]});
    const schedule = scenario => scenario.faults.map(fault => ({...fault,intervals:[{start:fault.onset,end:scenario.duration}]}));
    if (url === `${base}/preview`) return response({schedule:schedule(body.scenario)});
    if (url === `${base}/simulate`) {
      const events = schedule(body.scenario);
      return response(simulation={id:'run',name:body.name,created_at:stamp,dataset_id:null,scenario:body.scenario,
        model_version:'1',signals:[signal],schedule:events,
        truth:{physical:[{t:0,level1:1},{t:1,level1:1}],events,severities:Object.fromEntries(events.map(event=>[event.id,[0,.6]]))},
        observations:[{t:0,values:{level1:1},quality:{level1:'observed'},source_times:{level1:0},acquisition_times:{level1:0}},
          {t:1,values:{level1:null},quality:{level1:'blackout'},source_times:{level1:1},acquisition_times:{level1:null}}],
        observation_packets:[]});
    }
    if (url === `${base}/runs/run`) return response(simulation);
    if (url === `${base}/export`) { exportedRequest=body; return response(exported); }
    throw new Error(`Unexpected resilience request ${url}`);
  };
  const props={workspaceId:'test',onExport:()=>{}};
  await mount(React.createElement(ResilienceWorkspace,props));
  assert.equal(container.querySelector('h1').textContent,'Resilience Testing');
  await click(button('Add fault'));
  await click(button('Add fault'));
  await click(button('Save scenario'));
  assert.deepEqual(saved.scenario.faults.map(event=>event.id),['fault-1','fault-2']);
  assert.equal(container.querySelector('h1').textContent,"Resilience Testing");
  assert.match(container.textContent,/Fault schedule/);
  await click(button('Run simulation'));
  await act(async()=>root.render(React.createElement(ResilienceWorkspace,{...props,section:'runs',recordId:'run'})));
  assert.match(container.textContent,/Physical vs\. measured trajectories/);
  assert.match(container.textContent,/Blackout/);
  await click(button('Open Signal Explorer'));
  assert.deepEqual(exportedRequest,{run_id:'run',name:saved.name});
  assert.equal(window.location.hash,'#/workspaces/test/explorer/catalog-level1');
});
async function openRuntime(api, asOf = 300, tab = 'evidence') {
  await mount(React.createElement(RuntimeWorkbench,{simulationId:'A',initialTab:tab}));
  await setField(field('Observe through'),asOf);
  await debounceAnalysis();
  await resolveAnalysis(api.analyses.at(-1));
}
function forecastFor(body) {
  const path={times:[body.asOf,body.horizon],pressure:[2700,2800],physicalPeak:2800,trip:null,productionLoss:0,qualityLoss:0,utilityCost:1,safe:true};
  return {mode:body.mode,hypothesis:body.hypothesis,observedThrough:body.asOf,at:body.at,horizon:body.horizon,threshold:3600,fitError:.01,baseline:path,branches:[{...path,action:'bypass'}]};
}
async function resolveOperation(request, marker = '') {
  const intervention = request.url.endsWith('/interventions'), assistant = request.url === '/api/analyze';
  const trace=[{index:1,tool:request.body.calls?.[0]?.tool || 'inspect_signal_window',args:request.body.calls?.[0]?.args || {},result:{marker,observedThrough:request.body.asOf},status:'computed'}];
  const record={id:`run-${marker}`,kind:intervention ? 'intervention' : assistant ? 'assistant' : 'tool',request:request.body,result:intervention ? forecastFor(request.body) : {trace},createdAt:'2026-10-24T00:00:00Z'};
  await act(async()=>request.resolve(response(assistant ? {provider:'local',summary:marker,limitation:'',trace,record} : record)));
}

test('runtime windows retain plots, mask stale diagnoses immediately, reject late responses, and reuse exact-context cache', async()=>{
  const api=runtimeAPI(); await openRuntime(api);
  const topology=container.querySelector('.p-topology'), plot=container.querySelector('.p-signal-readout svg'), rawPath=plot.querySelector('path');
  const pathAt300=rawPath.getAttribute('d');
  await setField(field('Observe through'),93);
  assert.match(container.querySelector('.runtime-timeline [aria-live]').textContent,/Updating evidence for 0–93s/);
  assert.ok(isMasked(container.querySelector('.p-candidates')), '300-second conclusions are hidden and inert');
  assert.equal(container.querySelector('.p-topology'),topology);
  assert.equal(container.querySelector('.p-signal-readout svg'),plot);
  assert.notEqual(rawPath.getAttribute('d'),pathAt300,'visible raw curve follows the selected cutoff immediately');
  assert.equal(button('Export observed dossier').disabled,true);
  await debounceAnalysis(); await resolveAnalysis(api.analyses.at(-1));
  assert.equal(isMasked(container.querySelector('.p-candidates')),false);
  assert.match(container.querySelector('.p-candidates button').textContent,/at 0–93/);
  await setField(field('Observation window start'),10.2); await debounceAnalysis();
  assert.ok(isMasked(container.querySelector('.p-candidates')),'same cutoff with a different start is a different context');
  await resolveAnalysis(api.analyses.at(-1));
  assert.match(container.querySelector('.runtime-timeline [aria-live]').textContent,/Showing 11–93s/,'actual sampled bounds may differ from requested bounds');
  await setField(field('Observe through'),150); await debounceAnalysis(); const older=api.analyses.at(-1);
  await setField(field('Observe through'),160); await debounceAnalysis(); const newer=api.analyses.at(-1);
  assert.ok(older.signal.aborted);
  await resolveAnalysis(newer); await resolveAnalysis(older);
  assert.match(container.querySelector('.p-candidates button').textContent,/at 10.2–160/,'ignored cancellation cannot allow an older response to win');
  const count=api.analyses.length;
  await setField(field('Observe through'),93);
  assert.equal(isMasked(container.querySelector('.p-candidates')),false,'cache hit is valid in the same render');
  assert.match(container.querySelector('.runtime-timeline [aria-live]').textContent,/Showing 11–93s/);
  assert.equal(container.querySelector('.p-topology'),topology); assert.equal(container.querySelector('.p-signal-readout svg'),plot);
  await debounceAnalysis(); assert.equal(api.analyses.length,count,'cached context is not fetched again');
});

test('investigations and the assistant use only the current diagnosis and ignore old-window output',async()=>{
  const api=runtimeAPI(); await openRuntime(api,300,'tools');
  await setField(field('Working hypothesis'),'pump_degradation');
  await setField(field('Tool'),'simulate_fault');
  await click(button('Compute tool result')); const oldTool=api.operations.at(-1);
  await setField(field('Observe through'),93);
  assert.equal(field('Working hypothesis').value,''); assert.equal(field('Working hypothesis').disabled,true);
  assert.equal(button('Compute tool result').disabled,true);
  await setField(field('Question or instruction'),'Explain this window');
  assert.equal(button('Ask using current observations').disabled,true);
  await debounceAnalysis(); await resolveAnalysis(api.analyses.at(-1),'cooling_valve');
  assert.equal(field('Working hypothesis').value,'cooling_valve','old manual hypothesis does not carry into another window');
  assert.equal(field('Tool').value,'simulate_fault','tool choice survives observation changes');
  await click(button('Compute tool result')); const current=api.operations.at(-1);
  assert.equal(current.body.asOf,93); assert.equal(current.body.hypothesis,'cooling_valve');
  assert.equal(current.body.calls[0].args.hypothesis,'cooling_valve');
  await resolveOperation(current,'current-93'); await resolveOperation(oldTool,'old-300');
  assert.match(container.querySelector('.p-trace-result').textContent,/current-93/); assert.ok(!isMasked(container.querySelector('.p-trace-result')));
  await click(button('Ask using current observations')); const oldAssistant=api.operations.at(-1);
  await setField(field('Observation window start'),5); await debounceAnalysis(); await resolveAnalysis(api.analyses.at(-1));
  assert.ok(isMasked(container.querySelector('.p-trace-result')),'a different start masks previous tool output');
  await click(button('Ask using current observations')); const assistant=api.operations.at(-1);
  assert.equal(assistant.body.windowStart,5); assert.equal(assistant.body.asOf,93); assert.equal(assistant.body.hypothesis,'pump_degradation');
  await resolveOperation(assistant,'current-assistant'); await resolveOperation(oldAssistant,'stale-assistant');
  assert.match(container.querySelector('.p-trace-result').textContent,/current-assistant/);
  assert.ok(!container.querySelector('.p-trace-result').textContent.includes('stale-assistant'));
});

test('interventions preserve parameters while gating pending contexts and hiding old-window predictions',async()=>{
  const api=runtimeAPI(); await openRuntime(api,300,'interventions');
  await setField(field('Bypass cooling flow'),17.5);
  const submit=async()=>act(async()=>field('Model source').closest('form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));
  await submit(); const old=api.operations.at(-1);
  await setField(field('Observe through'),93);
  assert.equal(button('Run intervention comparison').disabled,true);
  await submit(); assert.equal(api.operations.length,1,'pending contexts cannot be submitted programmatically either');
  await debounceAnalysis(); await resolveAnalysis(api.analyses.at(-1));
  assert.equal(field('Bypass cooling flow').value,'17.5');
  assert.equal(button('Run intervention comparison').disabled,false);
  await submit(); const current=api.operations.at(-1);
  assert.equal(current.body.asOf,93); assert.equal(current.body.parameters.bypassFlow,17.5); assert.equal(current.body.hypothesis,'pump_degradation');
  await resolveOperation(current,'current'); const graph=container.querySelector('.runtime-forecast svg');
  await resolveOperation(old,'old');
  assert.match(container.querySelector('.runtime-forecast .ws-notice').textContent,/observed through 93s/);
  await setField(field('Observation window start'),5);
  assert.ok(isMasked(container.querySelector('.runtime-forecast'))); assert.equal(container.querySelector('.runtime-forecast svg'),graph);
  await debounceAnalysis(); await resolveAnalysis(api.analyses.at(-1));
  assert.ok(isMasked(container.querySelector('.runtime-forecast')),'fresh diagnosis does not turn an old forecast into a current result');
  await setField(field('Observation window start'),0);
  assert.equal(isMasked(container.querySelector('.runtime-forecast')),false,'returning to the exact cached context restores its valid forecast');
  assert.equal(container.querySelector('.runtime-forecast svg'),graph); assert.equal(field('Bypass cooling flow').value,'17.5');
});

test('late session loads and old-session analyses cannot replace the selected session',async()=>{
  const api=runtimeAPI({deferSessions:true});
  await mount(React.createElement(RuntimeWorkbench,{simulationId:'A'}));
  await act(async()=>api.loads[0].resolve(response(simulation('A'))));
  await debounceAnalysis(); const oldAnalysis=api.analyses.at(-1);
  await setField(field('Saved simulation'),'B'); const oldLoad=api.loads.at(-1);
  await setField(field('Saved simulation'),'C'); const selected=api.loads.at(-1);
  await act(async()=>selected.resolve(response(simulation('C'))));
  await act(async()=>oldLoad.resolve(response(simulation('B'))));
  await resolveAnalysis(oldAnalysis);
  assert.equal(field('Saved simulation').value,'C'); assert.equal(container.querySelector('.runtime-timeline h2').textContent,'Session C');
  assert.equal(container.querySelector('.p-candidates'),null,'old session analysis cannot populate a new session');
  await debounceAnalysis(); const current=api.analyses.at(-1); assert.match(current.url,/simulations\/C\/analysis/);
  await resolveAnalysis(current); assert.ok(container.querySelector('.p-candidates'));
});

function incidentResult(id = 'incident-result') {
  const intervals = [
    { start: 340, end: 379, samples: 40, peakTime: 350, peakScore: 30, signals: names.slice(0, 3), contributions: names.slice(0, 3).map((signal, i) => ({ signal, value: 30 / (i + 1) })) },
    { start: 510, end: 554, samples: 45, peakTime: 520, peakScore: 20, signals: names.slice(2, 5), contributions: names.slice(2, 5).map((signal, i) => ({ signal, value: 20 / (i + 1) })) },
  ];
  return { id, workspaceId: 'test', datasetId: 'incident-data', name: '反应器分析', algorithmLabel: 'Robust Max-Z', completedAt: '2026-10-24T00:00:00Z', createdAt: '2026-10-24T00:00:00Z', durationMs: 3,
    config: { signals: names, analysisRange: [200, 699], baselineRange: [0, 199], datasetId: 'incident-data', algorithm: 'robust-maxz', alpha: .01 },
    times: [200, 340, 350, 379, 510, 520, 554, 699], scores: [0, 15, 30, 10, 15, 20, 10, 0], threshold: 3, intervals, relatedSignals: names.slice(0, 3), signalContributions: intervals[0].contributions, contributionMetric: 'absolute-robust-z', peakTime: 350,
    summary: { analysisSamples: 500, baselineSamples: 200, fitSamples: 140, calibrationSamples: 60, flaggedSamples: 85, peakScore: 30, firstDetection: 340, imputedValues: { analysis: 0 } }, model: {} };
}
const emptyIncident = () => ({ id: 'event-one', workspace_id: 'test', title: '反应器事件', description: '持续调查', status: 'open', start_time: 330, end_time: 560, time_origin: null, conclusion: '', created_at: '2026-10-24T00:00:00Z', updated_at: '2026-10-24T00:00:00Z', entries: [], links: [] });
function dialogField(label) {
  const dialog = container.querySelector('dialog[open]'); assert.ok(dialog, 'modal is open');
  const element = [...dialog.querySelectorAll('label')].find(n => matchesLabel(n.textContent, label));
  assert.ok(element, `dialog field ${label} exists`); return element.querySelector('input,textarea,select');
}
function inputFor(label, within = container) {
  const element = [...within.querySelectorAll('label')].find(n => matchesLabel(n.textContent, label));
  assert.ok(element, `field ${label} exists`); return element.querySelector('input,textarea,select');
}
function matchesLabel(content, source) {
  return content.startsWith(t(source));
}

test('regime workspace freezes selected context, reopens the evaluation, and links a transition alarm', async () => {
  const fitA = dataset('Reduced-load normal'), fitB = dataset('Rated-load normal'), evaluation = dataset('Production replay');
  const datasets = [fitA, fitB, evaluation], endpoint = '/api/workspaces/test/regimes';
  const createdAt = '2026-11-11T00:00:00Z';
  const behavior = { validSamples: 4, totalSamples: 4, alarmSamples: 1, alarmIntervalCount: 1, alarmFraction: .25 };
  const comparison = { behavior, detection: { windows: null }, labelled: null };
  const detector = { algorithm: 'robust-maxz', alpha: .01, variance: .9, threshold: 0 };
  const fittedMode = { center: [1], covariance: [[.5]], regularizedCovariance: [[.4]], distanceThreshold: 5, fitSamples: 50, calibrationSamples: 40, detector };
  let model, run, incidentLink;
  globalThis.fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    if (url === endpoint + '/models') return response({ models: model ? [model] : [] });
    if (url === endpoint + '/runs' && !body) return response({ runs: run ? [run] : [] });
    if (url === endpoint + '/fit' && body) {
      assert.deepEqual(body.recognition.recognitionSignals, [names[0]]);
      assert.deepEqual(body.signals, names);
      assert.equal(body.modes.length, 2);
      assert.equal(body.modes[0].fit[0].datasetId, fitA.id);
      assert.ok(body.modes[0].fit[0].range[1] < body.modes[0].calibration[0].range[0]);
      model = { id: 'model-1', createdAt, name: body.name, config: body, sources: { [fitA.id]: fitA, [fitB.id]: fitB }, referenceDatasetId: fitA.id,
        model: { version: '1', modes: { 'mode-1': fittedMode, 'mode-2': fittedMode }, comparisons: [], globalDetector: detector, singleDetector: detector } };
      return response(model);
    }
    if (url === endpoint + '/models/model-1') return response(model);
    if (url === endpoint + '/runs' && body) {
      assert.equal(body.modelId, model.id);
      assert.equal(body.evaluation.datasetId, evaluation.id);
      const times = [0, 1, 2, 3];
      const decisions = times.map((time, i) => ({
        time, mode: i === 0 ? 'mode-1' : i === 3 ? 'mode-2' : null, activeMode: i === 3 ? 'mode-2' : 'mode-1',
        candidateMode: i > 1 ? 'mode-2' : null, scoringMode: i > 1 ? 'mode-2' : 'mode-1',
        recognition: i === 1 ? 'unknown' : 'supported', evidence: { 'mode-1': { distance: 1, threshold: 4, discriminant: 1.5, supported: true } },
        margin: null, status: ['normal', 'unknown', 'abnormal', 'normal'][i], transition: i === 2, candidateSamples: i === 2 ? 1 : 0,
        alarm: i === 2, score: i === 2 ? 9 : 0, threshold: 0, globalScore: 1, globalThreshold: 2, globalAlarm: false,
        singleScore: i === 2 ? 9 : 0, singleThreshold: 4, singleAlarm: i === 2,
      }));
      run = { id: 'run-1', analysisId: 'run-1', modelId: model.id, datasetId: evaluation.id, name: body.name, createdAt, evaluation: body.evaluation, model,
        source: evaluation, gapThreshold: 5, labelSet: null, protocol: 'distinct-dataset', times, decisions,
        series: { time: times, values: { [names[0]]: [10, 11, 12, 13] } },
        intervals: [{ start: 2, end: 2, peakTime: 2, peakScore: 9, samples: 1, kind: 'transition', mode: 'mode-2', signals: [names[0]], contributions: [{ signal: names[0], value: 9 }] }],
        transitions: [{ fromMode: 'mode-1', toMode: 'mode-2', startTime: 1, candidateTime: 2, confirmedTime: 3, endTime: 3, resolvedTime: 3, outcome: 'confirmed', initialMargin: null }],
        metrics: { regime: comparison, global: comparison, single: comparison } };
      return response(run);
    }
    if (url === endpoint + '/runs/run-1') return response(run);
    if (url === '/api/workspaces/test/incidents') return response({ incidents: [emptyIncident()] });
    if (url === '/api/incidents/event-one/links') { incidentLink = body; return response(emptyIncident()); }
    throw new Error(`Unexpected request ${url}`);
  };
  const page = props => React.createElement(RegimeWorkspace, { workspaceId: 'test', datasets, ...props });
  await mount(page());
  await setField(inputFor('Model name'), 'Reactor regimes');
  const modes = container.querySelectorAll('.regime-mode');
  await setField(inputFor('Operating-mode label', modes[0]), 'Low load');
  await setField(inputFor('Operating-mode label', modes[1]), 'High load');
  assert.ok(button('Fit and save model').disabled, 'an explicit context signal is required');
  await click(container.querySelector(`[aria-label="Recognize using ${names[0]}"]`));
  await click(button('Fit and save model'));
  assert.equal(window.location.hash, '#/workspaces/test/regimes/models/model-1');
  await act(async () => root.render(page({ section: 'models', itemId: 'model-1' })));
  assert.match(container.textContent, /Frozen model evidence/);
  await setField(inputFor('Run name'), 'Shift replay');
  await click(button('Run and save evaluation'));
  assert.equal(window.location.hash, '#/workspaces/test/regimes/runs/run-1');
  await act(async () => root.render(page({ section: 'runs', itemId: 'run-1' })));
  assert.match(container.textContent, /Detector comparison.*Global detector.*Single-mode detector/s);
  await click(button('Inspect transition'));
  assert.match(container.querySelector('.regime-cursor output').textContent, /2 s.*Sample 3/);
  assert.match(container.querySelector('.regime-evidence').textContent, /Abnormal.*Candidate modeHigh load/s);
  assert.match(container.textContent, /Alarm peak evidence/);
  assert.match(container.textContent, /Operating regime monitoring.*Detector comparison/s);
  assert.match(container.textContent, /Low load.*High load/s, 'mode labels remain user-owned');
  await click(button('Link to incident'));
  await click(button("Add to existing incident"));
  await click(button("Add and open incident"));
  assert.deepEqual(incidentLink, { kind: 'interval', datasetId: evaluation.id, analysisId: 'run-1', intervalIndex: 0 });
  assert.equal(window.location.hash, '#/workspaces/test/incidents/event-one');
});

test('result interval cards and complete record create or join a persistent incident with editable event fields', async () => {
  const result = incidentResult(), writes = [], saved = emptyIncident();
  globalThis.fetch = async (url, options = {}) => {
    if (url.includes('/series?')) return response(seriesFor(url));
    if (url === '/api/workspaces/test/incidents' && !options.body) return response({ incidents: [saved] });
    writes.push({ url, method: options.method, body: JSON.parse(options.body) }); return response(saved);
  };
  await mount(React.createElement(ResultView, { result, dataset: dataset('incident-data'), signalPicker: () => null }));
  const card = container.querySelector('.ws-finding');
  const cardStart = Number(card.querySelector('button[aria-label]').getAttribute('aria-label').match(/interval (\d+)/)[1]);
  await click([...card.querySelectorAll('button')].find(n => n.textContent === t("Create incident")));
  assert.equal(dialogField("Start time").value, String(cardStart));
  await setField(dialogField("Incident title"), '用户确认的事件');
  await setField(dialogField("Start time"), 320);
  await setField(dialogField("Incident description"), '等待现场复核');
  await click(button("Create and open incident"));
  assert.equal(writes[0].url, '/api/workspaces/test/incidents');
  assert.equal(writes[0].body.title, '用户确认的事件');
  assert.equal(writes[0].body.start_time, 320);
  assert.equal(writes[0].body.description, '等待现场复核');
  assert.deepEqual(writes[0].body.source, { kind: 'interval', analysisId: result.id, datasetId: 'incident-data', intervalIndex: result.intervals.findIndex(i => i.start === cardStart) });
  assert.equal(window.location.hash, '#/workspaces/test/incidents/event-one');
  const row = container.querySelector('tbody tr');
  await click([...row.querySelectorAll('button')].find(n => n.textContent === t("Add to existing incident")));
  assert.equal(dialogField("Select incident").value, saved.id);
  await click(button("Add and open incident"));
  assert.equal(writes[1].url, '/api/incidents/event-one/links');
  assert.equal(writes[1].body.intervalIndex, 0);
});

test('incident workstation edits notes, hypotheses, evidence relationships and conclusions, then reopens saved content and curves', async () => {
  const result = incidentResult('incident-detail-analysis'), data = dataset('incident-data');
  let saved = emptyIncident(), identity = 0;
  saved.links = [{ id: 'source-one', incident_id: saved.id, kind: 'interval', reference_id: result.id, selector: '0', created_at: saved.created_at,
    details: { title: result.name, analysisId: result.id, datasetId: data.id, algorithmLabel: result.algorithmLabel, analysisRange: result.config.analysisRange, intervalIndex: 0, interval: result.intervals[0], contributionMetric: result.contributionMetric } }];
  const writes = [];
  globalThis.fetch = async (url, options = {}) => {
    if (url.includes('/series?')) return response(seriesFor(url));
    if (url === `/api/analyses/${result.id}`) return response(result);
    if (url.includes('/timeline?')) return response(incidentView(saved, [result]));
    if (url === '/api/incidents/event-one' && options.method === 'GET') return response(saved);
    const body = options.body ? JSON.parse(options.body) : {};
    writes.push({ url, method: options.method, body });
    if (url === '/api/incidents/event-one') saved = { ...saved, ...body };
    else if (url.endsWith('/entries') && options.method === 'POST') saved = { ...saved, entries: [...saved.entries, { id: `entry-${++identity}`, incident_id: saved.id, created_at: saved.created_at, updated_at: saved.updated_at, ...body }] };
    else if (options.method === 'PATCH') { const id = url.split('/').at(-1); saved = { ...saved, entries: saved.entries.map(e => e.id === id ? { ...e, ...body } : e) }; }
    else throw new Error(`Unexpected incident operation ${url}`);
    return response(saved);
  };
  await mount(React.createElement(IncidentDetail, { initial: structuredClone(saved), datasets: [data], jobs: [] }));
  assert.ok(curve(names[0]), 'linked interval plots the raw dataset');
  assert.match([...container.querySelectorAll('a')].find(a => a.textContent === t("Open original analysis ↗")).getAttribute('href'), /incident-detail-analysis\/0$/);
  await click(button("＋ Add hypothesis"));
  await setField(dialogField("Record title"), '冷却侧变化');
  await setField(dialogField("Record content"), '先核对冷却回路');
  await click(button("Save investigation record"));
  await click(button("＋ Add evidence"));
  await setField(dialogField("Record title"), '温度首先升高');
  await setField(dialogField("Record content"), '温度在区间开始前已偏离。');
  await setField(dialogField("Related hypothesis"), 'entry-1');
  await setField(dialogField("Evidence relationship"), 'support');
  await setField(dialogField('Observation time'), 345);
  await click(button("Save investigation record"));
  const evidence = saved.entries.find(e => e.kind === 'evidence');
  assert.equal(evidence.hypothesis_id, 'entry-1'); assert.equal(evidence.stance, 'support');
  assert.equal(evidence.source_link_id, 'source-one'); assert.equal(evidence.observed_at, 345);
  await click(button("＋ Add note"));
  await setField(dialogField("Record title"), '现场复核'); await setField(dialogField("Record content"), '已检查交接记录。');
  await click(button("Save investigation record"));
  const noteCard = [...container.querySelectorAll('article')].find(a => a.textContent.includes('现场复核'));
  await click([...noteCard.querySelectorAll('button')].find(b => b.textContent === t("Edit")));
  await setField(dialogField("Record content"), '已检查交接记录，等待冷却水记录。');
  await click(button("Save investigation record"));
  await setField(inputFor("Incident title"), '反应器持续调查');
  await setField(inputFor("Investigation status"), 'investigating');
  await click(button("Save information"));
  await setField(inputFor("Investigation conclusion"), '暂时支持冷却侧变化，继续验证。');
  await click(button("Save investigation conclusion"));
  assert.ok(writes.some(w => w.method === 'PATCH' && w.body.conclusion === '暂时支持冷却侧变化，继续验证。'));
  await act(async () => root.unmount()); container.remove(); root = null;
  await mount(React.createElement(IncidentsPage, { workspaceId: 'test', incidentId: saved.id, datasets: [data], jobs: [] }));
  assert.equal(inputFor("Incident title").value, '反应器持续调查');
  assert.equal(inputFor("Investigation conclusion").value, saved.conclusion);
  assert.match(container.textContent, /等待冷却水记录/);
  assert.match(container.textContent, /Supports: 冷却侧变化/);
  assert.ok(curve(names[0]));
});

test('incident list filters by status, title and time using the workspace API', async () => {
  const requests = [], incident = { ...emptyIncident(), analysis_count: 2, interval_count: 3 };
  globalThis.fetch = async url => { requests.push(url); return response({ incidents: [incident] }); };
  await mount(React.createElement(IncidentsPage, { workspaceId: 'test', datasets: [], jobs: [] }));
  await act(async () => new Promise(resolve => setTimeout(resolve, 220)));
  assert.match(container.textContent, /2 analyses · 3 intervals/);
  await setField(inputFor("Investigation status"), 'investigating');
  await setField(inputFor("Find incidents"), "reactor");
  await setField(inputFor('Intersecting range start'), 300);
  await setField(inputFor('Intersecting range end'), 600);
  await act(async () => new Promise(resolve => setTimeout(resolve, 220)));
  const query = new URL(requests.at(-1), 'http://localhost').searchParams;
  assert.equal(query.get('status'), 'investigating'); assert.equal(query.get('q'), "reactor");
  assert.equal(query.get('start'), '300'); assert.equal(query.get('end'), '600');
  assert.equal(container.querySelector('.ws-history-row').getAttribute('href'), '#/workspaces/test/incidents/event-one');
});

test('saved runtime experiment reopens its observation and intervention parameters and links to an incident', async () => {
  const api = runtimeAPI(), delegate = globalThis.fetch;
  const savedBody = { asOf: 156, windowStart: 0, hypothesis: 'cooling_valve', mode: 'known', at: 162, horizon: 400, actions: ['bypass'], parameters: { bypassFlow: 63 } };
  const run = { id: 'saved-trial', kind: 'intervention', request: savedBody, result: forecastFor(savedBody), createdAt: '2026-10-24T00:00:00Z' }, writes = [];
  globalThis.fetch = async (url, options = {}) => {
    if (url === '/api/simulations?workspaceId=test') return response({ simulations: [{ ...simulation('A'), workspaceId: 'test' }] });
    if (url === '/api/simulations/A') return response({ ...simulation('A'), workspaceId: 'test', datasetId: 'saved-model-data' });
    if (url === '/api/simulations/A/runs') return response({ runs: [run] });
    if (url === '/api/workspaces/test/incidents') return response({ incidents: [emptyIncident()] });
    if (url === '/api/incidents/event-one/links') { writes.push(JSON.parse(options.body)); return response(emptyIncident()); }
    return delegate(url, options);
  };
  await mount(React.createElement(RuntimeWorkbench, { workspaceId: 'test', simulationId: 'A', runId: run.id }));
  await debounceAnalysis(); await resolveAnalysis(api.analyses.at(-1));
  assert.ok(container.querySelector('a[href="#/workspaces/test/datasets/saved-model-data"]'), 'reopened simulation links to its exact saved Dataset');
  assert.ok(container.querySelector('a[href="#/workspaces/test/experiments/new/saved-model-data"]'), 'model Dataset can continue directly into an experiment');
  assert.equal(field('Observe through').value, '156'); assert.equal(field('Intervention starts at').value, '162');
  assert.equal(field('Prediction ends at').value, '400'); assert.equal(field('Bypass cooling flow').value, '63');
  assert.ok(container.querySelector('.runtime-forecast'), 'stored forecast opens without recomputation');
  await click(button("Link most recent completed result"));
  await click([...container.querySelectorAll('dialog button')].find(b => b.textContent === t("Add to existing incident")));
  await click(button("Add and open incident"));
  assert.deepEqual(writes[0], { kind: 'run', simulationId: 'A', runId: 'saved-trial', hypothesis: 'cooling_valve' });
  assert.equal(window.location.hash, '#/workspaces/test/incidents/event-one');
});

test('restored tool output stays tied to its saved observation window after switching tabs', async () => {
  const api = runtimeAPI(), delegate = globalThis.fetch;
  const run = { id: 'saved-tools', kind: 'tools', request: { asOf: 93, windowStart: 0, hypothesis: 'cooling_valve', calls: [{ tool: 'inspect_signal_window', args: { signal: 'valve' } }] },
    result: { trace: [{ index: 1, tool: 'inspect_signal_window', args: { signal: 'valve' }, result: { marker: 'saved-window-93' }, status: 'computed' }] }, createdAt: '2026-10-24T00:00:00Z' };
  globalThis.fetch = async (url, options) => url === '/api/simulations/A/runs' ? response({ runs: [run] }) : delegate(url, options);
  await mount(React.createElement(RuntimeWorkbench, { simulationId: 'A', runId: run.id }));
  await debounceAnalysis(); await resolveAnalysis(api.analyses.at(-1));
  assert.equal(isMasked(container.querySelector('.p-trace-result')), false);
  assert.match(container.querySelector('.p-trace-result').textContent, /saved-window-93/);
  await setField(field('Observe through'), 150); await debounceAnalysis(); await resolveAnalysis(api.analyses.at(-1));
  assert.equal(isMasked(container.querySelector('.p-trace-result')), true);
  await click(button('Evidence & topology')); await click(button('Investigation tools'));
  assert.equal(isMasked(container.querySelector('.p-trace-result')), true, 'remounting cannot label a saved 93-second result as current 150-second evidence');
});

function incidentView(incident, results, selected = results.map(r => r.id)) {
  const axisId = 'dataset:incident-data';
  const analyses = results.map(r => ({ id: r.id, result: r, datasetId: r.datasetId, datasetName: '现场数据', axisId, offset: 0, scope: "Full analysis", linkId: `link-${r.id}`, observedSpans: [[200, 699]],
    intervals: r.intervals.map((i, index) => ({ ...i, index, linkId: `link-${r.id}` })) }));
  return { incident, workspace: { id: 'test', name: '工业调查' }, generatedAt: incident.updated_at, primaryAxisId: axisId, datasets: [dataset('incident-data')],
    axes: [{ id: axisId, label: '现场数据', origin: null, start: 330, end: 560 }], analyses,
    comparisons: selected.length ? [{ axisId, analysisIds: selected, firstDetection: 340, firstAlarmSpread: selected.length > 1 ? 0 : null, common: [], unique: [], segments: selected.length > 1 ? [{ kind: 'common', start: 340, end: 379, analysisIds: selected }] : [] }] : [],
    events: [...analyses.flatMap(a => a.intervals.map(i => ({ id: `alarm-${a.id}-${i.index}`, kind: 'alarm', title: `${a.result.algorithmLabel} · 异常区间`, axisId, start: i.start, end: i.end, peakTime: i.peakTime, peakScore: i.peakScore, analysisId: a.id, intervalIndex: i.index, linkId: a.linkId, recordedAt: incident.created_at, target: 'source' }))),
      ...incident.entries.map(entry => ({ id: `entry:${entry.id}`, kind: entry.kind, title: entry.title, start: entry.observed_at, end: entry.observed_at, axisId: entry.observed_at == null ? null : axisId, entryId: entry.id, linkId: entry.source_link_id, content: entry.content, recordedAt: entry.created_at, target: 'entry' }))] };
}

test('incident timeline filters, navigates alarms and evidence, and shares cursor/window with comparison and raw signals', async () => {
  const maxz = incidentResult('timeline-maxz'), pca = { ...incidentResult('timeline-pca'), algorithmLabel: 'PCA-Q', name: 'PCA 分析' };
  const saved = emptyIncident(), queries = [], samples = [];
  saved.links = [maxz, pca].map(result => ({ id: `link-${result.id}`, incident_id: saved.id, kind: 'analysis', reference_id: result.id, selector: '', created_at: saved.created_at,
    details: { title: result.name, datasetId: result.datasetId, analysisId: result.id, analysisRange: result.config.analysisRange, signals: names.slice(0, 3), algorithmLabel: result.algorithmLabel } }));
  saved.entries = [{ id: 'observed-note', incident_id: saved.id, kind: 'note', title: '现场温升记录', content: '温度上升已核实', observed_at: 345, source_link_id: saved.links[0].id, stance: 'neutral', hypothesis_id: null, created_at: saved.created_at, updated_at: saved.updated_at }];
  globalThis.fetch = async url => {
    if (url.includes('/timeline?')) { queries.push(url); const q = new URL(url, 'http://localhost').searchParams; return response(incidentView(saved, [maxz, pca], q.has('analysis') ? q.getAll('analysis').filter(Boolean) : undefined)); }
    if (url.includes('/series?')) return response(seriesFor(url));
    if (url.includes('/sample?')) { samples.push(url); const t = Number(new URL(url, 'http://localhost').searchParams.get('at')); return response({ time: t, previousTime: t-1, nextTime: t+1, values: Object.fromEntries(names.map(s => [s, 30])), previous: Object.fromEntries(names.map(s => [s, 28])) }); }
    if (url === `/api/analyses/${maxz.id}`) return response(maxz);
    if (url === `/api/analyses/${pca.id}`) return response(pca);
    throw new Error(`Unexpected request ${url}`);
  };
  await mount(React.createElement(IncidentDetail, { initial: saved, datasets: [dataset('incident-data')], jobs: [] }));
  const timeline = container.querySelector('#incident-timeline'), comparison = container.querySelector('#incident-comparison');
  assert.equal(timeline.querySelectorAll('.incident-event-list li').length, 5);
  await setField(inputFor("Analysis result", timeline), pca.id);
  assert.equal(timeline.querySelectorAll('.incident-event-list li').length, 2);
  await setField(inputFor('Filter start', timeline), 500);
  assert.equal(timeline.querySelectorAll('.incident-event-list li').length, 1);
  await click(timeline.querySelector('.incident-event-list button'));
  assert.ok(Number(inputFor('Window start').value) < 510);
  assert.ok(Number(inputFor('Window end').value) > 554);
  assert.equal(inputFor("Observation time (source seconds)").value, '520');
  assert.ok(container.querySelector('.incident-preview svg [data-selected-time="520"]'));
  assert.match(container.querySelector('.incident-comparison-scores').textContent, /PCA 分析/);
  await setField(inputFor("Synchronized observation time"), 530);
  assert.ok(container.querySelector('.incident-preview svg [data-selected-time="530"]'));
  assert.ok(container.querySelector('.incident-comparison-scores svg [data-selected-time="530"]'));
  await act(async () => new Promise(resolve => setTimeout(resolve, 130)));
  assert.match(container.querySelector("[aria-label=\"" + t("Multivariable observations at the same time") + "\"]").textContent, /30/);
  assert.ok(samples.some(url => url.includes('at=530')));
  await click(comparison.querySelector('.ws-option-grid input'));
  assert.match(queries.at(-1), /analysis=timeline-pca/);
  assert.equal(comparison.querySelectorAll('tbody')[0].rows.length, 1);
  await setField(inputFor("Analysis result", timeline), ''); await setField(inputFor('Filter start', timeline), ''); await setField(inputFor("Event category", timeline), 'note');
  assert.equal(timeline.querySelectorAll('.incident-event-list li').length, 1);
  await click(timeline.querySelector('.incident-event-list button'));
  assert.equal(dialogField("Record title").value, '现场温升记录');
  assert.equal(dialogField('Observation time').value, '345');
});

test('professional report preview/export uses current saved content and invalidates an older generation', async () => {
  const { IncidentReport } = require('../src/workspace/investigation/IncidentReport.tsx');
  let saved = emptyIncident(), reports = 0;
  globalThis.fetch = async url => {
    assert.match(url, /report\.html$/); reports++;
    return { ok: true, headers: { get: () => 'text/html; charset=utf-8' }, text: async () => `<!doctype html><html><body><h1>真实事件报告</h1><p>${saved.conclusion || '尚未形成结论'}</p><svg><path d="M0 0 L1 2"/></svg></body></html>` };
  };
  await mount(React.createElement(IncidentReport, { incident: saved }));
  assert.equal(button("Export offline HTML").disabled, true);
  await click(button("Generate report"));
  assert.match(container.querySelector('iframe').getAttribute('srcdoc'), /尚未形成结论/);
  let printed = 0;
  const frame = container.querySelector('iframe');
  frame.contentWindow.print = () => printed++;
  frame.contentWindow.focus = () => {};
  await act(async () => frame.dispatchEvent(new window.Event('load')));
  await click(button("Print / Save PDF"));
  assert.equal(printed, 1);
  const originalCreate = URL.createObjectURL, originalRevoke = URL.revokeObjectURL, originalClick = window.HTMLAnchorElement.prototype.click;
  let blob, filename;
  URL.createObjectURL = value => { blob = value; return 'blob:test-report'; };
  URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function () { filename = this.download; };
  try {
    await click(button("Export offline HTML"));
    assert.match(filename, /l5-incident-event-one\.html/);
    assert.match(await blob.text(), /<svg>/);
  } finally { URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke; window.HTMLAnchorElement.prototype.click = originalClick; }
  saved = { ...saved, conclusion: '更新后的现场结论', updated_at: '2026-10-24T03:00:00Z' };
  await act(async () => root.render(React.createElement(IncidentReport, { incident: saved })));
  assert.equal(container.querySelector('iframe'), null);
  assert.equal(button("Print / Save PDF").disabled, true);
  await click(button("Generate report"));
  assert.match(container.querySelector('iframe').getAttribute('srcdoc'), /更新后的现场结论/);
  assert.equal(reports, 2);
});

test('timeline experiment links reopen the stored run rather than the current cursor window', async () => {
  const { IncidentTimeline } = require('../src/workspace/investigation/IncidentTimeline.tsx');
  const saved = emptyIncident();
  saved.links = [{ id: 'trial-link', kind: 'run', details: { title: "Save experiment", simulationId: 'sim-one', run: { id: 'trial-one', request: { asOf: 93, windowStart: 0 }, kind: 'intervention' } } }];
  const view = { ...incidentView(saved, []), axes: [{ id: 'simulation:sim-one', label: '冷却模拟', start: 0, end: 100, origin: null }], primaryAxisId: 'simulation:sim-one', events: [{ id: 'trial-event', kind: 'experiment', title: "Intervention experiment", start: 93, end: 93, axisId: 'simulation:sim-one', linkId: 'trial-link', observationWindow: [0, 93], actionAt: 96, recordedAt: saved.created_at, target: 'source' }] };
  globalThis.fetch = async () => response(view);
  let selected;
  await mount(React.createElement(IncidentTimeline, { incident: saved, selection: null, onSelect: value => selected = value, onRecord() {}, onSection() {} }));
  await click(container.querySelector('.incident-event-list button'));
  assert.equal(selected.at, 93); assert.equal(selected.linkId, 'trial-link');
  assert.equal(container.querySelector('.incident-event-list a').getAttribute('href'), '#/workspaces/test/simulations/sim-one/trial-one');
});

test('removing an analysis source reconciles the incident comparison selection without stale source requests', async () => {
  const { IncidentTimeline } = require('../src/workspace/investigation/IncidentTimeline.tsx');
  const results = [incidentResult('remove-maxz'), { ...incidentResult('remove-pca'), name: 'PCA' }];
  let saved = emptyIncident();
  saved.links = results.map(r => ({ id: `link-${r.id}`, details: { analysisId: r.id } }));
  const queries = [];
  globalThis.fetch = async url => {
    queries.push(url);
    const ids = new Set(saved.links.map(l => l.details.analysisId)), selected = new URL(url, 'http://localhost').searchParams;
    return response(incidentView(saved, results.filter(r => ids.has(r.id)), selected.has('analysis') ? selected.getAll('analysis').filter(Boolean) : undefined));
  };
  const render = () => React.createElement(IncidentTimeline, { incident: saved, selection: null, onSelect() {}, onRecord() {}, onSection() {} });
  await mount(render());
  await click(container.querySelector('#incident-comparison input'));
  saved = { ...saved, links: [saved.links[0]], updated_at: '2026-10-24T04:00:00Z' };
  await act(async () => root.render(render()));
  assert.equal(new URL(queries.at(-1), 'http://localhost').searchParams.get('analysis'), '');
  assert.equal(container.querySelector('#incident-comparison input').checked, false);
  assert.equal(container.querySelector('[role=alert]'), null);
});

test('late report responses cannot replace a newer saved incident generation', async () => {
  const { IncidentReport } = require('../src/workspace/investigation/IncidentReport.tsx');
  let resolveOld;
  globalThis.fetch = () => new Promise(resolve => resolveOld = resolve);
  let saved = emptyIncident();
  await mount(React.createElement(IncidentReport, { incident: saved }));
  await click(button("Generate report"));
  saved = { ...saved, conclusion: '最新结论' };
  await act(async () => root.render(React.createElement(IncidentReport, { incident: saved })));
  globalThis.fetch = async () => ({ ok: true, headers: { get: () => 'text/html' }, text: async () => '<html><body>最新结论</body></html>' });
  await click(button("Generate report"));
  await act(async () => resolveOld({ ok: true, headers: { get: () => 'text/html' }, text: async () => '<html><body>旧结论</body></html>' }));
  assert.match(container.querySelector('iframe').getAttribute('srcdoc'), /最新结论/);
  assert.doesNotMatch(container.querySelector('iframe').getAttribute('srcdoc'), /旧结论/);
});


function foundationData() {
  const sources = ['temperature', 'temperature-peer', 'pressure'].map((id, i) => {
    const data = dataset(id, 11), name = i < 2 ? 'temp' : 'pressure';
    const column = { id: 'signal-' + id, name, displayName: i < 2 ? 'Motor temperature' : 'Feed pressure', unit: i < 2 ? '°C' : 'kPa', category: i < 2 ? 'Temperature' : 'Pressure', device: i === 2 ? 'Pump B' : 'Motor A', tags: ['campaign'], logicalKey: i < 2 ? 'motor.temperature' : '', missing: 1, min: 1, max: 10 };
    const q = { totalCount: 11, validCount: 10, finiteCount: 10, missing: 1, missingFraction: 1/11, invalidTimeMeasurements: 0, min: 1, max: 10, mean: 5, std: 2, missingSpans: [{ start: 4, end: 4, count: 1 }], availableSpans: [{ start: 0, end: 3, count: 4 }, { start: 5, end: 10, count: 6 }] };
    data.metadata.columns = [column]; data.metadata.time = { kind: 'datetime', origin: '1970-01-01T00:16:40Z', column: 't', start: 0, end: 10 };
    data.metadata.clock = { key: 'dataset:' + id, axisId: 'utc', offset: 1000, label: 'UTC absolute time', reference: { mode: 'native' } };
    data.metadata.quality = { totalCount: 11, timedCount: 11, invalidTimeCount: 0, invalidTimes: [], start: 0, end: 10, typicalInterval: 1, gapThreshold: 5, gaps: [], gapCount: 0, irregularCount: 0, irregular: false, duplicateCount: 0, duplicates: [], signals: { [name]: q } };
    return data;
  });
  const catalog = sources.map(d => ({ ...d.metadata.columns[0], datasetId: d.id, datasetName: d.name, workspaceId: 'test', source: 'CSV', time: d.metadata.time, clock: d.metadata.clock, quality: d.metadata.quality.signals[d.metadata.columns[0].name] }));
  return { sources, catalog };
}
function foundationAPI(fixture, savedViews = [], defer = false) {
  const requests = [], pending = [];
  globalThis.fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    requests.push({ url, body, method: options.method, signal: options.signal });
    if (url.endsWith('/signals')) return response({ signals: fixture.catalog });
    if (url.endsWith('/views') && !body) return response({ views: savedViews });
    if (url.includes('/views') && body) return response({ ...body, id: 'saved-comparison', workspaceId: 'test', updatedAt: '2026-10-24T00:00:00Z' });
    if (url.endsWith('/explore')) {
      const window = { start: 1000, end: 1010, at: 1000, ...body.windows?.utc };
      const result = { axes: body.signalIds.length ? [{ id: 'utc', label: 'UTC absolute time', origin: '1970-01-01T00:00:00Z', start: 1000, end: 1010, window }] : [], series: fixture.catalog.filter(s => body.signalIds.includes(s.id)).map(s => ({ signal: s, times: [window.start, window.end], nativeTimes: [window.start-1000, window.end-1000], values: [1, 10], segmentIds: [1, 2], sourceRows: 11, displayRows: 2 })) };
      return defer ? new Promise(resolve => pending.push({ body, result, resolve })) : response(result);
    }
    if (url.endsWith('/cursor')) return response({ axisId: body.axisId, at: body.at, samples: body.signalIds.map((id, i) => ({ signalId: id, status: i === 2 ? 'outside' : 'measured', value: i === 2 ? null : 42.125, time: body.at+.25, nativeTime: body.at-1000+.25, sourceIndex: 5, deltaSeconds: .25, duplicateCount: 1 })) });
    if (url.startsWith('/api/signals/') || url.endsWith('/time-reference')) return response({});
    throw new Error('Unexpected foundation request: ' + url);
  };
  return { requests, pending };
}

test('signal catalog filters semantics, selects sources and saves metadata against stable IDs', async () => {
  const fixture = foundationData(), api = foundationAPI(fixture);
  const props = { workspaceId: 'test', datasets: fixture.sources, jobs: [], mode: 'signals', onChanged() {}, onAnalyze() {} };
  await mount(React.createElement(SignalWorkspace, props));
  await setField(field('Filter by device'), 'Motor A');
  assert.equal(container.querySelectorAll('.signal-catalog tbody tr').length, 2);
  await click(container.querySelectorAll('.signal-catalog input[type=checkbox]')[0]);
  await click(container.querySelectorAll('.signal-catalog input[type=checkbox]')[1]);
  await click(button('Explore selected signals'));
  assert.match(window.location.hash, /explorer/);
  await act(async () => root.render(React.createElement(SignalWorkspace, { ...props, mode: 'explorer' })));
  assert.equal(container.querySelectorAll('.explorer-lane').length, 2);
  const explorer = api.requests.filter(r => r.url.endsWith('/explore')).at(-1);
  assert.deepEqual(explorer.body.signalIds, fixture.catalog.slice(0, 2).map(s => s.id));
  await act(async () => root.render(React.createElement(SignalEditor, { signal: fixture.catalog[0], catalog: fixture.catalog, onClose() {}, onSaved() {} })));
  await setField(field('Display name'), 'Bearing temperature');
  await setField(field('Physical unit'), 'K');
  await setField(field('Logical measurement key'), 'bearing.temperature');
  await setField(field('Tags'), 'motor, bearing');
  await click(button('Save signal metadata'));
  const mutation = api.requests.at(-1);
  assert.equal(mutation.url, '/api/signals/signal-temperature');
  assert.equal(mutation.method, 'PATCH');
  assert.equal(mutation.body.displayName, 'Bearing temperature');
  assert.deepEqual(mutation.body.tags, ['motor', 'bearing']);
  assert.ok(!('name' in mutation.body), 'source column remains immutable');
});

test('explorer restores saved windows, groups only compatible units and reads full-resolution cursor values', async () => {
  const fixture = foundationData();
  const saved = { id: 'view', workspaceId: 'test', name: 'Saved motor review', signalIds: fixture.catalog.map(s => s.id), windows: { utc: { start: 1002, end: 1008, at: 1005 } }, displayMode: 'overlay' };
  const api = foundationAPI(fixture, [saved]), analyses = [];
  await mount(React.createElement(SignalWorkspace, { workspaceId: 'test', datasets: fixture.sources, jobs: [], mode: 'explorer', onChanged() {}, onAnalyze: (...args) => analyses.push(args) }));
  assert.equal(container.querySelectorAll('.explorer-lane').length, 2, 'two temperature sources overlay, pressure has its own axis scale');
  assert.match(container.textContent, /Opened saved view: Saved motor review/);
  assert.equal(field('Window start').value, '2');
  const plots = api.requests.filter(r => r.url.endsWith('/explore')).length;
  await setField(container.querySelector('input[type=range]'), 4);
  await act(async () => new Promise(resolve => setTimeout(resolve, 110)));
  assert.match(container.querySelector('.cursor-readout').textContent, /42.125/);
  assert.match(container.querySelector('.cursor-readout').textContent, /Δ 0.25 s/);
  assert.match(container.querySelector('.cursor-readout').textContent, /Outside source coverage/);
  assert.equal(api.requests.filter(r => r.url.endsWith('/explore')).length, plots, 'cursor movement does not refetch display series');
  await click(button('Save browsing view'));
  const save = api.requests.findLast(r => r.url.includes('/views/') && r.body);
  assert.equal(save.body.windows.utc.at, 1006);
  assert.equal(save.body.displayMode, 'overlay');
  assert.match(container.textContent, /Saved: Saved motor review/);
  const requestCount = api.requests.length, nameInput = container.querySelector('input[value="Saved motor review"]');
  assert.match(container.querySelector('.ws-saved').textContent, /Saved: Saved motor review/);
  assert.equal(container.querySelector('input[value="Saved motor review"]'), nameInput);
  assert.equal(api.requests.length, requestCount, 'language does not reload explorer data');
  await click(button('Configure analysis for this window'));
  assert.deepEqual(analyses[0], ['temperature', ['temp'], [2, 8]]);
  const paths = container.querySelector('.explorer-lane svg').querySelectorAll('path');
  assert.equal(paths.length, 2);
  for (const path of paths) assert.equal((path.getAttribute('d').match(/M/g) || []).length, 2, 'missing boundaries break each source line');
  await act(async () => root.render(React.createElement(Plot, {
    title: 'Two independent temperature sources', times: [1000, 1010], values: [1, 2], segmentIds: [1, 1], axis: fixture.sources[0].metadata.time,
    gaps: [{ start: 1002, end: 1008 }], overlays: [{ title: 'Interrupted source', times: [1000, 1010], values: [3, 4], segmentIds: [1, 2], color: '#fff' }],
  })));
  const independent = container.querySelectorAll('svg path');
  assert.match(independent[0].getAttribute('d'), /L/, 'a peer sampling interruption must not break this continuously recorded source');
  assert.equal((independent[1].getAttribute('d').match(/M/g) || []).length, 2, 'the interrupted peer retains its own gap');
});

test('quality problems open the corresponding original signal window and show measured statistics', async () => {
  const fixture = foundationData(), opened = [];
  await mount(React.createElement(QualityExplorer, { dataset: fixture.sources[0], open: (...args) => opened.push(args) }));
  assert.match(container.textContent, /10 \/ 11/);
  assert.match(container.textContent, /9.091%/);
  await click(container.querySelector('.quality-issue'));
  assert.deepEqual(opened[0], [['signal-temperature'], 4, 4]);
  assert.equal(container.querySelector('svg [role=button]').getAttribute('aria-label'), 'Missing measurement: temp 4 to 4');
});

test('relative time relationship editor saves an explicit reference and signed offset', async () => {
  const fixture = foundationData(), api = foundationAPI(fixture);
  const relative = structuredClone(fixture.sources[0]);
  relative.metadata.time.origin = null; relative.metadata.clock.reference = { mode: 'independent', offsetSeconds: 0 };
  let updated = false;
  await mount(React.createElement(TimeReferenceEditor, { dataset: relative, datasets: fixture.sources, onSaved: () => { updated = true; } }));
  await setField(field('Time relationship'), 'reference');
  await setField(field('Reference dataset'), fixture.sources[1].id);
  await setField(field('Offset added'), -12.5);
  await click(button('Save time relationship'));
  assert.equal(updated, true);
  assert.deepEqual(api.requests.at(-1).body, { mode: 'reference', offsetSeconds: -12.5, referenceDatasetId: 'temperature-peer' });
});

test('late explorer and cursor responses cannot replace a newer source window', async () => {
  const fixture = foundationData();
  const api = foundationAPI(fixture, [{ id: 'v', name: 'Review', signalIds: [fixture.catalog[0].id], windows: {}, displayMode: 'separate' }], true);
  await mount(React.createElement(SignalWorkspace, { workspaceId: 'test', datasets: fixture.sources, jobs: [], mode: 'explorer', onChanged() {}, onAnalyze() {} }));
  await act(async () => api.pending[0].resolve(response(api.pending[0].result)));
  await setField(field('Window start'), 2);
  await setField(field('Window end'), 8);
  await click(button('Apply observation window'));
  const older = api.pending.at(-1);
  await click(container.querySelector('.explorer-signal-pool input[type=checkbox]'));
  const newer = api.pending.at(-1);
  await act(async () => newer.resolve(response(newer.result)));
  await act(async () => older.resolve(response(older.result)));
  assert.equal(container.querySelectorAll('.explorer-group').length, 0, 'unselected source cannot return from an old window request');
  const deferred = [];
  globalThis.fetch = (url, options) => new Promise(resolve => deferred.push({ body: JSON.parse(options.body), resolve }));
  const series = fixture.catalog.slice(0, 1).map(signal => ({ signal }));
  const axis = { id: 'utc', label: 'UTC', origin: '1970-01-01T00:00:00Z', start: 1000, end: 1010 };
  await act(async () => root.render(React.createElement(CursorReadout, { workspaceId: 'test', axis, series, at: 1001 })));
  await act(async () => new Promise(resolve => setTimeout(resolve, 110)));
  await act(async () => root.render(React.createElement(CursorReadout, { workspaceId: 'test', axis, series, at: 1007 })));
  await act(async () => new Promise(resolve => setTimeout(resolve, 110)));
  await act(async () => deferred[1].resolve(response({ samples: [{ signalId: fixture.catalog[0].id, value: 77, status: 'measured', time: 1007, nativeTime: 7, deltaSeconds: 0, sourceIndex: 7, duplicateCount: 1 }] })));
  await act(async () => deferred[0].resolve(response({ samples: [{ signalId: fixture.catalog[0].id, value: 11, status: 'measured', time: 1001, nativeTime: 1, deltaSeconds: 0, sourceIndex: 1, duplicateCount: 1 }] })));
  assert.match(container.textContent, /77/);
  assert.equal(container.querySelector('tbody td:nth-child(3)').textContent, '77');
});


const transformCatalog = [
  { id: 'pressure-id', name: 'p', displayName: 'Feed pressure', unit: 'kPa', datasetId: 'pressure-source', datasetName: 'Pressure recorder' },
  { id: 'temperature-id', name: 't', displayName: 'Temperature', unit: '°C', datasetId: 'temperature-source', datasetName: 'Temperature recorder' },
].map(signal => ({ ...signal, workspaceId: 'test', source: 'CSV', time: { kind: 'numeric', start: 0, end: 599, origin: null, typicalInterval: 1 },
  clock: { key: 'dataset:' + signal.datasetId, axisId: 'test-axis', offset: 0, label: 'Related recorders', reference: { mode: 'independent' } } }));
function transformPreview(config, marker = 'Computed pressure') {
  const names = [...config.sources, ...config.derived].map(s => s.key);
  const metadata = { ...dataset('transform-output').metadata, rowCount: 600, time: { kind: 'numeric', origin: null, start: 0, end: 599, sampleInterval: config.grid.intervalSeconds },
    columns: [...config.sources, ...config.derived].map(s => ({ name: s.key, displayName: s.displayName || marker, unit: s.unit, min: .3, max: .32, missing: 0 })),
    transformation: { config, definitionName: marker, grid: { start: 0, end: 599, samples: 600, intervalSeconds: config.grid.intervalSeconds }, sources: [], sourceSimulations: [],
      quality: names.map(key => ({ key, before: { validCount: 500, missingFraction: 1/6 }, after: { validCount: 600, missingFraction: 0, min: .3, max: .32 }, observedCount: 500, provenance: { measured: 500, interpolated: 100 } })) } };
  return { metadata, series: { times: [0, 1, 2], values: Object.fromEntries(names.map(name => [name, [.3, .31, .32]])), sourceRows: 600, displayRows: 3 },
    samples: [{ time: 1, values: Object.fromEntries(names.map(name => [name, .31])), provenance: Object.fromEntries(names.map(name => [name, 'interpolated'])), observed: Object.fromEntries(names.map(name => [name, false])) }] };
}
const transformUnits = [{ name: 'Pa', dimension: 'pressure' }, { name: 'kPa', dimension: 'pressure' }, { name: 'MPa', dimension: 'pressure' }, { name: '°C', dimension: 'temperature' }];
async function previewDebounce() { await act(async () => new Promise(resolve => setTimeout(resolve, 490))); }

test('transformation editor sends stable signal IDs, previews computed curves, saves and generates separate datasets', async () => {
  const writes = [], generated = [];
  let savedConfig;
  globalThis.fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    if (url.endsWith('/signals')) return response({ signals: transformCatalog });
    if (url.endsWith('/units')) return response({ units: transformUnits });
    if (url.endsWith('/transformations') && !body) return response({ transformations: [] });
    if (url.endsWith('/preview')) { writes.push({ url, body }); return response(transformPreview(body.config)); }
    if (url.endsWith('/transformations') && body) { writes.push({ url, body }); savedConfig = body.config; return response({ id: 'definition-1', workspace_id: 'test', revision: 1, name: body.name, config: body.config, updated_at: '2026-10-24T00:00:00Z' }); }
    if (url.endsWith('/execute')) { writes.push({ url, body }); const preview = transformPreview(savedConfig); return response({ id: 'generated-' + generated.length, workspace_id: 'test', name: body.name, metadata: preview.metadata }); }
    throw new Error('Unexpected request ' + url);
  };
  await mount(React.createElement(TransformationWorkspace, { workspaceId: 'test', datasets: [], initialSignalIds: 'pressure-id,temperature-id', onGenerated: d => generated.push(d) }));
  await setField(inputFor('Output unit 1'), 'MPa');
  await setField(inputFor('Resampling 1'), 'mean');
  await setField(inputFor('Duplicate timestamps 1'), 'last');
  await setField(inputFor('Missing values 1'), 'fixed');
  await setField(inputFor('Fill value 1'), .3);
  await click(button('+ Add derived signal'));
  await setField(inputFor('Expression 1'), 'rate(s_1)');
  await previewDebounce();
  const latest = writes.filter(w => w.url.endsWith('/preview')).at(-1).body.config;
  assert.equal(latest.sources[0].signalId, 'pressure-id');
  assert.equal(latest.sources[0].unit, 'MPa');
  assert.equal(latest.sources[0].resampling, 'mean');
  assert.equal(latest.sources[0].missing.value, .3);
  assert.equal(latest.derived[0].expression, 'rate(s_1)');
  assert.ok(container.querySelector('svg[aria-label="Feed pressure (MPa) time series"]'));
  assert.match(container.textContent, /Original observations/);
  assert.match(container.textContent, /500/);
  await click(button('Generate new dataset'));
  assert.equal(generated.length, 1);
  assert.ok(container.querySelector('a[href="#/workspaces/test/datasets/generated-0"]'));
  assert.ok(container.querySelector('a[href="#/workspaces/test/experiments/new/generated-0"]'), 'generated data opens an experiment directly');
  assert.equal(writes.filter(w => w.url.endsWith('/transformations')).length, 1);
  await click(button('Generate new dataset'));
  assert.equal(generated.length, 2);
  assert.notEqual(generated[0].id, generated[1].id);
  assert.equal(writes.filter(w => w.url.endsWith('/transformations')).length, 1, 'unchanged rerun reuses saved revision');
});

test('transformation preview discards stale success and stale errors; validation blocks generation', async () => {
  const pending = [];
  globalThis.fetch = (url, options = {}) => {
    if (url.endsWith('/signals')) return Promise.resolve(response({ signals: transformCatalog }));
    if (url.endsWith('/units')) return Promise.resolve(response({ units: transformUnits }));
    if (url.endsWith('/transformations')) return Promise.resolve(response({ transformations: [] }));
    if (url.endsWith('/preview')) return new Promise(resolve => pending.push({ config: JSON.parse(options.body).config, resolve }));
    throw new Error('Unexpected request ' + url);
  };
  await mount(React.createElement(TransformationWorkspace, { workspaceId: 'test', datasets: [], initialSignalIds: 'pressure-id', onGenerated: () => {} }));
  await previewDebounce();
  await setField(inputFor('Sampling interval (s)'), 2);
  await previewDebounce();
  await act(async () => pending[1].resolve(response(transformPreview(pending[1].config, 'Current'))));
  assert.match(container.textContent, /2 s interval/);
  await act(async () => pending[0].resolve(new Response(JSON.stringify({ error: 'Obsolete failure' }), { status: 400, headers: { 'Content-Type': 'application/json' } })));
  assert.ok(!container.textContent.includes('Obsolete failure'));
  await click(button('+ Add derived signal'));
  await setField(inputFor('Expression 1'), 'invalid.__class__');
  await previewDebounce();
  await act(async () => pending[2].resolve(new Response(JSON.stringify({ error: 'Only arithmetic and selected keys are allowed.' }), { status: 400, headers: { 'Content-Type': 'application/json' } })));
  assert.match(container.querySelector('[role="alert"]').textContent, /Only arithmetic/);
  assert.ok(button('Generate new dataset').disabled);
});

test('saved transformation reopens its source keys and execution lineage links to source and simulation', async () => {
  const config = { version: 1, grid: { mode: 'intersection', intervalSeconds: 2 }, sources: [{ signalId: 'pressure-id', key: 'stable_pressure', displayName: 'Pressure', sourceUnit: 'kPa', unit: 'MPa', resampling: 'previous', duplicatePolicy: 'mean', maxGapSeconds: 4, missing: { method: 'keep' } }], derived: [] };
  const definition = { id: 'saved-definition', name: 'Stored pipeline', revision: 3, config, updated_at: '2026-10-24T00:00:00Z' };
  globalThis.fetch = async (url, options = {}) => {
    if (url.endsWith('/signals')) return response({ signals: transformCatalog });
    if (url.endsWith('/units')) return response({ units: transformUnits });
    if (url.endsWith('/transformations')) return response({ transformations: [definition] });
    if (url.endsWith('/preview')) return response(transformPreview(JSON.parse(options.body).config));
    throw new Error('Unexpected request ' + url);
  };
  await mount(React.createElement(TransformationWorkspace, { workspaceId: 'test', datasets: [], definitionId: definition.id, onGenerated: () => {} }));
  assert.equal(inputFor('Signal key 1').value, 'stable_pressure');
  assert.equal(inputFor('Sampling interval (s)').value, '2');
  assert.equal(inputFor('Output unit 1').value, 'MPa');
  assert.match(container.textContent, /Revision 3/);
  const generated = { id: 'derived-data', workspace_id: 'test', metadata: transformPreview(config).metadata };
  Object.assign(generated.metadata.transformation, { definitionId: definition.id, revision: 3, executionId: 'frozen-execution', createdAt: '2026-10-24T00:00:00Z', sources: [{ datasetId: 'pressure-source', datasetName: 'Pressure recorder' }], sourceSimulations: ['model-source'] });
  await act(async () => root.render(React.createElement(TransformationLineage, { dataset: generated })));
  assert.ok(container.querySelector('a[href="#/workspaces/test/datasets/pressure-source"]'));
  assert.ok(container.querySelector('a[href="#/workspaces/test/explorer/pressure-id"]'));
  assert.ok(container.querySelector('a[href="#/workspaces/test/simulations/model-source"]'));
  assert.match(container.textContent, /frozen-execution/);
});

function researchFixture(id = 'experiment-one') {
  const source = dataset('research-data');
  source.metadata.clock = { axisId: 'research-clock', offset: 0 };
  const experiment = { id, workspace_id: 'test', name: 'Cooling campaign', description: 'Compare saved methods', revision: 1,
    config: newExperimentConfig(source), notes: '', conclusion: '', conclusion_run_ids: [], created_at: '2026-10-24T00:00:00Z', updated_at: '2026-10-24T00:00:00Z', runs: [] };
  const run = { id: 'run-original', experiment_id: id, status: 'partial', created_at: experiment.created_at, task_count: 2, completed: 2, succeeded: 1, failed: 1, duration_ms: 4 };
  experiment.runs = [run];
  const task = { id: 'task-succeeded', run_id: run.id, algorithm: 'robust-maxz', config: { ...experiment.config, algorithm: 'robust-maxz', variance: .9 }, status: 'succeeded',
    result_id: 'saved-analysis', duration_ms: 3, datasetId: source.id, datasetName: source.name, experimentRevision: 1,
    metrics: { behavior: { totalSamples: 3, validSamples: 3, abstainedSamples: 0, coverageFraction: 1, alarmSamples: 2, alarmFraction: 2/3, alarmIntervalCount: 1, alarmDuration: 1, firstDetection: 201, durationMs: 2, relatedSignals: names.slice(0,2) }, labelled: null } };
  const failed = { ...task, id: 'task-failed', algorithm: 'ewma', status: 'failed', result_id: null, metrics: null, error: 'Temporal samples require regular times' };
  const result = { id: task.result_id, workspaceId: 'test', datasetId: source.id, name: 'Saved Max-Z', algorithmLabel: 'Robust Max-Z', config: { ...task.config, analysisRange: [200,202] },
    times: [200,201,202], scores: [1,4,5], states: ['normal','alarm','alarm'], threshold: 3, intervals: [{ start: 201, end: 202, peakTime: 202 }], relatedSignals: names.slice(0,2), signalContributions: [{ signal: names[0], value: 5 }], contributionMetric: 'absolute-robust-z' };
  const analysis = { id: task.id, task, result, dataset: source, axisId: 'research-clock', offset: 0, intervals: result.intervals };
  return { source, experiment, run, task, failed, result, analysis, data: { experiment, tasks: [task, failed], analyses: [], groups: [], rules: {} } };
}

test('experiment editor previews a real multi-algorithm parameter plan and enforces the visible task budget', async () => {
  const source = dataset('new-research'), writes = [];
  globalThis.fetch = async (url, options = {}) => {
    if (url.endsWith('/experiments') && !options.body) return response({ experiments: [] });
    if (url.endsWith('/incidents')) return response({ incidents: [] });
    if (url.endsWith('/labels')) return response({ labels: [] });
    if (url.endsWith('/preview')) { const body = JSON.parse(options.body); writes.push(body); return response({ taskCount: 10, tasks: [] }); }
    throw new Error('Unexpected request ' + url);
  };
  await mount(React.createElement(ExperimentWorkspace, { workspaceId: 'test', datasets: [source], onChanged() {} }));
  await click(button('Select all nine algorithms'));
  await setField(container.querySelector('[aria-label="PCA-Q variance candidates"]'), '.7, .95');
  assert.match(container.textContent, /9 methods · 10 tasks/);
  await click(button('Preview 10 tasks'));
  assert.equal(writes[0].config.algorithms.length, 9);
  assert.deepEqual(writes[0].config.algorithms.find(p => p.algorithm === 'pca-q').study.variance, [.7,.95]);
  assert.match(container.textContent, /Validated task preview · 10/);
  await setField(container.querySelector('[aria-label="Dynamic PCA-Q lags candidates"]'), '1,2,3,4,5,6,7,8');
  await setField(container.querySelector('[aria-label="Dynamic PCA-Q variance candidates"]'), '.5,.6,.7,.8,.9,.95,.97,.99');
  assert.equal(button('Save & run').disabled, true, 'oversized candidate product cannot be submitted');
});

test('experiment history keeps successful results usable when another task fails, saves notes, filters and links real IDs', async () => {
  const fixture = researchFixture(), writes = [];
  globalThis.fetch = async (url, options = {}) => {
    const body = options.body && JSON.parse(options.body);
    if (url === '/api/workspaces/test/experiments' && !body) return response({ experiments: [fixture.experiment] });
    if (url === '/api/workspaces/test/incidents') return response({ incidents: [] });
    if (url.endsWith('/labels')) return response({ labels: [] });
    if (url === '/api/experiments/experiment-one' && !body) return response(fixture.experiment);
    if (url.endsWith('/comparison')) return response({ ...fixture.data, experiment: fixture.experiment, analyses: body.taskIds.includes(fixture.task.id) ? [fixture.analysis] : [] });
    if (url === '/api/experiments/experiment-one' && body) { writes.push({ url, body }); Object.assign(fixture.experiment, body, { revision: fixture.experiment.revision+1 }); return response(fixture.experiment); }
    if (url === '/api/experiment-runs/run-original/incidents') { writes.push({ url, body }); return response({ id: 'linked-incident', title: 'Research incident' }); }
    throw new Error('Unexpected request ' + url);
  };
  await mount(React.createElement(ExperimentWorkspace, { workspaceId: 'test', experimentId: fixture.experiment.id, datasets: [fixture.source], onChanged() {} }));
  assert.match(container.textContent, /1 succeeded · 1 failed/);
  assert.match(container.textContent, /Temporal samples require regular times/);
  assert.ok(container.querySelector('a[href="#/workspaces/test/analysis/saved-analysis"]'));
  await setField(inputFor('Experiment notes'), 'Reviewed original measurements');
  await setField(inputFor('Experiment conclusion'), 'Retain the fixed detector for comparison');
  const reference = [...container.querySelectorAll('fieldset')].find(n => n.textContent.startsWith('Runs supporting'));
  await click(reference.querySelector('input'));
  await click(button('Save experiment'));
  assert.equal(writes[0].body.notes, 'Reviewed original measurements');
  assert.deepEqual(writes[0].body.conclusion_run_ids, ['run-original']);
  await setField(inputFor('Filter task / detection status'), 'failed');
  assert.equal(container.querySelectorAll('.experiment-results tbody tr').length, 1);
  await setField(inputFor('Filter task / detection status'), '');
  await click(container.querySelector('[aria-label="Compare task task-suc"]'));
  await click(button('Create incident from selected results'));
  assert.deepEqual(writes.at(-1).body.taskIds, ['task-succeeded']);
  assert.ok(container.querySelector('a[href="#/workspaces/test/incidents/linked-incident"]'));
});

test('late experiment loads cannot replace the newly opened experiment', async () => {
  const first = researchFixture('first-experiment'), second = researchFixture('second-experiment'), pending = [];
  second.experiment.name = 'Second research';
  globalThis.fetch = async (url, options = {}) => {
    if (url === '/api/workspaces/test/experiments') return response({ experiments: [] });
    if (url.endsWith('/incidents')) return response({ incidents: [] });
    if (url.endsWith('/labels')) return response({ labels: [] });
    if (url.endsWith('/comparison')) return response(second.data);
    return new Promise(resolve => pending.push({ url, resolve }));
  };
  await mount(React.createElement(ExperimentWorkspace, { workspaceId: 'test', experimentId: first.experiment.id, datasets: [first.source], onChanged() {} }));
  await act(async () => root.render(React.createElement(ExperimentWorkspace, { workspaceId: 'test', experimentId: second.experiment.id, datasets: [second.source], onChanged() {} })));
  await act(async () => pending[1].resolve(response(second.experiment)));
  await act(async () => pending[0].resolve(response(first.experiment)));
  assert.equal(inputFor('Experiment name').value, 'Second research');
});

test('label editor imports explicit native-clock annotations and saves an independent version', async () => {
  const writes = [], selected = [];
  globalThis.fetch = async (url, options = {}) => {
    if (!options.body) return response({ labels: [] });
    writes.push(JSON.parse(options.body)); return response({ id: 'label-v2', version: 2 });
  };
  await mount(React.createElement(ExperimentLabels, { dataset: dataset('label-source'), onChange: id => selected.push(id) }));
  await setField(inputFor('Label JSON'), JSON.stringify({ timeBasis: 'dataset-seconds', timeSource: 'Reviewed event log', intervals: [{ kind: 'anomaly', start: 400, end: 459 }] }));
  await click(button('Load JSON into editor'));
  await click(button('Save new label version'));
  assert.equal(writes[0].timeBasis, 'dataset-seconds');
  assert.equal(writes[0].timeSource, 'Reviewed event log');
  assert.deepEqual(writes[0].intervals, [{ kind: 'anomaly', start: 400, end: 459 }]);
  assert.deepEqual(selected, ['label-v2']);
});

test('a pending experiment save cannot replace another experiment opened during the request', async () => {
  const first = researchFixture('pending-save'), second = researchFixture('new-selection');
  second.experiment.name = 'New selected experiment';
  let resolveSave, changed = 0;
  globalThis.fetch = (url, options = {}) => {
    if (url === '/api/workspaces/test/experiments') return Promise.resolve(response({ experiments: [first.experiment, second.experiment] }));
    if (url.endsWith('/incidents')) return Promise.resolve(response({ incidents: [] }));
    if (url.endsWith('/labels')) return Promise.resolve(response({ labels: [] }));
    if (url.endsWith('/comparison')) return Promise.resolve(response(url.includes(first.experiment.id) ? first.data : second.data));
    if (url.endsWith('/' + first.experiment.id) && options.body) return new Promise(resolve => { resolveSave = resolve; });
    return Promise.resolve(response(url.endsWith('/' + first.experiment.id) ? first.experiment : second.experiment));
  };
  await mount(React.createElement(ExperimentWorkspace, { workspaceId: 'test', experimentId: first.experiment.id, datasets: [first.source], onChanged() { changed++; } }));
  await setField(inputFor('Experiment name'), 'Pending old edit');
  await click(button('Save experiment'));
  assert.equal(container.querySelector('form').hasAttribute('inert'), true);
  await act(async () => root.render(React.createElement(ExperimentWorkspace, { workspaceId: 'test', experimentId: second.experiment.id, datasets: [second.source], onChanged() { changed++; } })));
  await act(async () => resolveSave(response({ ...first.experiment, revision: 2, name: 'Pending old edit' })));
  assert.equal(inputFor('Experiment name').value, 'New selected experiment');
  assert.equal(changed, 0, 'a stale save does not refresh the new experiment context');
});

test('experiment comparison warns on mismatched coverage and synchronizes independent score plots with original data', async () => {
  const fixture = researchFixture(), other = { ...fixture.analysis, id: 'second-task', result: { ...fixture.result, algorithmLabel: 'EWMA' } };
  globalThis.fetch = async url => response(seriesFor(url));
  const data = { ...fixture.data, analyses: [fixture.analysis, other], groups: [{ axisId: 'research-clock', taskIds: [fixture.task.id, other.id], matchingWindows: false, matchingCoverage: false, segments: [], agreement: [] }] };
  await mount(React.createElement(ExperimentComparison, { data }));
  assert.match(container.textContent, /different analysis windows/);
  assert.match(container.textContent, /different observation coverage/);
  await setField(inputFor('Shared observation time'), 201);
  assert.ok(container.querySelectorAll('line[data-selected-time="201"]').length >= 2, 'both score plots and source measurements share the cursor');
});

test('experiment report discards late generation and requires saved notes before export', async () => {
  const fixture = researchFixture(), pending = [];
  globalThis.fetch = () => new Promise(resolve => pending.push(resolve));
  await mount(React.createElement(ExperimentReport, { experiment: fixture.experiment, dirty: true }));
  assert.equal(button('Preview experiment report').disabled, true);
  await act(async () => root.render(React.createElement(ExperimentReport, { experiment: fixture.experiment, dirty: false })));
  await click(button('Preview experiment report'));
  await act(async () => root.render(React.createElement(ExperimentReport, { experiment: { ...fixture.experiment, revision: 2 }, dirty: false })));
  await click(button('Preview experiment report'));
  await act(async () => pending[1](new Response('<h1>Current saved conclusion</h1>', { headers: { 'content-type': 'text/html' } })));
  await act(async () => pending[0](new Response('<h1>Stale conclusion</h1>', { headers: { 'content-type': 'text/html' } })));
  assert.match(container.querySelector('iframe').getAttribute('srcdoc'), /Current saved conclusion/);
  assert.doesNotMatch(container.querySelector('iframe').getAttribute('srcdoc'), /Stale/);
  assert.ok(container.querySelector('a[download]'));
});

function modelFixture(id = 'independent-process') {
  const model = { modelId:id,name:'Independent tank model',version:'1.0.0',category:'Hydraulic',description:'A distinct registered model',source:{name:'Local physical model'},limitations:['Known-model forecasts only'],
    defaults:{fault:'healthy',duration:120,step:.2,start:40,seed:7,area:1},configFields:[{key:'area',label:'Tank area',unit:'m²',group:'Initial conditions',type:'number',min:.1,max:10,nullable:false}],
    signals:[{key:'level',tag:'LT-1',unit:'m',label:'Measured level'}],faults:{healthy:'Healthy',leak:'Leak'},capabilities:['simulation','observation','investigation-tools','interventions','forecast'],
    tools:['flow_balance'],toolDefinitions:[{id:'flow_balance',name:'Observed balance'}],actions:[{id:'adjust_pump',name:'Adjust pump',parameters:['pumpControl']}],actionParameters:{pumpControl:{label:'Pump command',unit:'%',min:0,max:150,default:100}},edges:[] };
  const scenario={id:'scenario-1',workspaceId:'test',modelId:id,modelVersion:'1.0.0',version:1,name:'Saved leak scenario',description:'Old description',config:{...model.defaults,fault:'leak'},createdAt:'2026-10-25T00:00:00Z',updatedAt:'2026-10-25T00:00:00Z'};
  const session={id:'model-session',title:'Tank run',modelId:id,modelVersion:'1.0.0',modelDescriptor:model,scenarioId:scenario.id,scenarioVersion:1,scenarioSnapshot:scenario,config:scenario.config,
    rows:Array.from({length:601},(_,i)=>({t:i*.2,level:1+i*.001})),workspaceId:'test',datasetId:null,status:'completed',createdAt:'2026-10-25T00:00:00Z',groundTruth:{}};
  return {model,scenario,session};
}

test('model catalog uses registered metadata and generates model-specific scenario fields',async()=>{
  const {model}=modelFixture('a-new-model-id');
  globalThis.fetch=async url=>response(url==='/api/models' ? {models:[model]} : url.includes('/scenarios') ? {scenarios:[]} : {simulations:[]});
  await mount(React.createElement(ModelWorkspace,{workspaceId:'test',onSaved(){}}));
  assert.ok(container.textContent.includes('Independent tank model'));
  assert.equal(inputFor('Tank area').value,'1');
  assert.equal(container.querySelectorAll('.model-card').length,1);
  assert.ok(!container.textContent.includes('18 CHANNELS'));
  assert.ok(!container.textContent.includes('cooling_valve'));
});

test('scenario edits save a new version before a run and retain the original input object',async()=>{
  const {model,scenario,session}=modelFixture(),writes=[],original=JSON.stringify(scenario),saved=[];
  globalThis.fetch=async(url,options={})=>{
    if(!options.body) return response({versions:[scenario]});
    const body=JSON.parse(options.body);writes.push({url,body,method:options.method});
    return response(url.endsWith('/run') ? session : {...scenario,version:2,name:body.name,config:body.config});
  };
  await mount(React.createElement(ScenarioEditor,{workspaceId:'test',model,scenario,onSaved:s=>saved.push(s),onSelect(){},onRun(){}}));
  await setField(inputFor('Tank area'),2.4);
  await click(button('Save & run scenario'));
  assert.equal(writes[0].method,'PATCH');assert.equal(writes[0].body.expectedVersion,1);
  assert.equal(writes[0].body.config.area,2.4);
  assert.deepEqual(writes[1].body,{scenarioVersion:2,workspaceId:'test'});
  assert.equal(saved[0].version,2);assert.equal(JSON.stringify(scenario),original);
  const name = inputFor('Scenario name'), requestCount = writes.length;
  assert.match(container.querySelector('[role="status"]').textContent, /Saved scenario v2/);
  assert.match(container.querySelector('[role="status"]').textContent, /Saved scenario v2/);
  assert.equal(inputFor('Scenario name'), name);
  assert.equal(writes.length, requestCount, 'relocalizing a saved notice does not run the model again');
  assert.equal(JSON.stringify(scenario), original);
});

test('generic intervention records restore their own action parameters and observation window',async()=>{
  const {session}=modelFixture(),writes=[];
  const result={format:'model-forecast-v1',mode:'known',modelId:session.modelId,at:63.17,horizon:120,observedThrough:60,
    baseline:{action:null,times:[0,60,120],values:{level:[1,1,.8]},metrics:{delivered:2}},branches:[{action:'adjust_pump',times:[0,60,120],values:{level:[1,1,1.1]},metrics:{delivered:3}}],
    metricDefinitions:[{key:'delivered',label:'Delivered water',unit:'m³'}],signalDefinitions:session.modelDescriptor.signals,uncertainty:'Conditional known model'};
  const run={id:'tank-trial',kind:'intervention',modelId:session.modelId,createdAt:'2026-10-25T00:00:00Z',request:{windowStart:10,asOf:60,mode:'known',at:63.17,horizon:120,actions:['adjust_pump'],parameters:{pumpControl:117}},result};
  globalThis.fetch=async(url,options={})=>{
    if(url.endsWith('/runs')) return response({runs:[run]});
    const body=JSON.parse(options.body || '{}');
    if(url.endsWith('/analysis')) return response({observedThrough:body.asOf,windowStart:body.windowStart,samples:201});
    writes.push({url,body});return response({...run,id:"new-tank-trial"});
  };
  await mount(React.createElement(ModelSimulation,{workspaceId:'test',session,sessions:[session],runId:run.id,onSaved(){},onDataset(){}}));
  assert.equal(inputFor('Action time').value,'63.17');assert.equal(inputFor('Window start').value,'10');assert.equal(inputFor('Pump command').value,'117');
  assert.ok(container.textContent.includes('Delivered water (m³)'));
  assert.ok(!container.textContent.includes('physical pressure'));
  await click(button('Simulate actions & save comparison'));
  assert.equal(writes[0].body.parameters.pumpControl,117);assert.equal(writes[0].body.asOf,60);
  await setField(inputFor('Observe through'),70);
  assert.ok(container.textContent.includes('different observation window'));
});

test('Incident saved result renders model-declared forecast metrics without TripLens fields',async()=>{
  const forecast={format:'model-forecast-v1',mode:'known',at:60,horizon:120,observedThrough:60,baseline:{action:null,times:[0,120],values:{height:[1,.7]},metrics:{water:2}},branches:[],metricDefinitions:[{key:'water',label:'Delivered water',unit:'m³'}],signalDefinitions:[{key:'height',label:'Physical level',unit:'m'}],uncertainty:'Known tank model'};
  await mount(React.createElement(SavedRunView,{run:{id:'saved-tank',kind:'intervention',result:forecast,request:{}}}));
  assert.ok(container.textContent.includes('Delivered water (m³)'));assert.ok(curve('Physical level (m)'));
  assert.ok(!container.textContent.includes('pressure'));
});

test('leaving a scenario during a pending save does not navigate back to its old model',async()=>{
  const first=modelFixture('first-model'),second=modelFixture('second-model');
  let complete,callbacks=0;
  globalThis.fetch=(url,options={})=>options.body ? new Promise(resolve=>{complete=resolve;}) : Promise.resolve(response({versions:[first.scenario]}));
  const props={workspaceId:'test',model:first.model,scenario:first.scenario,onSaved(){callbacks++;},onSelect(){},onRun(){callbacks++;}};
  await mount(React.createElement(ScenarioEditor,{...props,key:'first'}));
  await setField(inputFor('Tank area'),2);
  await click(button('Save & run scenario'));
  await act(async()=>root.render(React.createElement(ScenarioEditor,{...props,key:'second',model:{...second.model,name:'Second selected process'},scenario:null})));
  await act(async()=>complete(response({...first.scenario,version:2})));
  assert.equal(callbacks,0);assert.equal(inputFor('Scenario name').value,'Second selected process scenario');
});

test('late model session response cannot replace a newer selected session',async()=>{
  const {model,session}=modelFixture();let complete;
  const second={...session,id:'newer-session',title:'Newer selected process'};
  globalThis.fetch=(url,options={})=>{
    if(url==='/api/models') return Promise.resolve(response({models:[model]}));
    if(url.includes('/scenarios')) return Promise.resolve(response({scenarios:[]}));
    if(url.includes('/model-research')) return Promise.resolve(response({rows:[]}));
    if(url.includes('/simulations?')) return Promise.resolve(response({simulations:[session,second]}));
    if(url.endsWith('/'+session.id)) return new Promise(resolve=>{complete=resolve;});
    if(url.endsWith('/'+second.id)) return Promise.resolve(response(second));
    if(url.endsWith('/runs')) return Promise.resolve(response({runs:[]}));
    return Promise.resolve(response({observedThrough:93,windowStart:0,samples:466}));
  };
  await mount(React.createElement(ModelWorkspace,{workspaceId:'test',simulationId:session.id,onSaved(){}}));
  await act(async()=>root.render(React.createElement(ModelWorkspace,{workspaceId:'test',simulationId:second.id,onSaved(){}})));
  await act(async()=>complete(response(session)));
  assert.ok(container.querySelector('.model-provenance').textContent.includes(second.title));
  assert.ok(!container.querySelector('.model-provenance').textContent.includes('Tank run'));
});

test('model research retains separate model identities, label versions and evaluation denominators',async()=>{
  const rows=['TripLens','Coupled tanks'].map((name,i)=>({experimentId:'e'+i,experimentName:name+' study',runId:'run'+i,taskId:'task'+i,datasetId:'d'+i,datasetName:name+' signals',models:[{id:name,name,version:'1.0',scenarioId:'scenario'+i,scenarioVersion:i+1}],algorithm:'robust-maxz',status:'succeeded',resultId:'result'+i,labelVersion:i+1,
    metrics:{behavior:{alarmSamples:20,validSamples:100+i,coverageFraction:1},labelled:{sample:{precision:.8,recall:.9,f1:.847}}}}));
  globalThis.fetch=async()=>response({rows,scope:'Persisted research only'});
  await mount(React.createElement(ModelResearch,{workspaceId:'test'}));
  assert.ok(container.textContent.includes('TripLens v1.0'));assert.ok(container.textContent.includes('Coupled tanks v1.0'));
  assert.ok(container.textContent.includes('20 / 100'));assert.ok(container.textContent.includes('20 / 101'));
  assert.equal(container.querySelectorAll('tbody tr').length,2);
});

test('external import requires a verified preview, retains independent run selections and opens the fixed experiment', async () => {
  const writes = [], changes = [];
  const run = { id:'faulty-testing-f01-r001', faultNumber:1, simulationRun:1, split:'testing', samples:960, features:52, sampleIntervalSeconds:180, faultOnsetSample:161, faultOnsetSeconds:28800 };
  const source = { id:'faulty-testing', source:{sourceFile:'TEP_Faulty_Testing.RData'}, runs:[run] };
  globalThis.fetch = async (url, options={}) => {
    if (url.endsWith('/sources')) return response({sources:[source]});
    if (url.endsWith('/studies')) return response({studies:[]});
    if (url.endsWith('/experiments')) return response({experiments:[]});
    const body=JSON.parse(options.body); writes.push({url,body});
    if (url.endsWith('/preview')) return response({runs:[run],timeConvention:'sample 161 = 28800 seconds'});
    if (url.endsWith('/external/tep')) return response({datasets:[dataset('external-fixture')]});
    throw new Error('Unexpected request '+url);
  };
  await mount(React.createElement(TEPWorkspace,{workspaceId:'test',onChanged:()=>changes.push(true)}));
  assert.equal(button('Import independent runs').disabled,true);
  await click(inputFor('Fault 1 · run 1'));
  await click(button('Inspect selected runs'));
  assert.match(container.textContent,/960 \/ 52/);
  assert.match(container.textContent,/sample 161 · 28800 s/);
  await click(button('Import independent runs'));
  assert.deepEqual(writes[1].body,{sourceId:'faulty-testing',runIds:[run.id]});
  assert.equal(changes.length,1);
  assert.match(container.textContent,/1 independent runs saved/);
  await click(inputFor('Fault 1 · run 1'));
  assert.equal(button('Import independent runs').disabled,true,'changing the selection invalidates its preview');
});

test('independent experiment editor keeps normal training and per-test windows and label versions separate', async () => {
  const sources=['fit','calibration','test-one','test-two'].map(id=>dataset(id));
  const writes=[];
  globalThis.fetch=async()=>response({labels:[{id:'published-v1',version:1,name:'Published protocol',source:'tep-rieth'}]});
  function Fixture(){ const [config,setConfig]=useState(newExperimentConfig(sources[2])); return React.createElement(IndependentTraining,{datasets:sources,config,onChange:change=>{setConfig(v=>({...v,...change}));writes.push(change);}}); }
  await mount(React.createElement(Fixture));
  await click(inputFor('Fit and calibrate on separate normal datasets'));
  assert.equal(writes[0].training.fit.datasetId,'fit');
  assert.equal(writes[0].training.calibration.datasetId,'calibration');
  assert.deepEqual(writes[0].testDatasets,[{datasetId:'test-one',analysisRange:[0,899]}]);
  await click(inputFor('test-two'));
  assert.equal(writes.at(-1).testDatasets.length,2);
  const details=[...container.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent.startsWith('test-two'));
  details.open=true;
  await setField(inputFor('Test truth label version',details),'published-v1');
  assert.equal(writes.at(-1).testDatasets[1].labelSetId,'published-v1');
  assert.equal(writes.at(-1).testDatasets[0].labelSetId,undefined);
});

test('external matrix retains missing events, run denominators and separate fixed parameter conditions', async () => {
  const fixture=researchFixture(), selected=[];
  const condition=JSON.stringify({algorithm:'robust-maxz',alpha:.01});
  const cell={runId:fixture.run.id,faultNumber:3,algorithm:'robust-maxz',condition,runCount:2,succeeded:2,failed:0,labelledRuns:2,
    sample:{TP:0,FP:0,TN:320,FN:1600,precision:null,recall:0,f1:0,falseAlarmRate:0},
    event:{detectedEvents:0,eligibleEvents:2,missedEvents:2,unobservedEvents:0,falseAlarmEvents:0},coverage:1,abstainFraction:0,
    delay:{n:0,median:null,minimum:null,maximum:null},recall:{n:2,median:0,minimum:0,maximum:0},falseAlarmRate:{n:2,median:0,minimum:0,maximum:0},
    alarmDuration:{n:2,median:0,minimum:0,maximum:0},durationMs:{n:2,median:2,minimum:1,maximum:3},taskIds:[fixture.task.id]};
  const data={...fixture.data,benchmark:{cells:[cell,{...cell,condition:JSON.stringify({algorithm:'robust-maxz',alpha:.02})}],rules:'Each batch and fixed parameter condition is separate.'},
    tasks:[{...fixture.task,datasetId:fixture.source.id,external:{faultNumber:3,simulationRun:1,faultOnsetSeconds:28800}}]};
  await mount(React.createElement(TEPBenchmark,{data,onSelect:ids=>selected.push(ids)}));
  assert.match(container.textContent,/0\/2 events/);
  assert.match(container.textContent,/2\/2 runs/);
  assert.equal(container.querySelectorAll('thead th').length,3,'parameter candidates keep separate columns');
  await setField(inputFor('Matrix metric'),'delay');
  assert.match(container.textContent,/— s/,'missed event delay is undefined, not zero');
  await setField(inputFor('Fault / simulationRun'),fixture.source.id);
  await click(button('Compare algorithms for this trajectory'));
  assert.deepEqual(selected,[[fixture.task.id]]);
});

test('TEP study dashboard isolates protocols/configurations and exposes failed runs without losing event denominators', async () => {
  const fixture=researchFixture(),condition=JSON.stringify({algorithm:'robust-maxz'});
  const burden={samples:3,observedSamples:3,alarmSamples:0,alarmEvents:0,alarmDuration:0,alarmFraction:0};
  const window={detectedEvents:0,totalEvents:3,rate:0,unobservedEvents:1,truncatedEvents:0,unresolvedEvents:1};
  const base={runId:'A',faultNumber:3,algorithm:'robust-maxz',condition,runCount:3,succeeded:2,failed:1,labelledRuns:2,configuration:'A',
    sample:{TP:0,FP:0,TN:1,FN:3,recall:0},event:{eligibleEvents:1,detectedEvents:0,missedEvents:1,unobservedEvents:1},
    delay:{n:0,median:null,minimum:null,maximum:null},recall:{n:2,median:0,minimum:0,maximum:0},falseAlarmRate:{n:2,median:0,minimum:0,maximum:0},alarmDuration:{n:2,median:0,minimum:0,maximum:0},durationMs:{n:2,median:1,minimum:1,maximum:1},
    windows:Object.fromEntries(['1800','3600','14400','eventual'].map(k=>[k,window])),burden:{normal:burden,preInjection:burden,postInjection:burden},taskIds:['failed-task']};
  const saved={id:'study-one',workspaceId:'test',protocolHash:'fixed-hash',protocol:{id:'rieth-expanded-nine-v1',name:'Declared study',configurations:{A:{},B:{}}},
    statusCounts:{succeeded:2,failed:1},batches:[],cells:[base,{...base,configuration:'B',runId:'B',windows:Object.fromEntries(['1800','3600','14400','eventual'].map(k=>[k,{...window,detectedEvents:2}]))}],
    tasks:[{id:'failed-task',algorithm:'robust-maxz',status:'failed',error:'preserved numeric failure',datasetId:'actual-data',experimentId:'actual-experiment',external:{faultNumber:3,simulationRun:3},benchmark:{configuration:'A'},metrics:null}]};
  globalThis.fetch=async(url)=>{
    if(url.endsWith('/studies'))return response({studies:[{id:saved.id,protocolId:saved.protocol.id}]});
    if(url.endsWith('/experiments'))return response({experiments:[{...fixture.experiment,description:'rieth-mode1-independent-nine-v1'}]});
    if(url.endsWith('/study-one'))return response(saved);
    throw new Error('Unexpected dashboard request '+url);
  };
  await mount(React.createElement(TEPStudyDashboard,{workspaceId:'test',onChanged(){}}));
  assert.match(container.textContent,/0\/3 events/);
  await click(button('0/3 events'));
  assert.match(container.querySelector('[aria-label="Selected matrix cell"]').textContent,/preserved numeric failure/);
  assert.equal(container.querySelector('[aria-label="Selected matrix cell"] a').getAttribute('href'),'#/workspaces/test/datasets/actual-data');
  await setField(inputFor('Normal training configuration'),'B');
  assert.match(container.textContent,/2\/3 events/);
  assert.equal(container.querySelector('[aria-label="Selected matrix cell"]'),null,'changing configuration clears prior cell evidence');
  await setField(inputFor('Experiment protocol'),'original');
  assert.equal(container.querySelector('.tep-fault-matrix'),null,'original protocol never inherits expanded results');
  assert.match(container.textContent,/72 tasks/);
  const search = new URLSearchParams({ protocol: saved.protocol.id, study: saved.id, training: 'B', metric: 'eventual', fault: '3', algorithm: 'robust-maxz' }).toString();
  await act(async () => root.render(React.createElement(TEPStudyDashboard,{key:'reopened',workspaceId:'test',search,onChanged(){}})));
  assert.equal(inputFor('Experiment protocol').value, saved.protocol.id);
  assert.equal(inputFor('Normal training configuration').value, 'B');
  assert.equal(inputFor('Matrix metric').value, 'eventual');
  assert.match(container.querySelector('[aria-label="Selected matrix cell"]').textContent,/configuration B/);
});

test('analysis links restore signals and windows, and entering History refreshes results completed while away', async () => {
  const first = dataset('first-source'), selected = dataset('second-source');
  const historyRows=[];
  selected.metadata.columns[1].name = 'pressure, backup + unit';
  const signals = [selected.metadata.columns[1].name];
  const route = analysisPath('test', selected.id, signals, [300, 470]);
  window.location.hash = `#/${route}`;
  globalThis.fetch = async url => {
    if (url === '/api/workspaces') return response({workspaces:[{id:'test',name:'Restored project'}]});
    if (url === '/api/workspaces/test') return response({id:'test',name:'Restored project'});
    if (url.endsWith('/datasets')) return response({datasets:[first, selected]});
    if (url.endsWith('/analyses')) return response({jobs:historyRows});
    if (url.includes('/series?')) return response(seriesFor(url));
    throw new Error('Unexpected restoration request '+url);
  };
  await mount(React.createElement(App));
  assert.equal(inputFor('Dataset').value, selected.id);
  assert.equal(inputFor('Analysis start (s)').value, '300');
  assert.equal(inputFor('Analysis end (s)').value, '470');
  assert.deepEqual([...container.querySelectorAll('.ws-signal-picker input[type="checkbox"]')].filter(n=>n.checked).map(n=>n.closest('label').textContent.trim()), signals);
  assert.equal(container.querySelector('nav[aria-label="Workspace"] a').getAttribute('href'),'#/workspaces/test/datasets/second-source');
  const scrolls=[];
  dom.window.scrollTo=(...args)=>scrolls.push(args);
  try {
    await act(async()=>{
      window.location.hash=`#/${analysisPath('test',selected.id,signals,[320,450])}`;
      window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'));
    });
    assert.equal(inputFor('Analysis start (s)').value,'320');
    assert.equal(scrolls.length,0,'changing query context keeps the current scroll position');
    await act(async()=>{
      window.location.hash='#/workspaces/test/datasets/second-source';
      window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'));
    });
    assert.equal(container.querySelector('select[aria-label="Saved dataset"]').value,selected.id);
    assert.equal(scrolls.length,1,'changing workstation scrolls to the new page');
    historyRows.push({id:'background-saved',dataset_id:selected.id,name:'Completed while away',created_at:'2026-10-26T00:00:00Z',config:{algorithm:'robust-maxz',signals,analysisRange:[320,450]},summary:{flaggedSamples:1}});
    await act(async()=>{
      window.location.hash='#/workspaces/test/history';
      window.dispatchEvent(new dom.window.HashChangeEvent('hashchange'));
    });
    assert.ok(container.querySelector('a[href="#/workspaces/test/analysis/background-saved"]'),'history fetches a saved result even when its original page has unmounted');
  } finally { dom.window.scrollTo=()=>{}; }
});

test('a completed analysis cannot redirect or refresh a workstation that the user has already left', async () => {
  const source = dataset('pending-analysis');
  source.metadata.suggestedRanges = {baselineRange:[0,199],analysisRange:[200,899]};
  let resolveAnalysis, changed = 0;
  globalThis.fetch = () => new Promise(resolve => {resolveAnalysis=resolve;});
  await mount(React.createElement(AnalysisPage,{workspaceId:'test',datasets:[source],selected:source.id,setSelected(){},preferences:{},refresh(){changed++;}}));
  await click(button('Run analysis and save'));
  assert.ok(resolveAnalysis);
  await act(async () => root.render(React.createElement('p',null,'Another workstation')));
  const route = window.location.hash;
  await act(async () => resolveAnalysis(response({id:'completed-in-background'})));
  assert.equal(window.location.hash,route);
  assert.equal(changed,0);
  assert.equal(container.textContent,'Another workstation');
});

test('late saved analysis responses and failed deep links cannot restore an old result or hide the failure', async () => {
  const source = dataset('incident-data'), loads = [];
  globalThis.fetch = url => new Promise(resolve => loads.push({url,resolve}));
  const props={workspaceId:'test',datasets:[source],selected:source.id,setSelected(){},preferences:{},refresh(){}};
  await mount(React.createElement(AnalysisPage,{...props,jobId:'old'}));
  await act(async () => root.render(React.createElement(AnalysisPage,{...props,jobId:'missing'})));
  await act(async () => loads[1].resolve(new Response(JSON.stringify({error:'Saved analysis was not found.'}),{status:404,headers:{'Content-Type':'application/json'}})));
  await act(async () => loads[0].resolve(response(incidentResult('old'))));
  assert.match(container.querySelector('[role="alert"]').textContent,/Saved analysis was not found/);
  assert.equal(container.querySelector('.ws-analysis-form'),null);
  assert.equal(container.querySelector('.ws-result-anchor'),null);
});

test('new experiments retain dataset signal selection and start single-signal data with a compatible algorithm', async () => {
  const source=dataset('chosen-signals');
  globalThis.fetch=async url => response(url.endsWith('/incidents') ? {incidents:[]} : url.endsWith('/labels') ? {labels:[]} : {experiments:[]});
  await mount(React.createElement(ExperimentWorkspace,{workspaceId:'test',datasets:[source],initialDatasetId:source.id,initialSignals:[names[6]],onChanged(){}}));
  const checked=[...container.querySelectorAll('.experiment-editor .ws-signal-list input[type="checkbox"]')].filter(n=>n.checked).map(n=>n.closest('label').textContent.trim());
  assert.deepEqual(checked,[names[6]]);
  const config=newExperimentConfig({...source,metadata:{...source.metadata,columns:[source.metadata.columns[6]]}});
  assert.deepEqual(config.algorithms.map(a=>a.algorithm),['robust-maxz']);
  assert.deepEqual(newExperimentConfig(source,[names[6]]).signals,[names[6]]);
});



test('the workspace stays in English with a saved language from an earlier version', async () => {
  window.location.hash = '#/';
  window.localStorage.setItem('l5.locale', 'zh-CN');
  try {
    globalThis.fetch = async () => response({ workspaces: [] });
    await mount(React.createElement(App));
    assert.equal(document.documentElement.lang, 'en');
    assert.match(container.innerText || container.textContent, /workspace/i);
    assert.equal(container.querySelector('.language-switch'), null);
    const name = container.querySelector('#workspace-name');
    await setField(name, 'Analysis · 现场项目');
    assert.equal(name.value, 'Analysis · 现场项目');
  } finally {
    window.localStorage.removeItem('l5.locale');
  }
});

test('rerendering keeps an analysis request, its raw inputs and current route', async () => {
  const source = dataset('incident-data');
  source.metadata.suggestedRanges = { baselineRange: [0,199], analysisRange: [200,899] };
  let pending, requestSignal, requests = 0;
  globalThis.fetch = (url, options = {}) => {
    if (url.includes('/series?')) return Promise.resolve(response(seriesFor(url)));
    requests++; requestSignal = options.signal;
    return new Promise(resolve => pending = resolve);
  };
  const props = { workspaceId: 'test', datasets: [source], selected: source.id, setSelected() {}, preferences: {}, refresh() {} };
  await mount(React.createElement(AnalysisPage, props));
  const start = inputFor('Analysis start (s)'), name = inputFor('Analysis name (optional)');
  await setField(start, 300); await setField(name, '状态 / original name');
  await click(button('Run analysis and save'));
  const route = window.location.hash;
  await act(async () => root.render(React.createElement(AnalysisPage, props)));
  assert.equal(container.querySelector('input[value="状态 / original name"]'), name);
  assert.equal(inputFor('Analysis start (s)'), start);
  assert.equal(start.value, '300');
  assert.equal(name.value, '状态 / original name');
  assert.notEqual(requestSignal?.aborted, true);
  assert.equal(requests, 1);
  assert.equal(window.location.hash, route);
  await act(async () => pending(response({ ...incidentResult('bilingual-analysis'), datasetId: source.id })));
  assert.match(container.textContent, /Key findings/);
});

test('TripLens opens in English from workspace navigation and preserves a draft name', async () => {
  window.location.hash = '#/workspaces/test/history';
  globalThis.fetch = async url => response(url === '/api/workspaces' ? { workspaces: [{ id:'test', name:'User workspace' }] } : url.endsWith('/datasets') ? { datasets: [] } : url.endsWith('/analyses') ? { jobs: [] } : { id:'test', name:'User workspace' });
  await mount(React.createElement(App));
  runtimeAPI();
  await act(async () => { window.location.hash = '#/examples'; window.dispatchEvent(new window.HashChangeEvent('hashchange')); });
  assert.match(container.querySelector('.ws-example-banner').textContent, /L5 Workspaces/);
  const field = inputFor('Scenario name');
  await setField(field, '我的场景 / draft');
  assert.equal(field.value, '我的场景 / draft');
  assert.equal(window.location.hash, '#/examples');
});

test('English API errors and formatting preserve raw diagnostics and parameters', () => {
  assert.equal(errorMessage('Choose a nonempty CSV file.'), 'Choose a nonempty CSV file.');
  assert.equal(errorMessage("'Dataset not found.'"), 'Dataset not found.');
  assert.equal(errorMessage('alpha must be a finite number.'), 'alpha must be a finite number.');
  assert.equal(errorMessage('Request failed (503).'), 'Request failed (503).');
  assert.equal(t('Saved: {0}', {0: 'Status'}), 'Saved: Status');
  assert.equal(t('Saved: Status'), 'Saved: Status');
  assert.equal(runtimeText('Cooling flow falls — not observed'), 'Cooling flow falls — not observed');
  const diagnostic = '用户数据 / Original diagnostic #42';
  assert.equal(errorMessage(diagnostic), diagnostic);
});

test('report generation discards the earlier incident response after the saved incident changes', async () => {
  const { IncidentReport } = require('../src/workspace/investigation/IncidentReport.tsx');
  const requests = [];
  globalThis.fetch = url => new Promise(resolve => requests.push({url,resolve}));
  const incident = emptyIncident();
  await mount(React.createElement(IncidentReport, { incident }));
  await click(button('Generate report'));
  assert.equal(requests[0].url, '/api/incidents/event-one/report.html');
  await act(async () => root.render(React.createElement(IncidentReport, { incident: { ...incident, id: 'event-two' } })));
  await click(button('Generate report'));
  assert.equal(requests[1].url, '/api/incidents/event-two/report.html');
  const report = html => ({ok:true,headers:{get:()=> 'text/html'},text:async()=> html});
  await act(async () => requests[1].resolve(report('<html lang="en"><body>New report</body></html>')));
  await act(async () => requests[0].resolve(report('<html lang="en"><body>Old report</body></html>')));
  assert.match(container.querySelector('iframe').getAttribute('srcdoc'), /New report/);
  assert.doesNotMatch(container.querySelector('iframe').getAttribute('srcdoc'), /Old report/);
});

function twinFixture() {
  const source={...dataset('tank-calibration',201),metadata:{...dataset('tank-calibration',201).metadata,
    columns:['level1','level2','pump','valve','outlet'].map(name=>({name,missing:0,min:0,max:150}))}};
  const reference={...observationReference(source),unitsConfirmed:true,datasetName:source.name};
  const metric={samples:200,rmse:.002,mae:.0015,bias:.0001,std:.002,lag1:.01,quantiles:[-.003,0,.003],normalizedRmse:1,systematic:false,histogram:{edges:[-.004,0,.004],counts:[99,101]}};
  const evaluation={reference,times:[0,100,200],observed:{level1:[1,1.1,1.2],level2:[.8,.9,1]},predicted:{level1:[1,1.101,1.201],level2:[.8,.901,1.001]},original:{level1:[1,1.3,1.5],level2:[.8,1.1,1.3]},residuals:{level1:[0,.001,.001],level2:[0,.001,.001]},metrics:{level1:metric,level2:metric},originalMetrics:{level1:{...metric,rmse:.2},level2:{...metric,rmse:.2}},initializationExcluded:false,numericalStepDifferenceRmse:{level1:1e-7,level2:1e-7},massBalanceError:1e-14,parameterEnvelope:null};
  const parameters=Object.fromEntries(['pumpRate','connection','outlet'].map(k=>[k,{initial:.03,lower:.01,upper:.08,value:.035,unit:'m³/s'}]));
  const identity={rank:2,parameterCount:3,status:'rank-deficient',conditionNumber:null,singularValues:[1000,100,1e-9],rankTolerance:.001,sensitivityNorms:{pumpRate:1,connection:1,outlet:1},sensitivityCosine:[[1,0,1],[0,1,0],[1,0,1]],correlation:null,weakCombinations:[{singularValue:1e-9,combination:{pumpRate:.7,connection:0,outlet:-.7}}],activeBounds:[]};
  const uncertainty={available:false,standardErrors:null,covariance:null,method:'local-linearized-known-noise',assumptions:[]};
  const run={id:'calibration-run',workspaceId:'test',name:'Frozen calibration',status:'completed',createdAt:'2026-11-10T00:00:00Z',progress:{stage:'completed',evaluations:8},error:null,
    config:{calibration:reference,validation:{...reference,datasetId:'tank-validation'},parameters:Object.fromEntries(Object.entries(parameters).map(([k,p])=>[k,{initial:p.initial,lower:p.lower,upper:p.upper}])),nominal:{pumpRate:.03,connection:.04,outlet:.03},noise:{level1:.002,level2:.002},integrationStep:.05,maxEvaluations:80},
    result:{parameters,optimizer:{converged:true,evaluations:8,simulationCalls:50,cost:200,optimality:1e-7,trace:[]},identifiability:identity,uncertainty,warnings:['rank-deficient'],reducedChiSquare:1,calibration:evaluation,validation:{...evaluation,reference:{...reference,datasetName:'Independent measurements',datasetId:'tank-validation'},initializationExcluded:true,multiStep:[]},durationMs:2000}};
  return {source,run,identity,uncertainty};
}

test('calibration setup submits mapped observations and physical bounds, with an explicit independent validation source', async () => {
  const {source,run}=twinFixture(),writes=[];
  const validation={...source,id:'tank-validation',name:'Independent measurements'};
  const catalog={parameters:Object.fromEntries(['pumpRate','connection','outlet'].map(key=>[key,{label:key,unit:'m³/s',min:.0001,max:.2,scale:.03}])),nominal:{pumpRate:.03,connection:.04,outlet:.03}};
  globalThis.fetch=async(url,options={})=>{
    if(options.method==='POST'){writes.push(JSON.parse(options.body));return response({...run,status:'queued',result:null});}
    if(url.endsWith('/catalog'))return response(catalog);
    return response(url.endsWith('/twins') ? {twins:[]} : {runs:[]});
  };
  await mount(React.createElement(CalibrationWorkspace,{workspaceId:'test',datasets:[source,validation]}));
  await setField(container.querySelector('[aria-label="pumpRate upper"]'),.06);
  await setField(container.querySelector('[aria-label="Calibration observations level2"]'),'outlet');
  await setField(container.querySelector('[aria-label="Calibration observations level2"]'),'level2');
  const check=text=>[...container.querySelectorAll('label')].find(n=>n.textContent.includes(text)).querySelector('input');
  await click(check('I confirm the mapped signals'));
  await click(check('Add independent validation'));
  await setField(container.querySelector('[aria-label="Validation observations Dataset"]'),'tank-validation');
  await click([...container.querySelectorAll('.twin-check')].at(-1).querySelector('input'));
  await act(async()=>container.querySelector('form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));
  assert.equal(writes.length,1);
  assert.equal(writes[0].config.parameters.pumpRate.upper,.06);
  assert.equal(writes[0].config.calibration.mapping.level2,'level2');
  assert.equal(writes[0].config.validation.datasetId,'tank-validation');
  assert.equal(writes[0].config.validation.unitsConfirmed,true);
  assert.match(window.location.hash,/calibration\/calibration-run/);
  assert.match(container.textContent,/Calibrate a digital twin/);
  assert.equal(container.querySelector('[aria-label="pumpRate upper"]').value,'0.06');
});

test('rank-deficient results withhold uncertainty, keep independent metrics and save append-only twin revisions', async () => {
  const {source,run,identity,uncertainty}=twinFixture(),writes=[];
  const twin={id:'saved-twin',workspaceId:'test',name:run.name,revision:2,runId:run.id,createdAt:run.createdAt,validated:true,identifiability:identity,uncertainty,warnings:run.result.warnings};
  globalThis.fetch=async(url,options={})=>{
    if(options.method==='PATCH'){writes.push({url,body:JSON.parse(options.body)});return response({...twin,revision:3});}
    if(url.endsWith('/catalog'))return response({parameters:{},nominal:{}});
    if(url.endsWith('/revisions'))return response({revisions:[twin]});
    if(url.endsWith('/twins'))return response({twins:[twin]});
    if(url.endsWith(`/${run.id}`))return response(run);
    return response({runs:[run]});
  };
  await mount(React.createElement(CalibrationWorkspace,{workspaceId:'test',datasets:[source],runId:run.id}));
  assert.match(container.textContent,/not a unique physical estimate/);
  assert.match(container.textContent,/Independent measurements/);
  assert.match(container.textContent,/Withheld/);
  assert.equal(container.querySelectorAll('svg[aria-label="Residual histogram"]').length,2);
  await setField(container.querySelector('[aria-label="Save twin target"]'),'saved-twin');
  await click(button('Save next twin revision'));
  assert.deepEqual(writes[0].body,{runId:run.id,name:run.name,expectedRevision:2});
  assert.match(writes[0].url,/twins\/saved-twin$/);
  await act(async()=>root.render(React.createElement(CalibrationResults,{run:{...run,result:{...run.result,optimizer:{...run.result.optimizer,converged:false},warnings:['optimizer-incomplete']}}})));
  assert.match(container.textContent,/Optimizer incomplete/);
  assert.match(container.textContent,/Optimizer incomplete/);
  assert.match(container.textContent,/Independent validation/);
});

test('process safety saves a versioned limit, evaluates it, and attaches raw observed evidence', async () => {
  const source = dataset('tank-data', 3), createdAt = '2026-11-13T08:00:00Z';
  const signal = { id: 'tank-level', name: 'level1', displayName: 'Tank level', unit: 'm', missing: 1, datasetId: source.id };
  source.metadata.columns = [signal];
  source.metadata.model = { id: 'coupled-tanks', name: 'Coupled-Tank Process' };
  const incident = emptyIncident(), requests = [], configurations = [], assessments = [];
  const base = '/api/workspaces/test/safety';
  function assessment(body, saved) {
    const constraint = body.constraints[0];
    const interval = { state: 'violation', start: 1, end: 1, duration: 0, samples: 1, confirmedAt: 1, peakTime: 1, peakValue: 2.7, minimumMargin: -.2, maximumExceedance: .2 };
    return {
      ...(saved ? { id: 'safety-assessment' } : {}), workspaceId: 'test', datasetId: source.id, name: body.name, createdAt,
      source: { datasetName: source.name, time: source.metadata.time, signals: [signal] },
      configuration: { id: body.configurationId, revision: body.configurationRevision, name: configurations[0]?.name, constraints: [constraint] },
      forecastOptions: body.forecast,
      observed: [{ constraint, signalIds: [signal.id], marginUnit: 'm', sourceUnits: { [signal.id]: 'm' },
        current: { time: 2, value: null, margin: null, state: 'unavailable', rawState: 'unavailable' },
        coverage: { evaluatedSamples: 2, totalSamples: 3, sampleFraction: 2 / 3, observedDuration: 1, durationFraction: .5 },
        quality: { missingSamples: 1, unobservedSamples: 0, duplicateCount: 0, rateUnavailableSamples: 0, numericalUnavailableSamples: 0, gaps: [] },
        intervals: [interval], rawViolationIntervals: [interval], minimumMargin: -.2, maximumExceedance: .2, violationDuration: 0,
        series: { times: [0, 1, 2], values: [2.4, 2.7, null], margins: [.1, -.2, null], measurements: { [signal.id]: [2.4, 2.7, null] },
          states: ['normal', 'violation', 'unavailable'], rawStates: ['normal', 'violation', 'unavailable'], segmentIds: [0, 0, 1] },
      }],
      forecast: { status: 'unavailable', reasonCode: 'missing-observation', observedThrough: 2, requestedAsOf: 2, model: null,
        inputMeasurements: null, assumptions: {}, trajectory: null, constraints: [], uncertainty: null },
    };
  }
  globalThis.fetch = async (url, options = {}) => {
    const method = options.method || 'GET', body = options.body && JSON.parse(options.body);
    requests.push({ url, method, body });
    if (url === '/api/workspaces') return response({ workspaces: [{ id: 'test', name: 'Safety project' }] });
    if (url === '/api/workspaces/test') return response({ id: 'test', name: 'Safety project' });
    if (url.endsWith('/datasets')) return response({ datasets: [source] });
    if (url.endsWith('/analyses')) return response({ jobs: [] });
    if (url.endsWith('/signals')) return response({ signals: [signal] });
    if (url === '/api/simulations?workspaceId=test') return response({ simulations: [] });
    if (url === `${base}/configurations` && method === 'GET') return response({ configurations });
    if (url === `${base}/configurations` && method === 'POST') {
      const saved = { ...body, id: 'limit-config', workspaceId: 'test', revision: 1, createdAt, updatedAt: createdAt };
      configurations.push(saved);
      return response(saved);
    }
    if (url === `${base}/configurations/limit-config` && method === 'PATCH') {
      configurations[0] = { ...configurations[0], ...body, revision: 2 };
      return response(configurations[0]);
    }
    if (url === `${base}/assessments` && method === 'GET') return response({ assessments });
    if (url === `${base}/evaluate`) return response(assessment(body, false));
    if (url === `${base}/assessments` && method === 'POST') {
      const saved = assessment(body, true);
      assessments.push(saved);
      return response(saved);
    }
    if (url === `${base}/assessments/safety-assessment`) return response(assessments[0]);
    if (url === '/api/workspaces/test/incidents') return response({ incidents: [incident] });
    if (url === `${base}/assessments/safety-assessment/incident-evidence`) return response(incident);
    throw new Error(`Unexpected safety request ${url}`);
  };
  window.location.hash = '#/workspaces/test/safety?dataset=tank-data';
  await mount(React.createElement(App));
  assert.equal(container.querySelector('[aria-current="page"]').textContent.trim(), 'Process safety');
  assert.equal(inputFor('Dataset').value, source.id);
  await click(button('Add constraint'));
  await setField(inputFor('Constraint name'), 'Tank operating ceiling');
  await setField(inputFor('Critical upper limit'), 2.6);
  await setField(inputFor('Configuration name'), 'Tank limits');
  await click(button('Save configuration'));
  const original = requests.find(item => item.method === 'POST' && item.url.endsWith('/configurations')).body.constraints[0];
  assert.equal(original.terms[0].signalId, signal.id);
  assert.equal(original.unit, 'm');
  await setField(inputFor('Critical upper limit'), 2.5);
  await click(button('Save new revision'));
  const edit = requests.find(item => item.method === 'PATCH');
  assert.equal(edit.body.revision, 1);
  assert.equal(edit.body.constraints[0].id, original.id);
  assert.equal(edit.body.constraints[0].upper, 2.5);
  await click(inputFor('Include a forecast'));
  await click(button('Evaluate limits'));
  const evaluation = requests.find(item => item.url.endsWith('/evaluate'));
  assert.equal(evaluation.body.configurationRevision, 2);
  assert.equal(evaluation.body.forecast.input.mode, 'hold');
  assert.match(container.textContent, /A measured level or control input is unavailable/);
  await click(button('Evaluate again and save'));
  await act(async () => window.dispatchEvent(new window.HashChangeEvent('hashchange')));
  assert.equal(window.location.hash, '#/workspaces/test/safety/safety-assessment');
  assert.ok(container.querySelector('a[download][href*="format=csv"]'));
  const raw = [...container.querySelectorAll('details')].find(node => node.querySelector('summary').textContent.startsWith('Raw critical exceedances'));
  raw.open = true;
  await click([...raw.querySelectorAll('button')].find(node => node.textContent === 'Attach to Incident'));
  await setField(dialogField('Incident'), incident.id);
  await click(button('Attach evidence'));
  const link = requests.find(item => item.url.endsWith('/incident-evidence'));
  assert.deepEqual(link.body, { kind: 'observed', constraintId: original.id, intervalIndex: 0, raw: true, incidentId: incident.id });
  assert.ok(container.querySelector('a[href="#/workspaces/test/incidents/event-one"]'));
  assert.equal(container.querySelector('h1').textContent, "Process safety & predictive risk");
  assert.equal(inputFor('Critical upper limit').value, '2.5');
});

test('shared application labels have unique English display names by key', () => {
  const file = new URL('../l5/labels.json', import.meta.url);
  const source = ts.parseJsonText('labels.json', readFileSync(file, 'utf8'));
  const names = new Set();
  for (const property of source.statements[0].expression.properties) {
    const key = property.name.text;
    assert.ok(!names.has(key), key);
    names.add(key);
    assert.ok(property.initializer.text.length, key);
    assert.doesNotMatch(property.initializer.text, /[\u3400-\u9fff]/, key);
  }
});

test('local validation and report errors display in English and preserve input', async () => {
  const source = dataset('report-error');
  globalThis.fetch = async url => url.endsWith('/labels') ? response({labels: []}) : new Response('', {status: 503});
  await mount(React.createElement(ExperimentLabels, {dataset: source, onChange(){}}));
  await setField(inputFor('Label JSON'), '{}');
  await click(button('Load JSON into editor'));
  assert.equal(container.querySelector('[role="alert"]').textContent, 'Import JSON needs timeBasis: dataset-seconds, timeSource, and intervals.');
  assert.equal(inputFor('Label JSON').value, '{}');
  const fixture = researchFixture();
  await act(async () => root.render(React.createElement(ExperimentReport, {experiment: fixture.experiment, dirty: false})));
  await click(button('Preview experiment report'));
  assert.equal(container.querySelector('[role="alert"]').textContent, 'Unable to generate experiment report from the local service.');
});

test('system timeline labels are English and user records preserve their text', () => {
  const {axisLabel, timelineTitle} = require('../src/workspace/types.ts');
  const source = dataset('raw-user-names'), result = incidentResult();
  const view = {analyses: [{id: result.id, result}], datasets: [source]};
  const alarm = {id: 'interval:'+result.id+':0', kind: 'alarm', analysisId: result.id, title: 'Robust Max-Z · Anomaly interval'};
  const userNote = {id: 'entry:raw', kind: 'note', title: '现场状态变更'};
  assert.equal(axisLabel({id:'incident:event-one',label:'Independent incident time axis',origin:null}), 'Independent incident time axis');
  assert.equal(timelineTitle({id:'history:status',kind:'status',title:'Status change'},view), 'Status change');
  assert.equal(timelineTitle(alarm,view), 'Robust Max-Z · Anomaly interval');
  assert.equal(timelineTitle(userNote,view), '现场状态变更');
  assert.equal(axisLabel({id:'utc',label:'UTC',origin:'1970-01-01T00:00:00Z'}), 'UTC absolute time');
  assert.equal(axisLabel({id:'dataset:raw',label:'现场时钟',origin:null}), '现场时钟');
});

test('scripted example prose is English and preserves the original brief and scenario', async () => {
  const {RootCauses, AnalystPanel} = require('../src/components/Investigation.tsx');
  const {scenario} = require('../src/lib/engine.ts');
  const brief = {schemaVersion:1,incidentId:scenario.id,provider:'local',prompt:scenario.analyst.prompt,steps:scenario.analyst.steps,summary:scenario.analyst.summary,limitation:scenario.analyst.limitation};
  const before = JSON.stringify({scenario, brief});
  await mount(React.createElement(React.Fragment,null,
    React.createElement(RootCauses,{ready:true,selected:scenario.candidates[0].id,onSelect(){},onInspect(){}}),
    React.createElement(AnalystPanel,{brief,step:0,running:false,error:null,onRun(){},onExport(){},onCompare(){},ready:true})));
  assert.match(container.textContent,/The pressure rise is a downstream symptom/);
  assert.doesNotMatch(container.textContent,/[\u3400-\u9fff]/);
  assert.equal(JSON.stringify({scenario,brief}),before);
});

test('model action IDs use English labels and summaries preserve observations', async () => {
  const {ModelForecastView} = require('../src/workspace/modeling/ModelResults.tsx');
  const baseline = {times:[0,1],values:{level1:[1,1]},metrics:{peakLevel:1}};
  const forecast = {format:'model-forecast-v1',mode:'known',observedThrough:0,at:0,horizon:1,
    baseline,branches:[{...baseline,action:'adjust_pump'}],
    metricDefinitions:[{key:'peakLevel',label:'Peak physical level',unit:'m'}],
    signalDefinitions:[{key:'level1',label:'Tank 1 physical level',unit:'m'}],
    uncertainty:'Known illustrative model; no parameter fitting or predictive uncertainty bounds. Metrics start at the action time.'};
  const before=JSON.stringify(forecast);
  await mount(React.createElement(ModelForecastView,{forecast}));
  assert.match(container.textContent,/Adjust inlet pump command/);
  assert.match(container.textContent,/Peak physical level/);
  assert.equal(runtimeText('10/12 samples · age 2s · extreme step'), '10/12 samples · age 2s · extreme step');
  assert.doesNotMatch(container.textContent,/[\u3400-\u9fff]/);
  assert.equal(JSON.stringify(forecast),before);
});

function healthResult() {
  const episode = {start:220,end:240,detectedAt:220,samples:21,severity:2,indicatorIds:['shift'],signals:['temperature'],assessment:'sensor',evidenceCoverage:1,
    candidates:[{key:'level2_offset',category:'sensor',fitError:.5,penalizedError:1.5,improvement:.95,parameters:{offset:.2},constraints:['hydraulic2','balance2']}]};
  return {id:'health-1',workspaceId:'test',datasetId:'sensor-data',name:'Saved health',version:'1.0.0',createdAt:'2026-01-01T00:00:00Z',sourceDigest:'abc123',
    config:{signals:['temperature'],baselineRange:[0,149],analysisRange:[150,299],window:21,persistence:3,z:6,relationships:[]},
    times:[200,220,240],signals:{temperature:{referenceMedian:1,referenceScale:.01,measuredFraction:1,observed:[1,1.2,1.2],segmentIds:[1,1,1]}},
    indicators:[{id:'shift',kind:'level_shift',signals:['temperature'],threshold:6,scores:[0,10,10],intervals:[{...episode,peakTime:220,evidenceValue:10}],evidence:{referenceMedian:1,referenceScale:.01,interpretation:'A level shift can be a sensor offset or a real process change.'}}],
    episodes:[episode],warnings:[],limitations:['integrity_is_not_causality'],reference:{times:[0,1,2],values:{temperature:[1,1.01,.99]},fitSamples:105,calibrationSamples:45},relationships:[],
    physical:{kind:'coupled-tanks',mapping:{level2:'temperature'},parameters:{area2:1},expected:{temperature:[1,1,1]},segmentIds:{temperature:[1,1,1]},measuredCoverage:1,assumptions:['independent_flow_measurements'],residuals:[{key:'hydraulic2',unit:'m',values:[0,.2,.2],scale:.01,threshold:.06}]},
    datasetSnapshot:{name:'sensor-data',time:{kind:'numeric',column:'t',origin:null,start:0,end:299},createdAt:'2026-01-01'},summary:{samples:3,flaggedSamples:2,episodes:1,firstDetection:220}};
}

test('sensor workspace declares normal, saves numerical configuration and links a real interval to an existing incident', async () => {
  const source=dataset('sensor-data',300); source.metadata.columns=[{name:'temperature',missing:0,min:0,max:2}];
  source.metadata.suggestedRanges={baselineRange:[0,1],analysisRange:[2,299]};
  assert.notDeepEqual(newHealthConfig(source).baselineRange,[0,1]);
  const saved=healthResult(), requests=[];
  globalThis.fetch=async (url,options={})=>{
    if(url.endsWith('/sensor-model')) return response({model:null});
    if(url.startsWith('/api/simulations')) return response({simulations:[]});
    if(url.endsWith('/sensor-health') && options.method==='POST'){requests.push(JSON.parse(options.body));return response(saved);}
    if(url.endsWith('/sensor-health')) return response({diagnostics:[]});
    if(url.endsWith('/incidents')) return response({incidents:[{id:'incident-1',title:'Existing incident',status:'investigating'}]});
    if(url.endsWith('/incidents/incident-1/links')){requests.push(JSON.parse(options.body));return response({id:'incident-1'});}
    throw new Error(url);
  };
  await mount(React.createElement(SensorHealthWorkspace,{workspaceId:'test',datasets:[source],onChanged(){}}));
  assert.equal(button('Run and save diagnostics').disabled,true);
  await click(container.querySelector('.health-confirm input'));
  assert.equal(button('Run and save diagnostics').disabled,false);
  await act(async()=>container.querySelector('form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
  assert.equal(requests[0].datasetId,'sensor-data');
  assert.deepEqual(requests[0].signals,['temperature']);
  assert.equal(requests[0].z,6);
  assert.match(window.location.hash,/sensor-health\/health-1/);
  assert.match(container.textContent,/Tank 2 level sensor offset/);
  await click(button('Link this interval to Incident'));
  assert.ok(container.querySelector('dialog[open]'));
  await act(async()=>container.querySelector('dialog form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
  assert.deepEqual(requests[1],{kind:'sensor-health',diagnosticId:'health-1',episodeIndex:0});
  assert.match(window.location.hash,/incidents\/incident-1/);
});

test('saved sensor results switch languages without rewriting evidence and share graph cursor selection', async () => {
  const saved=healthResult(), before=JSON.stringify(saved);
  await mount(React.createElement(SensorHealthResult,{result:saved}));
  const svg=container.querySelector('svg');
  await act(async()=>svg.dispatchEvent(new window.MouseEvent('pointermove',{bubbles:true,clientX:100})));
  assert.ok(container.querySelectorAll('[data-selected-time]').length>=2);
  assert.match(container.textContent,/Tank 2 level sensor offset/);
  assert.match(container.textContent,/Tank 2 level sensor offset/);
  assert.match(container.textContent,/Physical constraint residual/);
  assert.doesNotMatch(container.textContent,/Rankings compare residual corrections/);
  assert.equal(JSON.stringify(saved),before);
});

test('sensor deep links ignore an aborted older response and preserve saved results after reopening', async () => {
  const saved=healthResult(); let resolveOld;
  const old=new Promise(resolve=>{resolveOld=resolve;});
  globalThis.fetch=async url=>url.endsWith('/sensor-health/old') ? old : url.endsWith('/sensor-health/new') ? response({...saved,id:'new',name:'Newest diagnostic'}) : url.endsWith('/sensor-model') ? response({model:null}) : url.startsWith('/api/simulations') ? response({simulations:[]}) : response({diagnostics:[]});
  const props={workspaceId:'test',datasets:[dataset('sensor-data',300)],onChanged(){}};
  await mount(React.createElement(SensorHealthWorkspace,{...props,diagnosticId:'old'}));
  await act(async()=>root.render(React.createElement(SensorHealthWorkspace,{...props,diagnosticId:'new'})));
  assert.match(container.textContent,/Newest diagnostic/);
  await act(async()=>resolveOld(response({...saved,name:'Stale diagnostic'})));
  assert.doesNotMatch(container.textContent,/Stale diagnostic/);
});

function controlFixture(){
  const protocol=defaultProtocol();protocol.reference=[{time:0,level:1},{time:2,level:1.2}];
  const rows=[0,2,4].map(t=>({t,level1:1.5625+t*.01,level2:1+t*.02,reference:t<2?1:1.2,error:t<2?0:.2-t*.02,pump:100+t*2,valve:1,inlet:.03,transfer:.03,outlet:.03}));
  return {id:'control-run',name:'Control comparison evidence',workspaceId:'test',createdAt:'2026-11-09T00:00:00Z',format:'tank-control-1',modelId:'coupled-tanks',modelVersion:'1.0.0',scenarioSnapshot:null,config:{fault:'healthy',duration:4,start:2,step:.2,seed:3,tankHeight:2.5},protocol,datasets:{},noiseFingerprint:'fixed-common-noise',solver:{name:'QP'},
    results:['open-loop','pi','mpc'].map((controller,i)=>({controller,settings:{kind:controller},rows,physical:rows,metrics:{iae:10-i,solverFailures:0,maxLevelViolation:0,recovery:[]},decisions:rows.slice(0,2).map(r=>({time:r.t,measurement:r,command:{pump:r.pump,valve:1},reference:r.reference,durationMs:1,solver:{status:controller==='mpc'?'solved':controller,iterations:4,primalResidual:1e-9,stationarityResidual:1e-9,...(controller==='mpc'?{prediction:[[1.6,1.1],[1.7,1.2]],targets:[1.2,1.2],plan:[[1.1,1],[1.2,1]]}:{})}}))})),metricDefinitions:[{key:'iae',label:'Measured tracking IAE',unit:'m·s'}]};
}

test('Control editor sends selected scenario version, reference, constraints and controller parameters',async()=>{
  const {model,scenario}=modelFixture('coupled-tanks');model.defaults.tankHeight=2.5;
  const requests=[];
  globalThis.fetch=async(url,options)=>{
    if(options?.method==='POST'){requests.push(JSON.parse(options.body));return response(controlFixture());}
    return response(url==='/api/models/coupled-tanks'?model:url.endsWith('/scenarios')?{scenarios:[scenario]}:{experiments:[]});
  };
  await mount(React.createElement(ControlWorkspace,{workspaceId:'test',onSaved(){}}));
  await setField(inputFor('Tank scenario'),scenario.id);
  await setField(inputFor('Proportional gain (%/m)'),210);
  await setField(inputFor('Control interval (s)'),3);
  await setField(inputFor('Maximum pump (%)'),130);
  await setField(inputFor('Experiment name'),'Specific control run');
  await click(button('+ Setpoint change'));
  await act(async()=>container.querySelector('form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));
  assert.equal(requests.length,1);
  assert.equal(requests[0].scenarioId,scenario.id);assert.equal(requests[0].scenarioVersion,1);
  assert.equal(requests[0].config,undefined);
  assert.equal(requests[0].protocol.controllers.find(c=>c.kind==='pi').kp,210);
  assert.equal(requests[0].protocol.constraints.pumpMax,130);
  assert.equal(requests[0].protocol.sampleInterval,3);
  assert.equal(requests[0].protocol.reference.length,3);
  assert.ok(container.textContent.includes('Control comparison evidence'));
  assert.equal(container.querySelectorAll('.control-results > figure svg').length,5);
});

test('Control saved results share cursor, retain evidence, export and connect Dataset workflow in both languages',async()=>{
  const experiment=controlFixture(),before=JSON.stringify(experiment),saved=[];
  globalThis.fetch=async(url,options)=>{assert.equal(JSON.parse(options.body).controller,'mpc');return response({...dataset('control-dataset'),metadata:{...dataset('control-dataset').metadata,model:{simulationId:'control-session'}}});};
  await mount(React.createElement(ControlResults,{experiment,onSaved:(d,kind)=>saved.push([d.id,kind])}));
  await setField(container.querySelector('input[type=range]'),1);
  assert.match(container.querySelector('.control-readout').textContent,/1.2/);
  assert.deepEqual([...container.querySelectorAll('.control-results > figure [data-selected-time]')].map(n=>n.getAttribute('data-selected-time')),['2','2','2','2','2']);
  assert.ok(container.textContent.includes('2 s / 4 s'));
  await click(button('Save selected controller as Dataset'));
  assert.deepEqual(saved,[['control-dataset','mpc']]);
  assert.ok(container.querySelector('a[href="#/workspaces/test/experiments/new/control-dataset"]'));
  assert.ok(button('Link Dataset to Incident'));
  const report=container.querySelector('a[href*="report.html"]');assert.ok(report.href.endsWith('report.html'));
  assert.match(container.textContent,/Measured tracking IAE|Link Dataset to Incident/);

  assert.equal(JSON.stringify(experiment),before);
});

test('Control reopening drops stale responses and restores the saved protocol',async()=>{
  const {model}=modelFixture('coupled-tanks'),fixture=controlFixture();let resolveOld;
  globalThis.fetch=async url=>{
    if(url.endsWith('/old'))return new Promise(resolve=>{resolveOld=resolve;});
    if(url.endsWith('/new'))return response({...fixture,id:'new',name:'New saved control'});
    return response(url==='/api/models/coupled-tanks'?model:url.endsWith('/scenarios')?{scenarios:[]}:{experiments:[]});
  };
  await mount(React.createElement(ControlWorkspace,{workspaceId:'test',experimentId:'old',onSaved(){}}));
  await act(async()=>root.render(React.createElement(ControlWorkspace,{workspaceId:'test',experimentId:'new',onSaved(){}})));
  await act(async()=>resolveOld(response({...fixture,id:'old',name:'Stale control result'})));
  assert.ok(container.textContent.includes('New saved control'));
  assert.ok(!container.textContent.includes('Stale control result'));
  assert.equal(inputFor('Control interval (s)').value,'2');
  assert.equal(container.querySelectorAll('.control-summary-cards button').length,3);
});

function estimationFixture(id='estimation-1') {
  const rows=[0,.3,1.1].map((t,i)=>({t,estimate:[1.4-i*.01,1-i*.01],prediction:[1.3,.9],openLoop:[1.2,.8],
    direct:[i===0 ? 1.45 : null,i===2 ? .99 : null],observed:[i===0 ? 1.45 : null,i===2 ? .99 : null],
    covariance:[[.002,.001],[.001,.003]],lower:[1.3,.9],upper:[1.5,1.1],innovation:[i===0 ? .15 : null,i===2 ? .09 : null],
    residual:[i===0 ? .05 : null,i===2 ? .01 : null],innovationSd:[i===0 ? .1 : null,i===2 ? .1 : null],nis:i===1 ? null : 1,dof:i===1 ? 0 : 1}));
  return {id,name:id,workspaceId:'test',createdAt:'2026-11-10T00:00:00Z',format:'tank-estimation-v1',inputSha256:'abc123',
    source:{kind:'simulation'},request:{sensors:['level1','level2']},inputs:{observations:rows.map(r=>({t:r.t}))},
    result:{rows,sensors:['level1','level2'],config:{initialState:[1.2,.7],initialTime:0,maxStep:.1,jacobianStep:1e-5,initialCovariance:[[.16,0],[0,.16]],processCovariance:[[1e-6,0],[0,1e-6]],measurementCovariance:[[.0004,0],[0,.0004]]},model:{},predictionOnly:1,warnings:[],innovationMean:[.15,.09],
      innovationConsistency:{1:{count:2,meanNIS:1,expectedMean:1,fraction95:1}}},score:null,
    comparisons:[{sensors:['level1','level2'],predictionOnly:1,score:null}],
    observability:[{point:[1.5625,1],sensors:['level2'],A:[[-.02,.02],[.02,-.035]],H:[[0,1]],matrix:[[0,1],[.02,-.035]],
      rank:2,singularValues:[1,.02],condition:50,poorlyObservable:false,status:'local-linearization',equilibrium:true,drift:[0,0]}]};
}

test('estimation uses selected sensors and full covariance, preserves missing samples and exports a saved Dataset',async()=>{
  const saved=[],writes=[],run=estimationFixture(),generated=dataset('estimated-dataset');
  globalThis.fetch=async(url,options={})=>{
    if(url.endsWith('/scenarios'))return response({scenarios:[]});
    if(options.method==='POST') {
      writes.push({url,body:JSON.parse(options.body)});
      return response(url.endsWith('/dataset') ? generated : run);
    }
    return response({runs:[]});
  };
  await mount(React.createElement(EstimationWorkspace,{workspaceId:'test',datasets:[],onSaved:d=>saved.push(d)}));
  await click([...container.querySelectorAll('label')].find(l=>l.textContent==='Observe Tank 1').querySelector('input'));
  await setField(inputFor('R · measurement covariance (m²)'), '[[0.0004,0.0001],[0.0001,0.0009]]');
  await act(async()=>container.querySelector('form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));
  assert.deepEqual(writes[0].body.sensors,['level2']);
  assert.deepEqual(writes[0].body.config.measurementCovariance,[[.0004,.0001],[.0001,.0009]]);
  assert.equal(writes[0].body.source.irregular,true);
  assert.ok(!('truth' in writes[0].body));
  assert.equal(container.querySelectorAll('[data-uncertainty-band]').length,2);
  assert.equal(container.querySelectorAll('[data-measurement-points] circle').length,2,'isolated observations remain visible without filling gaps');
  assert.ok(container.textContent.includes('Inferred at this time'));
  await click(button('Export estimates as Dataset'));
  assert.equal(saved[0].id,generated.id);
  assert.equal(writes[1].url,'/api/estimations/estimation-1/dataset');
  assert.ok(container.querySelector('a[href="#/workspaces/test/datasets/estimated-dataset"]'));
});

test('estimation charts share cursor and window and relocalize without rerunning inference',async()=>{
  let exports=0;
  await mount(React.createElement(EstimationResults,{run:estimationFixture(),onExport(){exports++;},busy:false}));
  const svg=container.querySelector('svg');
  svg.getBoundingClientRect=()=>({left:0,width:960,top:0,height:190,right:960,bottom:190});
  await act(async()=>svg.dispatchEvent(new dom.window.MouseEvent('pointermove',{bubbles:true,clientX:500})));
  const cursors=[...container.querySelectorAll('[data-selected-time]')];
  assert.equal(cursors.length,6);
  assert.equal(new Set(cursors.map(n=>n.getAttribute('data-selected-time'))).size,1);
  await setField(inputFor('Window end (s)'),.3);
  assert.equal(container.querySelectorAll('[data-measurement-points] circle').length,1);
  assert.ok(container.textContent.includes("Local observability"));
  assert.ok(container.textContent.includes("Export estimates as Dataset"));
  assert.ok(container.textContent.includes('Local observability'));
  assert.equal(exports,0);
});

test('late estimation load cannot overwrite a newer run or reappear after unmount',async()=>{
  let resolveFirst;
  globalThis.fetch=(url)=>{
    if(url.endsWith('/scenarios'))return Promise.resolve(response({scenarios:[]}));
    if(url.endsWith('/estimations'))return Promise.resolve(response({runs:[]}));
    if(url.endsWith('/first'))return new Promise(resolve=>{resolveFirst=resolve;});
    return Promise.resolve(response(estimationFixture('second')));
  };
  const props={workspaceId:'test',datasets:[],onSaved(){}};
  await mount(React.createElement(EstimationWorkspace,{...props,runId:'first'}));
  await act(async()=>root.render(React.createElement(EstimationWorkspace,{...props,runId:'second'})));
  await act(async()=>resolveFirst(response(estimationFixture('first'))));
  assert.equal(container.querySelector('.estimation-results h2').textContent,'second');
  assert.ok(!container.querySelector('[role="status"]'));
});

test('generated estimation Dataset retains a route to its frozen run and processed-value explanation',async()=>{
  const d=dataset('generated-estimates');d.metadata.estimation={runId:'frozen-run',createdAt:'2026-11-10T00:00:00Z',inputSha256:'frozen-hash',source:{kind:'simulation'},request:{}};
  await mount(React.createElement(EstimationProvenance,{dataset:d}));
  assert.ok(container.querySelector('a[href="#/workspaces/test/estimations/frozen-run"]'));
  assert.ok(container.textContent.includes('processed-value observation policy'));
  assert.ok(container.textContent.includes('frozen-hash'));
});

test('reopened estimation restores covariance, source scenario version and sensor settings for a reproducible rerun',async()=>{
  const run=estimationFixture('restored');
  run.source={kind:'scenario',scenarioId:'scenario-1',scenarioSnapshot:{version:1},noise:[.03,.04],every:[2,7],dropout:.2,irregular:true};
  run.request={model:{connection:.031},knownControls:['pumpControl'],compareSensors:true,operatingPoint:[1.8,.9]};
  run.result.sensors=['level2'];run.result.config.initialState=[.8,.5];run.result.config.measurementCovariance=[[.0009,.0001],[.0001,.0016]];
  let submitted;
  globalThis.fetch=async(url,options={})=>{
    if(url.endsWith('/scenarios'))return response({scenarios:[{id:'scenario-1',modelId:'coupled-tanks',name:'Newer scenario',version:2}]});
    if(options.method==='POST'){submitted=JSON.parse(options.body);return response({...run,id:'restored-rerun'});}
    if(url.endsWith('/estimations'))return response({runs:[{id:run.id,name:run.name,created_at:run.createdAt}]});
    return response(run);
  };
  await mount(React.createElement(EstimationWorkspace,{workspaceId:'test',datasets:[],runId:run.id,onSaved(){}}));
  assert.equal(inputFor('R · measurement covariance (m²)').value,'[[0.0009,0.0001],[0.0001,0.0016]]');
  await act(async()=>container.querySelector('form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));
  assert.equal(submitted.source.version,1,'rerun stays on the saved scenario version');
  assert.deepEqual(submitted.source.noise,[.03,.04]);
  assert.deepEqual(submitted.config.initialState,[.8,.5]);
  assert.deepEqual(submitted.sensors,['level2']);
  assert.deepEqual(submitted.knownControls,['pumpControl']);
});

test('alarm workspace reopens and acknowledges a saved alarm without clearing', async () => {
  const { AlarmWorkspace } = require('../src/workspace/monitoring/AlarmWorkspace.tsx');
  const { defaultAlarmPolicy } = require('../src/workspace/monitoring/alarmTypes.ts');
  const result = incidentResult('reactor-alarm-run'), source = dataset(result.datasetId);
  const axis = { id: 'dataset:' + source.id, label: source.name, origin: null, start: 200, end: 699 };
  const first = { ...result.intervals[0], id: 'alarm-1', datasetId: source.id, datasetName: source.name,
    analysisId: result.id, analysisName: 'Temperature monitor', detectorLabel: result.algorithmLabel,
    axisId: axis.id, offset: 0, intervalIndex: 0, durationSeconds: 39,
    nativeStart: 340, nativeEnd: 379, nativePeakTime: 350, nativeContributionTime: 350,
    affectedSignals: [names[0]], threshold: 3, peakAboveThreshold: 27, peakMagnitude: 30,
    measuredState: 'active', endReason: 'analysis-end', observedSpan: [200, 379], observedFraction: 1,
    quality: { gapThreshold: 5, coverageFraction: 1, abstainedSamples: 0 },
    provenance: { contributionMetric: result.contributionMetric },
    priority: 'high', equipment: ['Reactor'], policyEligible: true,
    operator: { acknowledgedAt: null, shelvedUntil: null, incidentIds: [], escalated: false } };
  const second = { ...first, id: 'alarm-2', detectorLabel: 'EWMA', operator: { ...first.operator } };
  const group = { id: 'alarm-group', axisId: axis.id, start: 340, end: 379,
    eventIds: [first.id, second.id], priority: 'high', incidentIds: [], relationships: [] };
  const stamp = new Date().toISOString();
  const session = { id: 'reactor-review', name: 'Shift review', workspaceId: 'test', analysisIds: [result.id],
    policy: defaultAlarmPolicy, createdAt: stamp, updatedAt: stamp, asOf: stamp,
    events: [first, second], groups: [group], axes: [axis], audit: [],
    flood: { rawEventCount: 2, groupCount: 1, axes: [] } };
  const writes = [];
  globalThis.fetch = async (url, options = {}) => {
    if (url.includes('/series?')) return response(seriesFor(url));
    if (url === '/api/analyses/' + result.id) return response(result);
    if (url === '/api/workspaces/test/alarm-sessions') return response({ sessions: [session] });
    if (url === '/api/alarm-sessions/' + session.id) return response(session);
    if (url.endsWith('/events/alarm-1/actions')) {
      const body = JSON.parse(options.body);
      writes.push(body);
      first.operator.acknowledgedAt = stamp;
      session.audit.push({ id: 'audit-1', eventId: first.id, kind: body.kind, actor: body.actor, recordedAt: stamp });
      return response(session);
    }
    assert.fail('unexpected request ' + url);
  };
  await mount(React.createElement(AlarmWorkspace, { workspaceId: 'test', datasets: [source], jobs: [], sessionId: session.id }));
  assert.match(container.textContent, /Shift review/);
  assert.match(container.textContent, /2 matching alarms in 1 groups/);
  await click(container.querySelector('.alarm-event-button'));
  assert.ok(curve(names[0]), 'measurement evidence renders for a source alarm');
  assert.ok(curve('Detector score'));
  await setField(inputFor('Operator name (optional)'), 'Shift lead');
  await click(button('Acknowledge'));
  assert.deepEqual(writes, [{ kind: 'acknowledge', actor: 'Shift lead' }]);
  assert.match(container.querySelector('.alarm-operator').textContent, /Active at analysis end · Acknowledged/);
  await setField(inputFor('Operator state'), 'Acknowledged');
  assert.match(container.textContent, /1 matching alarms in 1 groups/);
  assert.equal(container.querySelectorAll('.alarm-event-button').length, 2, 'filters retain every group member');
  assert.match(container.textContent, /Alarm timeline/);
});

test('predictive maintenance fits the generated measurements, localizes results, saves and links a snapshot', async () => {
  const { PrognosticWorkspace } = require('../src/workspace/reliability/PrognosticWorkspace.tsx');
  const pump = dataset('pump-data', 101);
  pump.metadata.columns = [
    { name: 'capacity_loss', unit: 'fraction', missing: 1, min: .05, max: .3 },
    { name: 'pump', unit: '%', missing: 0, min: 45, max: 55 },
  ];
  const base = '/api/workspaces/test/prognostics';
  const config = {
    datasetId: pump.id, assetId: 'pump-1', assetName: 'Pump 1', loadSignal: 'pump',
    indicator: { signal: 'capacity_loss', definition: 'Measured fractional loss of capacity', unit: 'fraction',
      direction: 'increasing', failure_threshold: .4, operating_threshold: .3 },
    start: 0, cutoff: 60, horizon: 20, method: 'stochastic', seed: 35, endStatus: 'censored',
    events: [{ time: 20, action: 'restore' }], operatingPeriods: [[0, 100]],
    maintenance: { preventive_cost: 50, corrective_cost: 250, downtime_cost: 1,
      preventive_duration: 30, corrective_duration: 90, failure_consequence: 50,
      replacement_cost: 130, replacement_duration: 40, planning_horizon: 20, scheduled_time: 10 },
  };
  const scheduled = { action: 'schedule', time: 10, failure_probability: .1, expected_cost: 117,
    expected_failure_cost: 39, expected_intervention_cost: 78 };
  const snapshot = {
    config, source: { datasetId: pump.id, datasetName: pump.name, loadSignal: { name: 'pump', displayName: 'Pump', unit: '%' } },
    forecast: { status: 'ok', method: 'stochastic', model_version: '1.0.0', cutoff: 60, horizon: 20,
      history: [{ time: 0, value: .05, load: 55, fitted: null }, { time: 20, value: .10, load: 50, fitted: .11 },
        { time: 60, value: .3, load: 45, fitted: .31 }],
      trajectory: [{ time: 60, offset: 0, lower: .22, median: .31, upper: .39 },
        { time: 80, offset: 20, lower: .35, median: .44, upper: .53 }],
      distribution: [{ time: 0, probability: 0 }, { time: 10, probability: .1 }, { time: 20, probability: .75 }],
      rul: { median: 16, lower: 8, upper: null, confidence: .9,
        probability_not_reached_by_horizon: .25, probability_never_reached_under_model: .01,
        probabilities: [{ horizon: 20, probability: .75 }] },
      diagnostics: { operating_periods: [[20, 60]], latest_maintenance: { time: 20, action: 'restore' } },
      assumptions: ['A fixed operating regime'], assumption_keys: ['elapsed_time'] },
    maintenance: { status: 'ok', horizon: 20, recommended: scheduled, options: [scheduled], curve: [scheduled], assumptions: [] },
  };
  const session = { ...snapshot, id: 'pump-session', name: 'Pump forecast', created_at: '2026-10-24T00:00:00Z' };
  const writes = [];
  let delaySave = false, finishSave;
  globalThis.fetch = async (url, options = {}) => {
    if (options.body) writes.push({ url, body: JSON.parse(options.body) });
    if (url === base + '/benchmark') return response({ dataset: pump, defaults: config });
    if (url === base + '/fit') return response(snapshot);
    if (url === base + '/sessions' && options.method === 'POST') {
      if (delaySave) return new Promise(resolve => { finishSave = () => resolve(response(session)); });
      return response(session);
    }
    if (url === base + '/sessions') return response({ sessions: [{ ...session, assetName: 'Pump 1', status: 'ok' }] });
    if (url === base + '/sessions/pump-session') return response(session);
    if (url === '/api/workspaces/test/incidents' && options.method === 'POST') return response(emptyIncident());
    if (url === '/api/workspaces/test/incidents') return response({ incidents: [] });
    throw new Error(`Unexpected URL ${url}`);
  };
  let generated;
  await mount(React.createElement(PrognosticWorkspace, { workspaceId: 'test', datasets: [],
    benchmarkScenario: { id: 'tank-scenario', version: 2 }, onGenerated: data => { generated = data; },
  }));
  assert.match(container.textContent, /The selected coupled-tank scenario supplies the hydraulic settings/);
  await click(button('Generate pump dataset'));
  assert.equal(generated.id, pump.id);
  assert.deepEqual(writes[0].body, { scenarioId: 'tank-scenario', scenarioVersion: 2 });
  assert.equal(inputFor('Degradation signal').value, 'capacity_loss');
  await click(button('Fit model and compare strategies'));
  assert.equal(writes.find(item => item.url.endsWith('/fit')).body.cutoff, 60);
  assert.match(container.querySelector('#pm-rul').parentElement.parentElement.textContent, /16 s/);
  assert.match(container.textContent, /Restoration · 20 s/);
  assert.match(container.textContent, /20 – 60/);
  assert.ok(container.querySelector('.pm-workspace svg polygon'));
  await setField(inputFor('Shared chart cursor'), 3);
  assert.ok(container.querySelector('.pm-workspace svg [data-selected-time="70"]'));
  assert.ok(container.querySelector('.pm-workspace svg [data-selected-time="10"]'));
  assert.match(container.textContent, /No crossing by the forecast horizon/);
  assert.match(container.textContent, /Recorded operating load/);
  assert.match(container.textContent, /Expected total cost/);
  await setField(inputFor('Session name'), 'Pump forecast');
  await click(button('Save session'));
  assert.equal(window.location.hash, '#/workspaces/test/maintenance/pump-session');
  await act(async () => root.render(React.createElement(PrognosticWorkspace, {
    key: session.id, workspaceId: 'test', datasets: [pump], sessionId: session.id, onGenerated() {},
  })));
  assert.equal(inputFor('Forecast cutoff (dataset s)').value, '60');
  assert.equal(container.querySelector('a[href$="/forecast.csv"]').getAttribute('href'), base + '/sessions/pump-session/forecast.csv');
  await click(button('Link saved forecast to an incident'));
  await click(button("Create and open incident"));
  assert.deepEqual(writes.at(-1).body.source, { kind: 'prognostic', sessionId: session.id });
  delaySave = true;
  await click(button('Save as new session'));
  assert.ok(finishSave);
  await act(async () => root.render(React.createElement('div')));
  window.location.hash = '#/workspaces/test/datasets';
  await act(async () => finishSave());
  assert.equal(window.location.hash, '#/workspaces/test/datasets');
  window.location.hash = '#/';
});

test('sensor placement saves configured constraints, restores bilingual evidence and opens published signals', async () => {
  const { SensorPlacementWorkspace } = require('../src/workspace/modeling/SensorPlacementWorkspace.tsx');
  const endpoint = '/api/workspaces/pilot/sensor-placement';
  const model = { id: 'coupled-tanks', name: 'Coupled-Tank Process', version: '1.0.0' };
  const keys = ['level1', 'level2', 'inlet', 'transfer', 'outlet'];
  const sensors = keys.map((key, i) => ({ key, label: i === 0 ? 'Tank 1 measured level' : key, tag: 'sensor-' + i, unit: 'm' }));
  const hypotheses = ['healthy', 'pump_degradation', 'valve_restriction'];
  const config = { modelId: model.id, horizon: 12, step: .5, onset: 2, duration: null,
    sensors: keys.map(key => ({ key, noise: .01, cost: 1, mode: 'available' })),
    correlations: keys.map((_, i) => keys.map((__, j) => +(i === j))),
    hypotheses: hypotheses.slice(1), intensities: { pump_degradation: .3, valve_restriction: .3 },
    conditions: [{ id: 'nominal', parameters: {} }], budget: 4, maxSensors: 2, objective: 'separation', aggregation: 'worst' };
  const trajectories = hypotheses.map((_, j) => [keys.map(() => 0), keys.map(() => j)]);
  const scores = { separation: 0, detectability: 0, isolability: 2, information: 0 };
  const spectrum = { singularValues: [3, 0], rank: 1, condition: null, tolerance: 1e-14 };
  const evidence = { ...scores, spectrum, signatureSpectrum: spectrum, sensitivityNorms: [[1], [0]],
    distances: [[0, 0, 2], [0, 0, 2], [2, 2, 0]] };
  const subset = { sensors: ['level1'], cost: 1, pareto: true, nominal: scores, mean: scores, worst: scores,
    conditions: [evidence] };
  const metadata = { id: 'saved', name: 'Study A', created_at: '2026-11-14T01:23:45Z' };
  const cohort = { id: 'holdout_timing', trialsPerHypothesis: 3, falseAlarmRate: 0, detectionRate: .5,
    classificationAccuracy: 0, ambiguousRate: .5, unclassifiedRate: 1, trueMinimumSeparation: 0,
    counts: [[3,0,0,0], [3,0,0,0], [0,0,0,3]], pairwise: [] };
  const cancellation = { id: 'cancellation_nominal', templates: trajectories, pumpIntensity: .3,
    valveIntensity: .3, noiseScale: 1, metrics: [{ sensors: ['level1'], detectability: 0, isolability: 2,
      competitor: 'pump_degradation', detectionPower: .05, nearestPairError: .16 }] };
  const analysis = { config, hypotheses, sensors, parameters: hypotheses.slice(1), runtimeMs: 10, weakDistance: 2,
    conditions: [{ id: 'nominal', times: [0, 2], templates: trajectories, signatures: trajectories,
      derivativeStability: hypotheses.slice(1).map(fault => ({ fault, relativeL2: keys.map(() => 0) })) }],
    subsets: [subset], winners: { nominal: subset.sensors, mean: subset.sensors, worst: subset.sensors },
    cancellation: { times: [0,2], templates: trajectories, hypotheses, tank1Rms: [.03,.03,0], cases: [cancellation] },
    evaluation: { calibrationSeed: 1, holdoutSeed: 2, targetFalseAlarm: .05, chosenLayout: 'minimax_optimum',
      cohorts: [{ id: cohort.id, model: { start: 2 }, representative: trajectories }],
      layouts: [{ id: 'minimax_optimum', sensors: subset.sensors, cost: 1, minimumSeparation: 0, runtimeMs: 1, cohorts: [cohort] }] } };
  const posts = [];
  globalThis.fetch = async (url, options) => {
    if (options.method === 'POST') {
      const payload = JSON.parse(options.body);
      posts.push([url, payload]);
      if (url.endsWith('/dataset')) return response({ metadata: { columns: [{ id: 'catalog-signal' }] } });
      return response({ ...metadata, analysis: { ...analysis, config: payload.config } });
    }
    if (url === endpoint) return response({ runs: [metadata], defaults: config, conditions: ['nominal'],
      modelFields: [], models: [model], sensors });
    if (url === endpoint + '/saved') return response({ ...metadata, analysis });
    throw new Error('Unexpected request ' + url);
  };
  const changes = [];
  const render = runId => React.createElement(SensorPlacementWorkspace, { workspaceId: 'pilot', runId, onChanged: () => changes.push(true) });
  window.location.hash = '#/workspaces/pilot/sensor-placement';
  await mount(render());
  const select = container.querySelector('select[aria-label="Tank 1 measured level · Sensor status"]');
  await act(async () => {
    select.value = 'required';
    select.dispatchEvent(new window.Event('change', { bubbles: true }));
    const name = container.querySelector('input[maxlength="160"]');
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(name, 'Study A');
    name.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
  await act(async () => container.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })));
  assert.equal(posts[0][1].config.sensors[0].mode, 'required');
  assert.equal(window.location.hash, '#/workspaces/pilot/sensor-placement/saved');
  await act(async () => root.render(render('saved')));
  assert.match(container.textContent, /Indistinguishable/);
  assert.ok(container.querySelector('a[href$="/analysis.json"]'));
  assert.ok(container.querySelector('svg[aria-label^="Tank 1 measured level"]'));
  assert.match(container.textContent, /Fault detectability and sensor placement/);
  assert.ok(container.querySelector('a[href*="report.html"]'));
  await click([...container.querySelectorAll('button')].find(button => button.textContent === "Publish trajectory to Signal Explorer"));
  assert.deepEqual(posts[1][1], { condition: 'nominal', hypothesis: 'pump_degradation', sensors: ['level1'] });
  assert.equal(changes.length, 1);
  assert.equal(window.location.hash, '#/workspaces/pilot/explorer/catalog-signal');
});

test('input design reopens a saved experiment, localizes controls and publishes the selected strategy', async () => {
  const { ExperimentDesign } = require('../src/workspace/modeling/ExperimentDesign.tsx');
  const config = {
    modelId: 'coupled-tanks', duration: 2, controlInterval: 1, segments: 2, sampleInterval: 1,
    integrationStep: .25, seed: 1, objective: 'E', initialLevels: [1.56, 1],
    levelMin: [0, 0], levelMax: [2.4, 2.4], tankHeight: 2.5, minDelivery: 0, terminalLevelTolerance: null,
    initialInput: [100, 1], terminalInput: null, inputMin: [45, .45], inputMax: [150, 1],
    maxMovement: [280, 2], maxSlew: [10, .075], parameters: ['pumpRate'], noise: { level1: .004 },
    nominal: { pumpRate: .03 }, scenarios: [{ pumpRate: .035 }],
  };
  const report = {
    parameters: config.nominal, objective: 4, rank: 1, singularValues: [2], eigenvalues: [4],
    logDet: Math.log(4), condition: 1, matrix: [[4]], physicalMatrix: [[4444]], correlation: [[1]],
    weakDirections: [[1]], rankThreshold: 1e-7, differenceDisagreement: 1e-8, sensitivity: [[[0]], [[.02]], [[.03]]],
    structurallyAbsent: [], times: [0, 1, 2], response: { level1: [1.56, 1.56, 1.58], level2: [1, 1, 1] },
    observations: { level1: [1.56, 1.56, 1.58] }, sampledInputs: { pump: [100, 110, 110], valve: [1, 1, 1] },
    margins: { levelUpper: [.8, 1.4] }, feasible: true, delivered: .06, spilled: 0, massResidual: 1e-16,
    extrema: { minAt: [0, 0], maxAt: [2, 0], substeps: 16 },
  };
  const strategy = {
    id: 'nominal-optimal', schedule: [{ start: 0, pump: 100, valve: 1 }, { start: 1, pump: 110, valve: 1 }],
    duration: 2, movement: [10, 0], maxSlew: [10, 0], inputMargins: { slew: [0, .075] },
    inputFeasible: true, feasible: true, reports: { nominal: report, 'scenario-1': { ...report, feasible: false } },
    worstScenario: 'scenario-1', worstObjective: 3, violatedScenarios: ['scenario-1'],
  };
  const summary = { id: 'design-1', name: 'Fixture', created_at: '2026-01-01T00:00:00Z', status: 'completed' };
  const record = { ...summary, snapshot: { config, designs: [strategy], solvers: {},
    diagnostics: { dRidge: 1e-6, stateIntegrationStep: .125, feasibilityTolerance: 1e-6 } } };
  const requests = [];
  let publications = 0;
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    if (url.endsWith('/datasets')) return response(dataset('generated'));
    if (url.endsWith('/design-1')) return response(record);
    return response({ defaults: config, experiments: [summary], parameters: {
      pumpRate: { label: 'Nominal pump flow', unit: 'm³/s', min: 0, max: .2 },
    }, measurements: { level1: { label: 'Tank 1 measured level', unit: 'm' }, level2: { label: 'Tank 2 measured level', unit: 'm' } } });
  };
  await mount(React.createElement(ExperimentDesign, { workspaceId: 'test', experimentId: 'design-1', onPublished: () => publications++ }));
  assert.match(container.textContent, /Optimal Experiment Design/);
  assert.match(container.textContent, /Fisher information/);
  const scenarios = [...container.querySelectorAll('select')].find(node => node.value === 'nominal');
  await act(async () => {
    scenarios.value = 'scenario-1';
    scenarios.dispatchEvent(new window.Event('change', { bubbles: true }));
  });
  assert.match(container.textContent, /Violates simulated constraints/);
  await click([...container.querySelectorAll('button')].find(node => node.textContent === "Publish as Dataset"));
  assert.equal(publications, 1);
  assert.deepEqual(JSON.parse(requests.at(-1).options.body), { designId: 'nominal-optimal', scenarioId: 'scenario-1' });
  assert.ok(container.querySelector('a[href="#/workspaces/test/datasets/generated"]'));
});

test('reachability computes a map, replays a selected state, reopens its snapshot and exports an ordinary Dataset', async () => {
  const config = { modelId: 'coupled-tanks', plant: { area1: 1, area2: 1, connection: .04, outlet: .03, pumpRate: .03, outletValve: 1, tankHeight: 2.5 },
    safe: [[.3, 2.35], [.25, 2.35]], target: [[1.4, 1.8], [.85, 1.15]], pump: [0, 150], valve: [.2, 1],
    slew: [6, .05], actionCounts: [4, 3], grid: [3, 3], horizon: 16, controlSeconds: 10, integrationStep: .1, mode: 'nominal', disturbances: ['pump-loss'] };
  const analysis = { config, modelVersion: '1.0.0', numerical: { axes: [[0, 1.2, 2.4], [0, 1.2, 2.4]], spacing: [1.2, 1.2],
    actions: [[50, 1], [100, 1]], scenarios: { nominal: {} }, horizonSeconds: 160, viabilityIterations: 2,
    nominalViabilityIterations: 2, convergence: true, seconds: .06, graphBytes: 64, safeAugmentedStates: 8, boundaryAugmentedStates: 6 },
    safe: Array(9).fill(true), target: Array(9).fill(false), ranks: Array(9).fill([1, 2]),
    policy: Array(9).fill([0, 0]), viable: Array(9).fill([true, true]), boundary: Array(9).fill([true, true]) };
  analysis.nominalRanks = analysis.viableTargetRanks = analysis.ranks;
  analysis.nominalViable = analysis.viable;
  const rootPath = '/api/workspaces/test/reachability';
  const data = dataset('recovered-data', 20);
  const calls = [];
  let saved;
  window.location.hash = '#/workspaces/test/reachability';
  globalThis.fetch = async (url, options) => {
    const body = options?.body ? JSON.parse(options.body) : null;
    calls.push([url, body]);
    if (url === '/api/workspaces') return response({ workspaces: [{ id: 'test', name: 'Tanks' }] });
    if (url === '/api/workspaces/test') return response({ id: 'test', name: 'Tanks' });
    if (url.endsWith('/datasets')) return response({ datasets: [] });
    if (url.endsWith('/analyses')) return response({ jobs: [] });
    if (url === rootPath && !body) return response({
      studies: saved ? [saved] : [], defaults: config, disturbances: { nominal: {}, 'pump-loss': { pump: .85 } }, scenarios: [], incidents: [],
    });
    if (url === rootPath + '/saved') return response(saved);
    if (url === rootPath + '/saved/dataset') return response(data);
    if (url === rootPath || url === rootPath + '/compute') {
      const evaluation = body.initial ? { initial: body.initial, integrationStep: .05,
        replays: Object.fromEntries(['policy', 'hold', 'drain', 'fill'].map(strategy => [strategy, {
          strategy, status: 'recovered', recoverySeconds: 10, effort: [500, 10], movement: [50, 0],
          minimumMargin: .1, violations: [], actions: [{ t: 0, pump: 50, valve: 1, disturbance: 'nominal' }],
          trajectory: [{ t: 0, level1: body.initial.heads[0], level2: body.initial.heads[1], pump: 50, valve: 1, safetyMargin: .1 },
            { t: 10, level1: 1.55, level2: 1.05, pump: 50, valve: 1, safetyMargin: .2 }],
        }])) } : null;
      const result = { analysis, evaluation, scenario: null, incident: null };
      if (url === rootPath) saved = { ...result, id: 'saved', name: body.name };
      return response(url === rootPath ? saved : result);
    }
    throw new Error('Unexpected reachability request ' + url);
  };
  await mount(React.createElement(App));
  assert.equal(container.querySelector('a[href="#/workspaces/test/reachability"]').getAttribute('aria-current'), 'page');
  await click(button('reach.compute'));
  const map = container.querySelector('svg[aria-label="Tank state map"]');
  assert.ok(map);
  await act(async () => map.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true })));
  await click(button('reach.simulate'));
  const simulation = calls.filter(([url]) => url.endsWith('/compute')).at(-1)[1].initial;
  assert.deepEqual(simulation, { heads: [1.2, 1.2], previousAction: 1, disturbance: 'nominal' });
  assert.ok(container.querySelector('.reach-map polyline'));
  assert.match(container.textContent, /Nonlinear replay comparison/);
  await click(button('reach.save'));
  await act(async () => window.dispatchEvent(new window.HashChangeEvent('hashchange')));
  assert.equal(window.location.hash, '#/workspaces/test/reachability/saved');
  assert.ok(calls.some(([url]) => url === rootPath + '/saved'));
  await click(button('reach.exportDataset'));
  assert.ok(container.querySelector('a[href="#/workspaces/test/datasets/recovered-data"]'));
  assert.ok(container.querySelector('a[href="#/workspaces/test/experiments/new/recovered-data"]'));
  assert.match(container.textContent, /Safety Reachability & Recovery Planning/);
  assert.match(container.textContent, /Nonlinear replay comparison/);
});
