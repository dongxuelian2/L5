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
    const prototype = node.tagName === 'SELECT' ? dom.window.HTMLSelectElement.prototype : dom.window.HTMLInputElement.prototype;
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
