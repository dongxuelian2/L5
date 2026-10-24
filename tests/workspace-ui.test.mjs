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
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
      fileName: filename,
    });
    module._compile(outputText, filename);
  };
}
require.extensions['.css'] = module => module._compile('', module.filename);
const dom = new JSDOM('<!doctype html><body></body>', { url: 'http://localhost/', pretendToBeVisual: true });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.Element = dom.window.Element;
globalThis.SVGElement = dom.window.SVGElement;
globalThis.requestAnimationFrame = dom.window.requestAnimationFrame.bind(dom.window);
globalThis.cancelAnimationFrame = dom.window.cancelAnimationFrame.bind(dom.window);
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.HTMLElement.prototype.scrollIntoView = function () {};
dom.window.matchMedia = () => ({ matches: true, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
const { createRoot } = await import('react-dom/client');
const { SignalPlots } = require('../src/workspace/Charts.tsx');
const { ResultView } = require('../src/workspace/Results.tsx');
const { ImportDataset } = require('../src/workspace/WorkspaceApp.tsx');
const { RuntimeWorkbench } = require('../src/workspace/RuntimeWorkbench.tsx');
const { IncidentsPage, IncidentDetail } = require('../src/workspace/Incidents.tsx');

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
function button(text) { return [...container.querySelectorAll('button')].find(node=>node.textContent.startsWith(text)); }
async function setField(node,value) {
  assert.ok(node);
  await act(async()=>{
    const prototype = node.tagName === 'SELECT' ? dom.window.HTMLSelectElement.prototype : node.tagName === 'TEXTAREA' ? dom.window.HTMLTextAreaElement.prototype : dom.window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype,'value').set.call(node,String(value));
    node.dispatchEvent(new dom.window.Event(node.tagName === 'SELECT' ? 'change' : 'input',{bubbles:true}));
  });
}
function isMasked(node) { return Boolean(node?.closest('[aria-hidden="true"][inert]')); }
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
  const element = [...dialog.querySelectorAll('label')].find(n => n.textContent.startsWith(label));
  assert.ok(element, `dialog field ${label} exists`); return element.querySelector('input,textarea,select');
}
function inputFor(label, within = container) {
  const element = [...within.querySelectorAll('label')].find(n => n.textContent.startsWith(label));
  assert.ok(element, `field ${label} exists`); return element.querySelector('input,textarea,select');
}

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
  await click([...card.querySelectorAll('button')].find(n => n.textContent === '创建事件'));
  assert.equal(dialogField('开始时间').value, String(cardStart));
  await setField(dialogField('事件标题'), '用户确认的事件');
  await setField(dialogField('开始时间'), 320);
  await setField(dialogField('事件说明'), '等待现场复核');
  await click(button('创建并打开事件'));
  assert.equal(writes[0].url, '/api/workspaces/test/incidents');
  assert.equal(writes[0].body.title, '用户确认的事件');
  assert.equal(writes[0].body.start_time, 320);
  assert.equal(writes[0].body.description, '等待现场复核');
  assert.deepEqual(writes[0].body.source, { kind: 'interval', analysisId: result.id, datasetId: 'incident-data', intervalIndex: result.intervals.findIndex(i => i.start === cardStart) });
  assert.equal(window.location.hash, '#/workspaces/test/incidents/event-one');
  const row = container.querySelector('tbody tr');
  await click([...row.querySelectorAll('button')].find(n => n.textContent === '添加到已有事件'));
  assert.equal(dialogField('选择事件').value, saved.id);
  await click(button('添加并打开事件'));
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
  assert.match([...container.querySelectorAll('a')].find(a => a.textContent === '打开原始分析 ↗').getAttribute('href'), /incident-detail-analysis\/0$/);
  await click(button('＋ 添加候选解释'));
  await setField(dialogField('记录标题'), '冷却侧变化');
  await setField(dialogField('记录内容'), '先核对冷却回路');
  await click(button('保存调查记录'));
  await click(button('＋ 添加证据'));
  await setField(dialogField('记录标题'), '温度首先升高');
  await setField(dialogField('记录内容'), '温度在区间开始前已偏离。');
  await setField(dialogField('关联候选解释'), 'entry-1');
  await setField(dialogField('证据关系'), 'support');
  await setField(dialogField('观察时间'), 345);
  await click(button('保存调查记录'));
  const evidence = saved.entries.find(e => e.kind === 'evidence');
  assert.equal(evidence.hypothesis_id, 'entry-1'); assert.equal(evidence.stance, 'support');
  assert.equal(evidence.source_link_id, 'source-one'); assert.equal(evidence.observed_at, 345);
  await click(button('＋ 添加笔记'));
  await setField(dialogField('记录标题'), '现场复核'); await setField(dialogField('记录内容'), '已检查交接记录。');
  await click(button('保存调查记录'));
  const noteCard = [...container.querySelectorAll('article')].find(a => a.textContent.includes('现场复核'));
  await click([...noteCard.querySelectorAll('button')].find(b => b.textContent === '编辑'));
  await setField(dialogField('记录内容'), '已检查交接记录，等待冷却水记录。');
  await click(button('保存调查记录'));
  await setField(inputFor('事件标题'), '反应器持续调查');
  await setField(inputFor('调查状态'), 'investigating');
  await click(button('保存基本信息'));
  await setField(inputFor('调查结论'), '暂时支持冷却侧变化，继续验证。');
  await click(button('保存调查结论'));
  assert.ok(writes.some(w => w.method === 'PATCH' && w.body.conclusion === '暂时支持冷却侧变化，继续验证。'));
  await act(async () => root.unmount()); container.remove(); root = null;
  await mount(React.createElement(IncidentsPage, { workspaceId: 'test', incidentId: saved.id, datasets: [data], jobs: [] }));
  assert.equal(inputFor('事件标题').value, '反应器持续调查');
  assert.equal(inputFor('调查结论').value, saved.conclusion);
  assert.match(container.textContent, /等待冷却水记录/);
  assert.match(container.textContent, /支持：冷却侧变化/);
  assert.ok(curve(names[0]));
});

test('incident list filters by status, title and time using the workspace API', async () => {
  const requests = [], incident = { ...emptyIncident(), analysis_count: 2, interval_count: 3 };
  globalThis.fetch = async url => { requests.push(url); return response({ incidents: [incident] }); };
  await mount(React.createElement(IncidentsPage, { workspaceId: 'test', datasets: [], jobs: [] }));
  await act(async () => new Promise(resolve => setTimeout(resolve, 220)));
  assert.match(container.textContent, /2 个分析 · 3 个区间/);
  await setField(inputFor('调查状态'), 'investigating');
  await setField(inputFor('查找事件'), '反应器');
  await setField(inputFor('相交区间起点'), 300);
  await setField(inputFor('相交区间终点'), 600);
  await act(async () => new Promise(resolve => setTimeout(resolve, 220)));
  const query = new URL(requests.at(-1), 'http://localhost').searchParams;
  assert.equal(query.get('status'), 'investigating'); assert.equal(query.get('q'), '反应器');
  assert.equal(query.get('start'), '300'); assert.equal(query.get('end'), '600');
  assert.equal(container.querySelector('.ws-history-row').getAttribute('href'), '#/workspaces/test/incidents/event-one');
});

test('saved runtime experiment reopens its observation and intervention parameters and links to an incident', async () => {
  const api = runtimeAPI(), delegate = globalThis.fetch;
  const savedBody = { asOf: 156, windowStart: 0, hypothesis: 'cooling_valve', mode: 'known', at: 162, horizon: 400, actions: ['bypass'], parameters: { bypassFlow: 63 } };
  const run = { id: 'saved-trial', kind: 'intervention', request: savedBody, result: forecastFor(savedBody), createdAt: '2026-10-24T00:00:00Z' }, writes = [];
  globalThis.fetch = async (url, options = {}) => {
    if (url === '/api/simulations?workspaceId=test') return response({ simulations: [{ ...simulation('A'), workspaceId: 'test' }] });
    if (url === '/api/simulations/A/runs') return response({ runs: [run] });
    if (url === '/api/workspaces/test/incidents') return response({ incidents: [emptyIncident()] });
    if (url === '/api/incidents/event-one/links') { writes.push(JSON.parse(options.body)); return response(emptyIncident()); }
    return delegate(url, options);
  };
  await mount(React.createElement(RuntimeWorkbench, { workspaceId: 'test', simulationId: 'A', runId: run.id }));
  await debounceAnalysis(); await resolveAnalysis(api.analyses.at(-1));
  assert.equal(field('Observe through').value, '156'); assert.equal(field('Intervention starts at').value, '162');
  assert.equal(field('Prediction ends at').value, '400'); assert.equal(field('Bypass cooling flow').value, '63');
  assert.ok(container.querySelector('.runtime-forecast'), 'stored forecast opens without recomputation');
  await click(button('关联最近一次已完成结果'));
  await click([...container.querySelectorAll('dialog button')].find(b => b.textContent === '添加到已有事件'));
  await click(button('添加并打开事件'));
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
  const analyses = results.map(r => ({ id: r.id, result: r, datasetId: r.datasetId, datasetName: '现场数据', axisId, offset: 0, scope: '完整分析', linkId: `link-${r.id}`, observedSpans: [[200, 699]],
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
  await setField(inputFor('分析结果', timeline), pca.id);
  assert.equal(timeline.querySelectorAll('.incident-event-list li').length, 2);
  await setField(inputFor('筛选起点', timeline), 500);
  assert.equal(timeline.querySelectorAll('.incident-event-list li').length, 1);
  await click(timeline.querySelector('.incident-event-list button'));
  assert.ok(Number(inputFor('窗口起点').value) < 510);
  assert.ok(Number(inputFor('窗口终点').value) > 554);
  assert.equal(inputFor('观察时刻（来源秒数）').value, '520');
  assert.ok(container.querySelector('.incident-preview svg [data-selected-time="520"]'));
  assert.match(container.querySelector('.incident-comparison-scores').textContent, /PCA 分析/);
  await setField(inputFor('同步观察时刻'), 530);
  assert.ok(container.querySelector('.incident-preview svg [data-selected-time="530"]'));
  assert.ok(container.querySelector('.incident-comparison-scores svg [data-selected-time="530"]'));
  await act(async () => new Promise(resolve => setTimeout(resolve, 130)));
  assert.match(container.querySelector('[aria-label="同一时刻的多变量观测"]').textContent, /30/);
  assert.ok(samples.some(url => url.includes('at=530')));
  await click(comparison.querySelector('.ws-option-grid input'));
  assert.match(queries.at(-1), /analysis=timeline-pca/);
  assert.equal(comparison.querySelectorAll('tbody')[0].rows.length, 1);
  await setField(inputFor('分析结果', timeline), ''); await setField(inputFor('筛选起点', timeline), ''); await setField(inputFor('事件类别', timeline), 'note');
  assert.equal(timeline.querySelectorAll('.incident-event-list li').length, 1);
  await click(timeline.querySelector('.incident-event-list button'));
  assert.equal(dialogField('记录标题').value, '现场温升记录');
  assert.equal(dialogField('观察时间').value, '345');
});

test('professional report preview/export uses current saved content and invalidates an older generation', async () => {
  const { IncidentReport } = require('../src/workspace/IncidentReport.tsx');
  let saved = emptyIncident(), reports = 0;
  globalThis.fetch = async url => {
    assert.match(url, /report\.html$/); reports++;
    return { ok: true, headers: { get: () => 'text/html; charset=utf-8' }, text: async () => `<!doctype html><html><body><h1>真实事件报告</h1><p>${saved.conclusion || '尚未形成结论'}</p><svg><path d="M0 0 L1 2"/></svg></body></html>` };
  };
  await mount(React.createElement(IncidentReport, { incident: saved }));
  assert.equal(button('导出离线 HTML').disabled, true);
  await click(button('生成报告'));
  assert.match(container.querySelector('iframe').getAttribute('srcdoc'), /尚未形成结论/);
  let printed = 0;
  const frame = container.querySelector('iframe');
  frame.contentWindow.print = () => printed++;
  frame.contentWindow.focus = () => {};
  await act(async () => frame.dispatchEvent(new window.Event('load')));
  await click(button('打印 / 保存 PDF'));
  assert.equal(printed, 1);
  const originalCreate = URL.createObjectURL, originalRevoke = URL.revokeObjectURL, originalClick = window.HTMLAnchorElement.prototype.click;
  let blob, filename;
  URL.createObjectURL = value => { blob = value; return 'blob:test-report'; };
  URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function () { filename = this.download; };
  try {
    await click(button('导出离线 HTML'));
    assert.match(filename, /l5-incident-event-one\.html/);
    assert.match(await blob.text(), /<svg>/);
  } finally { URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke; window.HTMLAnchorElement.prototype.click = originalClick; }
  saved = { ...saved, conclusion: '更新后的现场结论', updated_at: '2026-10-24T03:00:00Z' };
  await act(async () => root.render(React.createElement(IncidentReport, { incident: saved })));
  assert.equal(container.querySelector('iframe'), null);
  assert.equal(button('打印 / 保存 PDF').disabled, true);
  await click(button('生成报告'));
  assert.match(container.querySelector('iframe').getAttribute('srcdoc'), /更新后的现场结论/);
  assert.equal(reports, 2);
});

test('timeline experiment links reopen the stored run rather than the current cursor window', async () => {
  const { IncidentTimeline } = require('../src/workspace/IncidentTimeline.tsx');
  const saved = emptyIncident();
  saved.links = [{ id: 'trial-link', kind: 'run', details: { title: '保存实验', simulationId: 'sim-one', run: { id: 'trial-one', request: { asOf: 93, windowStart: 0 }, kind: 'intervention' } } }];
  const view = { ...incidentView(saved, []), axes: [{ id: 'simulation:sim-one', label: '冷却模拟', start: 0, end: 100, origin: null }], primaryAxisId: 'simulation:sim-one', events: [{ id: 'trial-event', kind: 'experiment', title: '干预实验', start: 93, end: 93, axisId: 'simulation:sim-one', linkId: 'trial-link', observationWindow: [0, 93], actionAt: 96, recordedAt: saved.created_at, target: 'source' }] };
  globalThis.fetch = async () => response(view);
  let selected;
  await mount(React.createElement(IncidentTimeline, { incident: saved, selection: null, onSelect: value => selected = value, onRecord() {}, onSection() {} }));
  await click(container.querySelector('.incident-event-list button'));
  assert.equal(selected.at, 93); assert.equal(selected.linkId, 'trial-link');
  assert.equal(container.querySelector('.incident-event-list a').getAttribute('href'), '#/workspaces/test/simulations/sim-one/trial-one');
});

test('removing an analysis source reconciles the incident comparison selection without stale source requests', async () => {
  const { IncidentTimeline } = require('../src/workspace/IncidentTimeline.tsx');
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
  const { IncidentReport } = require('../src/workspace/IncidentReport.tsx');
  let resolveOld;
  globalThis.fetch = () => new Promise(resolve => resolveOld = resolve);
  let saved = emptyIncident();
  await mount(React.createElement(IncidentReport, { incident: saved }));
  await click(button('生成报告'));
  saved = { ...saved, conclusion: '最新结论' };
  await act(async () => root.render(React.createElement(IncidentReport, { incident: saved })));
  globalThis.fetch = async () => ({ ok: true, headers: { get: () => 'text/html' }, text: async () => '<html><body>最新结论</body></html>' });
  await click(button('生成报告'));
  await act(async () => resolveOld({ ok: true, headers: { get: () => 'text/html' }, text: async () => '<html><body>旧结论</body></html>' }));
  assert.match(container.querySelector('iframe').getAttribute('srcdoc'), /最新结论/);
  assert.doesNotMatch(container.querySelector('iframe').getAttribute('srcdoc'), /旧结论/);
});
