"""Causal two-state tank EKF. No simulator, dataset repository or truth input.

Q is a continuous level-disturbance spectral density (m²/s); R and P0 are
level covariances (m²). Controls are right-continuous zero-order holds.
The discrete Jacobian differentiates the actual donor-limited SSPRK2 map.
"""
from __future__ import annotations

import math
import numpy as np

from .models.base import finite
from .models.tanks import CoupledTankModel, flows, hydraulic_step

STATES = ('level1', 'level2')
MODEL_KEYS = ('area1', 'area2', 'connection', 'outlet', 'pumpRate',
              'pumpControl', 'valve', 'outletValve', 'tankHeight')
FILTER_DEFAULTS = dict(initialState=[1.2, .7], initialCovariance=[[.16, 0], [0, .16]],
                       processCovariance=[[1e-6, 0], [0, 1e-6]],
                       measurementCovariance=[[.0004, 0], [0, .0004]],
                       initialTime=0., maxStep=.1, jacobianStep=1e-5)


def matrix(value, name, *, positive=False):
    a = np.asarray(value, dtype=float)
    if a.shape != (2, 2) or not np.isfinite(a).all() or not np.allclose(a, a.T, rtol=0, atol=1e-12):
        raise ValueError(f'{name} must be a finite symmetric 2 by 2 covariance.')
    eigenvalues = np.linalg.eigvalsh(a)
    if eigenvalues[0] < 0 or (positive and eigenvalues[0] <= 0):
        raise ValueError(f'{name} must be positive {"definite" if positive else "semidefinite"}.')
    return a


def settings(raw=None):
    raw = {} if raw is None else raw
    if not isinstance(raw, dict) or set(raw)-FILTER_DEFAULTS.keys():
        raise ValueError('Unknown estimator settings.')
    c = {**FILTER_DEFAULTS, **raw}
    x = np.asarray(c['initialState'], dtype=float)
    if x.shape != (2,) or not np.isfinite(x).all() or np.any(x < 0) or np.any(x > 100):
        raise ValueError('Initial state must contain two finite heights between 0 and 100 m.')
    for name in ('initialCovariance', 'processCovariance', 'measurementCovariance'):
        matrix(c[name], name, positive=name == 'measurementCovariance')
    for name, low, high in [('initialTime', 0, 1e12), ('maxStep', .005, .25), ('jacobianStep', 1e-7, 1e-3)]:
        if not finite(c[name]) or not low <= c[name] <= high:
            raise ValueError(f'{name} must be between {low} and {high}.')
    return c


def model_config(raw=None):
    """Only explicit physical assumptions; injected faults/initial truth excluded."""
    raw = {} if raw is None else raw
    if not isinstance(raw, dict) or set(raw)-set(MODEL_KEYS):
        raise ValueError('Estimator model accepts only physical parameters and nominal controls.')
    # The simulator editor uses a minimum 1% valve opening; the equations also
    # support a fully shut valve, essential for the observability counterexample.
    low_valve = finite(raw.get('valve')) and 0 <= raw['valve'] < .01
    validated = CoupledTankModel().validate({**raw, **({'valve': .01} if low_valve else {}), 'fault': 'healthy'})
    if low_valve:
        validated['valve'] = raw['valve']
    return validated


def transition(c, x, dt):
    return np.asarray(hydraulic_step(c, x, 0., dt)[0])


def transition_jacobian(c, x, dt, epsilon=1e-5):
    """Centered differences in the interior, forward at a dry boundary.

    Equal heads and dry outlets have no classical derivative. Here epsilon
    explicitly defines a finite-resolution secant, not a smooth Jacobian.
    """
    x = np.asarray(x, dtype=float)
    columns = []
    for j in range(2):
        h = epsilon*max(1., abs(x[j]))
        a, b = x.copy(), x.copy()
        a[j] += h
        b[j] -= h if x[j] >= h else 0.
        columns.append((transition(c, a, dt)-transition(c, b, dt))/(a[j]-b[j]))
    return np.column_stack(columns)


def stabilize(p):
    p = (p+p.T)/2
    if not np.isfinite(p).all():
        raise ValueError('Covariance overflow: reduce the horizon or revise the model and uncertainty.')
    eigenvalues, vectors = np.linalg.eigh(p)
    # Roundoff repair only. A materially indefinite covariance is a bug.
    if eigenvalues[0] < -1e-8*max(1., eigenvalues[-1]):
        raise ValueError('Covariance lost positive semidefiniteness.')
    p = (vectors*np.maximum(eigenvalues, 0.))@vectors.T
    return (p+p.T)/2


def measurement_update(x, p, z, indices, r):
    """Masked identity H, correlated R submatrix and Joseph covariance update."""
    h = np.eye(2)[indices]
    r = r[np.ix_(indices, indices)]
    innovation = np.asarray(z)-h@x
    s = h@p@h.T+r
    gain = np.linalg.solve(s, h@p).T
    updated = x+gain@innovation
    a = np.eye(2)-gain@h
    covariance = stabilize(a@p@a.T+gain@r@gain.T)
    nis = float(innovation@np.linalg.solve(s, innovation))
    return updated, covariance, innovation, s, nis


def validate_observations(observations, initial_time):
    if not isinstance(observations, list) or not 1 <= len(observations) <= 6000:
        raise ValueError('Use 1–6,000 timestamped observation rows.')
    previous = initial_time
    for i, row in enumerate(observations):
        if not isinstance(row, dict) or set(row)-{'t', *STATES}:
            raise ValueError('Observations contain only t, level1 and level2.')
        t = row.get('t')
        if not finite(t) or t < previous or (i and t == previous):
            raise ValueError('Observation timestamps must strictly increase from initialTime; combine simultaneous sensors in one row.')
        for key in STATES:
            if row.get(key) is not None and not finite(row[key]):
                raise ValueError('A level observation must be finite or null.')
        previous = t


def validate_controls(controls):
    if not isinstance(controls, list) or len(controls) > 6000:
        raise ValueError('Use at most 6,000 control events.')
    previous = -math.inf
    for row in controls:
        if not isinstance(row, dict) or set(row)-{'t', 'pumpControl', 'valve'} or len(row) < 2:
            raise ValueError('Control events need t and a pumpControl or valve command.')
        if not finite(row.get('t')) or row['t'] < 0 or row['t'] <= previous:
            raise ValueError('Control timestamps must be nonnegative and strictly increase.')
        for key, high in [('pumpControl', 150), ('valve', 1)]:
            if key in row and (not finite(row[key]) or not 0 <= row[key] <= high):
                raise ValueError('Control command is outside the physical range.')
        previous = row['t']


def estimate(observations, controls=None, *, model=None, config=None, sensors=None):
    """Run EKF plus open-loop and current-measurement baselines causally.

    Observations and controls are the entire inference interface; no truth,
    injected fault configuration, interpolated observations or future inputs.
    """
    c, cfg = model_config(model), settings(config)
    assumed_model = {k:c[k] for k in MODEL_KEYS}
    controls = [] if controls is None else controls
    sensors = list(STATES) if sensors is None else sensors
    if not isinstance(sensors, list) or len(set(sensors)) != len(sensors) or any(s not in STATES for s in sensors):
        raise ValueError('Select unique level1/level2 sensors, or none for prediction only.')
    validate_observations(observations, cfg['initialTime'])
    validate_controls(controls)
    t = cfg['initialTime']
    if (observations[-1]['t']-t)/cfg['maxStep']+len(observations)+len(controls) > 120000:
        raise ValueError('Estimation exceeds the 120,000-substep budget.')
    x = np.array(cfg['initialState'], dtype=float)
    open_loop = x.copy()
    p = matrix(cfg['initialCovariance'], 'initialCovariance')
    q = matrix(cfg['processCovariance'], 'processCovariance')
    r = matrix(cfg['measurementCovariance'], 'measurementCovariance', positive=True)
    cursor, rows, warnings = 0, [], set()
    for observation in observations:
        target = observation['t']
        while t < target:
            while cursor < len(controls) and controls[cursor]['t'] <= t:
                c.update({k:v for k, v in controls[cursor].items() if k != 't'})
                cursor += 1
            event = controls[cursor]['t'] if cursor < len(controls) else target
            dt = min(cfg['maxStep'], target-t, event-t)
            if abs(x[0]-x[1]) < 10*cfg['jacobianStep'] or min(x) < 10*cfg['jacobianStep']:
                warnings.add('nonsmooth-flow')
            f = transition_jacobian(c, x, dt, cfg['jacobianStep'])
            x = transition(c, x, dt)
            open_loop = transition(c, open_loop, dt)
            p = stabilize(f@p@f.T+q*dt)
            t = min(target, t+dt)
        prior = x.copy()
        observed = [observation.get(key) if key in sensors else None for key in STATES]
        indices = [j for j, v in enumerate(observed) if v is not None]
        innovations, residuals, innovation_sd = [None]*2, [None]*2, [None]*2
        nis = None
        if indices:
            x, p, innovation, s, nis = measurement_update(x, p, [observed[j] for j in indices], indices, r)
            for a, j in enumerate(indices):
                innovations[j] = float(innovation[a])
                innovation_sd[j] = float(math.sqrt(s[a, a]))
            if np.any(x < 0):
                warnings.add('boundary-projection')
                x = np.maximum(0., x)
            for j in indices:
                residuals[j] = float(observed[j]-x[j])
        sd = np.sqrt(np.maximum(0., np.diag(p)))
        rows.append(dict(t=target, estimate=x.tolist(), prediction=prior.tolist(),
                         openLoop=open_loop.tolist(), direct=observed, observed=observed,
                         covariance=p.tolist(), lower=(x-1.96*sd).tolist(), upper=(x+1.96*sd).tolist(),
                         innovation=innovations, residual=residuals, innovationSd=innovation_sd,
                         nis=nis, dof=len(indices)))
    updated = [row for row in rows if row['dof']]
    consistency = {str(d):dict(count=len(group), meanNIS=float(np.mean([r['nis'] for r in group])),
                              expectedMean=d, fraction95=float(np.mean([r['nis'] <= {1:3.841459, 2:5.991465}[d] for r in group])))
                   for d in (1, 2) if (group := [r for r in updated if r['dof'] == d])}
    return dict(rows=rows, sensors=sensors, config=cfg, model=assumed_model,
                predictionOnly=sum(not row['dof'] for row in rows), warnings=sorted(warnings),
                innovationConsistency=consistency,
                innovationMean=[float(np.mean(v)) if (v := [r['innovation'][j] for r in updated if r['innovation'][j] is not None]) else None for j in range(2)])


def observability(model=None, point=None, sensors=None):
    """Continuous local linearization O=[H; HA], singular values in SI units."""
    c = model_config(model)
    point = [1.5625, 1.] if point is None else point
    x = np.asarray(point, dtype=float)
    if x.shape != (2,) or not np.isfinite(x).all() or np.any(x < 0) or np.any(x > 100):
        raise ValueError('Operating point needs two nonnegative finite heights up to 100 m.')
    sensors = list(STATES) if sensors is None else sensors
    if not isinstance(sensors, list) or len(set(sensors)) != len(sensors) or any(s not in STATES for s in sensors):
        raise ValueError('Invalid observability sensor selection.')
    h = np.eye(2)[[STATES.index(s) for s in sensors]]
    flow = flows(c, x, 0, None, 0, {})[0]
    drift = [(flow[0]-flow[1]-flow[4])/c['area1'], (flow[1]-flow[2]-flow[5])/c['area2']]
    coupling = c['connection']*c['valve']
    nonsmooth = (x[0] == x[1] and coupling != 0) or x[1] == 0
    if nonsmooth:
        return dict(point=x.tolist(), sensors=sensors, drift=drift, A=None, H=h.tolist(), matrix=None,
                    rank=None, singularValues=[], condition=None, poorlyObservable=True,
                    status='nondifferentiable', equilibrium=False)
    k = coupling/(2*math.sqrt(abs(x[0]-x[1]))) if coupling else 0.
    d = c['outlet']*c['outletValve']/(2*math.sqrt(x[1]))
    spill = [.15*math.sqrt(max(0., v-c['tankHeight'])) for v in x]
    a = np.array([[(-k-spill[0])/c['area1'], k/c['area1']],
                  [k/c['area2'], (-k-d-spill[1])/c['area2']]])
    o = np.vstack([h, h@a])
    singular = np.linalg.svd(o, compute_uv=False) if sensors else np.zeros(2)
    tolerance = max(o.shape)*np.finfo(float).eps*singular[0] if sensors else 0.
    rank = int(np.sum(singular > tolerance))
    condition = float(singular[0]/singular[-1]) if rank == 2 else None
    return dict(point=x.tolist(), sensors=sensors, drift=drift, A=a.tolist(), H=h.tolist(), matrix=o.tolist(),
                rank=rank, rankTolerance=float(tolerance), singularValues=singular.tolist(), condition=condition,
                poorlyObservable=rank < 2 or singular[-1] < 1e-3 or condition > 1000,
                status='local-linearization', equilibrium=bool(np.max(np.abs(drift)) < 1e-9))


def score(result, truth, *, tolerance=.05):
    """Retrospective scoring only; truth must match the estimation clock exactly."""
    rows = result['rows']
    if len(truth) != len(rows) or any(a['t'] != b['t'] for a, b in zip(rows, truth)):
        raise ValueError('Scoring truth must match every estimation timestamp.')
    target = np.array([[r[k] for k in STATES] for r in truth])
    metrics = {}
    for method in ('estimate', 'openLoop', 'direct'):
        values = np.array([[np.nan if v is None else v for v in r[method]] for r in rows])
        error = values-target
        metrics[method] = [dict(count=int(np.isfinite(error[:, j]).sum()),
                               rmse=float(np.sqrt(np.mean(error[mask, j]**2))) if np.any(mask := np.isfinite(error[:, j])) else None,
                               mae=float(np.mean(np.abs(error[mask, j]))) if np.any(mask) else None) for j in range(2)]
    errors = np.array([r['estimate'] for r in rows])-target
    nees = [float(e@np.linalg.solve(p, e)) for e, row in zip(errors, rows)
            if np.linalg.eigvalsh(p := np.asarray(row['covariance']))[0] > 1e-14]
    inside = np.all(np.abs(errors) <= tolerance, axis=1)
    # First time after which both errors stay below tolerance, through this run's end.
    suffix = np.logical_and.accumulate(inside[::-1])[::-1]
    convergence = next((row['t'] for row, ok in zip(rows, suffix) if ok), None)
    return dict(methods=metrics, coverage95=np.mean((target >= np.array([r['lower'] for r in rows])) &
                (target <= np.array([r['upper'] for r in rows])), axis=0).tolist(),
                meanNEES=float(np.mean(nees)) if nees else None, neesDof=2, neesCount=len(nees),
                convergenceTime=convergence, convergenceTolerance=tolerance,
                finalAbsoluteError=np.abs(errors[-1]).tolist(),
                worseThanOpenLoop=[metrics['estimate'][j]['rmse'] > metrics['openLoop'][j]['rmse'] for j in range(2)])
