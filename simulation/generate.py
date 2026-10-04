"""Reproducible, reduced-order demo model. Python standard library only.

This is an illustrative process, not the Tennessee Eastman simulator. The
equations and thresholds are chosen for a legible demonstration, not control.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

DURATION = 300
FAULT_TIME = 30
TAGS = [
    {"key": "valve", "tag": "CV-101", "name": "Cooling valve", "unit": "%", "baseline": 62, "precision": 1, "color": "mint", "chain": "cooling"},
    {"key": "flow", "tag": "FI-101", "name": "Cooling water flow", "unit": "%", "baseline": 100, "precision": 1, "color": "mint", "chain": "cooling"},
    {"key": "temperature", "tag": "TI-101", "name": "Reactor temperature", "unit": "°C", "baseline": 120, "precision": 1, "color": "amber", "chain": "thermal"},
    {"key": "pressure", "tag": "PI-101", "name": "Reactor pressure", "unit": "kPa", "baseline": 2700, "precision": 0, "color": "coral", "chain": "thermal"},
    {"key": "separator", "tag": "PI-201", "name": "Separator pressure", "unit": "kPa", "baseline": 2630, "precision": 0, "color": "violet", "chain": "downstream"},
    {"key": "purity", "tag": "AI-301", "name": "Product purity", "unit": "%", "baseline": 99.2, "precision": 2, "color": "violet", "chain": "downstream"},
]
EDGES = [("valve", "flow"), ("flow", "temperature"), ("temperature", "pressure"), ("pressure", "separator"), ("separator", "purity")]


def correlation(a: list[float], b: list[float]) -> float:
    ma, mb = statistics.mean(a), statistics.mean(b)
    covariance = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    denominator = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return round(covariance / denominator, 4) if denominator else 0.


def compute_diagnostics(points: list[dict], detections: dict) -> dict:
    keys = [t['key'] for t in TAGS]
    # Correlation is descriptive, never treated as proof of causation.
    matrix = [[correlation([p[a] for p in points], [p[b] for p in points]) for b in keys] for a in keys]
    paths = []
    for source, target in EDGES:
        lag = detections[target]['time'] - detections[source]['time']
        paths.append({"source": source, "target": target, "lag": lag, "correlation": correlation([p[source] for p in points[:-lag]], [p[target] for p in points[lag:]]), "ordered": lag > 0})
    streams = []
    cumulative = {key: 0. for key in keys}
    for point in points:
        entry = {"t": point['t'], "signals": {}}
        for key in keys:
            d = detections[key]
            z = (point[key] - d['median']) / max(1.4826 * d['mad'], .001)
            cumulative[key] = max(0., cumulative[key] + abs(z) - 3.)
            entry['signals'][key] = {"z": round(z, 2), "cusum": round(cumulative[key], 2), "delta": round(point[key] - points[max(0, point['t'] - 1)][key], 4)}
        streams.append(entry)
    ranking = {}
    signatures = {
        'valve': {'valve': -1, 'flow': -1, 'temperature': 1, 'pressure': 1, 'separator': 1, 'purity': -1},
        'feed': {'temperature': 1, 'pressure': 1, 'separator': 1, 'purity': -1},
        'sensor': {'pressure': 1},
    }
    for cid, signature in signatures.items():
        covered = list(signature)
        direction = sum(signature[key] * (statistics.mean(p[key] for p in points[-30:]) - detections[key]['median']) > 0 for key in covered) / len(covered)
        coverage = len(covered) / len(keys)
        supported_edges = sum(a in covered and b in covered and detections[a]['time'] < detections[b]['time'] for a, b in EDGES)
        temporal = supported_edges / len(EDGES)
        unexplained = len(keys) - len(covered)
        # Explicit engineering hypothesis signatures, with no learned prior.
        parts = {"direction": round(40 * direction, 1), "coverage": round(35 * coverage, 1), "temporal": round(25 * temporal, 1), "unexplainedPenalty": 8 * unexplained, "missingFeedbackPenalty": 6}
        ranking[cid] = {"score": round(max(0, min(100, parts['direction'] + parts['coverage'] + parts['temporal'] - parts['unexplainedPenalty'] - 6))), "parts": parts, "explained": len(covered), "paths": supported_edges}
    return {"matrix": matrix, "paths": paths, "streams": streams, "ranking": ranking, "formula": "40·direction + 35·coverage + 25·ordered_paths − 8·unexplained − 6·missing_feedback"}


def simulate(intervention: int | None = None, fault: bool = True) -> list[dict]:
    """One-second forward Euler integration; identical prefix before branching.

    A stuck valve reduces cooling flow. Temperature follows a first-order
    energy balance; pressure and downstream vessels respond with delay.
    Intervention opens an independent bypass, with a small feed reduction.
    The failed valve itself remains stuck.
    """
    flow, temperature, pressure, separator, purity = 100., 120., 2700., 2630., 99.2
    points = []
    for t in range(DURATION + 1):
        failed = fault and t >= FAULT_TIME
        bypass = intervention is not None and t >= intervention
        valve = 22. if failed else 62.
        cooling_lost = fault and t >= FAULT_TIME + 5
        flow_target = 98. if bypass else 35.5 if cooling_lost else 100.
        flow += (flow_target - flow) / 10
        temp_target = 120 + .21 * (100 - flow) - (1.7 if bypass else 0)
        temperature += (temp_target - temperature) / 33
        pressure += (2700 + 35 * (temperature - 120) - pressure) / 24
        separator += (2630 + .58 * (pressure - 2700) - separator) / 27
        purity += (99.2 - .019 * (separator - 2630) - purity) / 35
        values = [valve, flow, temperature, pressure, separator, purity]
        amplitudes = [.09, .18, .04, .8, .6, .008]
        point = {"t": t}
        for i, (tag, value, amplitude) in enumerate(zip(TAGS, values, amplitudes)):
            # Deterministic sensor texture; same noise in both branches.
            point[tag["key"]] = round(value + amplitude * math.sin(t * .71 + i * 1.3), 4)
        points.append(point)
    return points


def detect(points: list[dict]) -> dict:
    """Median/MAD baseline, six robust sigmas, four consecutive samples."""
    detections = {}
    for tag in TAGS:
        key = tag["key"]
        baseline = [p[key] for p in points[:FAULT_TIME]]
        median = statistics.median(baseline)
        mad = statistics.median(abs(v - median) for v in baseline)
        scale = max(1.4826 * mad, .001)
        streak = 0
        for point in points[FAULT_TIME:]:
            z = abs(point[key] - median) / scale
            streak = streak + 1 if z > 6 else 0
            if streak >= 4:
                detections[key] = {"time": point["t"], "onset": point["t"] - 3, "z": round(z, 1), "median": round(median, 3), "mad": round(mad, 4)}
                break
    return detections


def alarms(points: list[dict]) -> list[dict]:
    # Reannunciation intervals deliberately create a synthetic alarm flood.
    rules = [
        ("flow", "L", 80, -1, 4), ("flow", "LL", 50, -1, 3),
        ("temperature", "H", 124, 1, 4), ("temperature", "HH", 129, 1, 3),
        ("pressure", "H", 2830, 1, 3), ("pressure", "HH", 2990, 1, 2),
        ("separator", "H", 2710, 1, 4), ("separator", "HH", 2800, 1, 3),
        ("purity", "L", 97.5, -1, 4), ("purity", "LL", 95.5, -1, 3),
    ]
    events, last = [], {}
    for point in points:
        for key, severity, threshold, direction, interval in rules:
            tag = next(tag for tag in TAGS if tag["key"] == key)
            rid = f'{tag["tag"]}:{severity}'
            if direction * (point[key] - threshold) > 0 and point["t"] - last.get(rid, -100) >= interval:
                events.append({"id": f"AL-{len(events) + 1:04}", "t": point["t"], "tag": tag["tag"], "key": key, "severity": severity, "value": round(point[key], tag["precision"]), "chain": tag["chain"], "message": f'{tag["name"]} {"high" if direction > 0 else "low"}{"-high" if severity == "HH" else "-low" if severity == "LL" else ""}', "repeat": rid in last})
                last[rid] = point["t"]
    return events


def build_scenario() -> dict:
    points = simulate()
    detections = detect(points)
    events = alarms(points)
    first_alarm = events[0]["t"]
    branches = []
    for time in [90, 120, 150]:
        branch = simulate(time)
        branches.append({"time": time, "points": branch, "alarms": len(alarms(branch)), "peakPressure": round(max(p["pressure"] for p in branch)), "finalPressure": round(branch[-1]["pressure"]), "trip": any(p["pressure"] >= 3050 for p in branch)})
    ordered_edges = sum(detections[a]["time"] < detections[b]["time"] for a, b in EDGES)
    checks = [
        {"name": "Deterministic replay", "passed": points == simulate(), "detail": "Same inputs → identical 301 samples"},
        {"name": "Identical branch prefix", "passed": all(b["points"][:b["time"]] == points[:b["time"]] for b in branches), "detail": "All 3 interventions share the observed initial state"},
        {"name": "Temporal path consistency", "passed": ordered_edges == len(EDGES), "detail": f"{ordered_edges}/{len(EDGES)} topology edges follow detection order"},
        {"name": "Normal-run false detections", "passed": not detect(simulate(fault=False)), "detail": "0 detections in one 300 s healthy fixture"},
        {"name": "Bypass lowers peak pressure", "passed": all(b["peakPressure"] < max(p["pressure"] for p in points) for b in branches), "detail": "Lower peak in each of 3 reduced-order branches"},
        {"name": "Alarm membership", "passed": sum(sum(e["chain"] == c for e in events) for c in ["cooling", "thermal", "downstream"]) == len(events), "detail": "Every raw event belongs to exactly one chain"},
    ]
    result = {
        "schemaVersion": 1,
        "id": "INC-001", "title": "Cooling-water valve sticking", "duration": DURATION, "faultTime": FAULT_TIME,
        "provenance": {"kind": "Illustrative simulation", "model": "TripLens reduced-order process v1", "source": "simulation/generate.py", "stepSeconds": 1, "isTEP": False, "analyst": "Scripted structured response · no model API"},
        "tags": TAGS, "edges": EDGES, "points": points, "detections": detections, "alarms": events, "branches": branches,
        "tripTime": next((p["t"] for p in points if p["pressure"] >= 3050), None),
        "firstAlarm": first_alarm, "leadTime": first_alarm - detections["valve"]["time"],
        "checks": checks,
        "chains": [
            {"id": "cooling", "name": "Cooling loss", "path": ["valve", "flow"], "color": "mint"},
            {"id": "thermal", "name": "Thermal escalation", "path": ["temperature", "pressure"], "color": "amber"},
            {"id": "downstream", "name": "Downstream upset", "path": ["separator", "purity"], "color": "violet"},
        ],
        "candidates": [
            {"id": "valve", "name": "Cooling-water valve sticking", "tag": "CV-101", "status": "Leading hypothesis", "support": "Valve position changes first. Cooling flow falls before temperature and pressure rise. All five downstream edges follow the observed detection order.", "against": "Valve command feedback is absent; mechanical sticking cannot be distinguished from an actuator fault.", "evidence": ["Temporal precedence", "5 connected downstream paths", "Cooling response consistent"]},
            {"id": "feed", "name": "Feed composition disturbance", "tag": "FEED-A", "status": "Alternative", "support": "A feed disturbance could explain rising reactor temperature and reduced product purity.", "against": "It does not explain the earlier valve-position and cooling-flow changes. Feed composition is not measured in this fixture.", "evidence": ["Thermal pattern compatible", "Early cooling loss unexplained"]},
            {"id": "sensor", "name": "Pressure sensor drift", "tag": "PI-101", "status": "Weak support", "support": "An isolated pressure rise could result from a drifting pressure instrument.", "against": "Independent temperature, flow, separator and purity channels also deviate, contradicting an isolated pressure measurement fault.", "evidence": ["Pressure deviation", "Independent channels contradict"]},
        ],
        "analyst": {
            "prompt": "Why is reactor pressure rising?",
            "steps": [
                {"action": "Inspect the first deviation", "tool": "inspect_signals", "result": f'CV-101 deviation confirmed at +{detections["valve"]["time"]}s; pressure follows at +{detections["pressure"]["time"]}s.'},
                {"action": "Trace the upstream path", "tool": "trace_topology", "result": "CV-101 → FI-101 → TI-101 → PI-101. Temporal order matches all 3 edges."},
                {"action": "Compare alternative causes", "tool": "read_candidates", "result": "Feed disturbance cannot explain early cooling loss. Sensor drift contradicts independent channels."},
                {"action": "Assemble the incident brief", "tool": "format_evidence", "result": "Cooling failure is the leading hypothesis. Test an independent bypass in the reduced-order model."},
            ],
            "summary": "The pressure rise is a downstream symptom. Cooling flow drops after CV-101 changes position, then reactor temperature rises before pressure. This sequence supports a cooling-loop fault as the initiating event.",
            "limitation": "Mechanical sticking is the scenario label; the observed signals alone do not rule out an actuator fault. Ranking scores are authored evidence scores, not calibrated probabilities.",
        },
    }
    result['diagnostics'] = compute_diagnostics(points, detections)
    for candidate in result['candidates']:
        candidate['score'] = result['diagnostics']['ranking'][candidate['id']]['score']
    result['analyst']['limitation'] = "Mechanical sticking is the scenario label; the observed signals alone do not rule out an actuator fault. Scores use explicit topology and coverage rules, not calibrated probabilities."
    return result


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[1] / "src/data/scenario.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    scenario = build_scenario()
    destination.write_text(json.dumps(scenario, ensure_ascii=False, indent=2) + "\n")
    print(f'Generated {destination.name}: {len(scenario["points"])} samples, {len(scenario["alarms"])} alarms, {len(scenario["branches"])} branches')
    print(f'Detections: {scenario["detections"]}')
    print(f'Trip: {scenario["tripTime"]}s. Branch peaks: {[b["peakPressure"] for b in scenario["branches"]]} kPa')
