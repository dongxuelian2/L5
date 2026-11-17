"""Offline coupled-tank output-error identification, independent of simulator truth.

Inputs are exact, zero-order-held commands; output errors are independent Gaussian
with user-specified standard deviations. All inference is local to this model,
these units, the selected outputs and the calibration interval.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from time import perf_counter

import numpy as np
from scipy.optimize import least_squares

from .models.base import finite
from .models.tanks import DEFAULTS, euler_stage, flows

VERSION = 'coupled-tanks-output-error-v1'
OUTPUTS = ('level1', 'level2', 'inlet', 'transfer', 'outlet')
INPUTS = ('pump', 'valve')
# Characteristic scales are fixed engineering scales, independent of user bounds.
PARAMETERS = {
    'pumpRate': dict(label='Nominal pump flow', unit='m³/s', min=.0001, max=.2, scale=.03),
    'connection': dict(label='Connection discharge coefficient', unit='m^(5/2)/s', min=.001, max=.2, scale=.04),
    'outlet': dict(label='Outlet discharge coefficient', unit='m^(5/2)/s', min=.001, max=.2, scale=.03),
    'initial1': dict(label='Initial Tank 1 level', unit='m', min=0., max=10., scale=1.),
    'initial2': dict(label='Initial Tank 2 level', unit='m', min=0., max=10., scale=1.),
    'pumpEfficiency': dict(label='Pump efficiency factor', unit='fraction', min=.1, max=1., scale=1.),
}
FIXED = {k: DEFAULTS[k] for k in ('area1', 'area2', 'pumpRate', 'connection', 'outlet',
         'initial1', 'initial2', 'pumpControl', 'valve', 'outletValve', 'tankHeight')}
FIXED['pumpEfficiency'] = 1.
FIXED_BOUNDS = dict(area1=(.1,10), area2=(.1,10), pumpControl=(0,150), valve=(.01,1),
                    outletValve=(.01,1), tankHeight=(.1,10))


@dataclass
class Observations:
    times: np.ndarray
    values: dict[str, np.ndarray]
    reference: dict


def configuration(raw):
    if not isinstance(raw, dict):
        raise ValueError('Identification configuration must be an object.')
    allowed = {'calibration', 'validation', 'parameters', 'nominal', 'noise', 'integrationStep', 'maxEvaluations'}
    if set(raw) - allowed:
        raise ValueError('Unknown identification configuration option.')
    nominal = raw.get('nominal', {})
    if not isinstance(nominal, dict) or set(nominal) - FIXED.keys():
        raise ValueError('Choose supported fixed physical parameters.')
    nominal = FIXED | nominal
    for key, value in nominal.items():
        low, high = FIXED_BOUNDS.get(key, (PARAMETERS.get(key, {}).get('min'), PARAMETERS.get(key, {}).get('max')))
        if not finite(value) or not low <= value <= high:
            raise ValueError('Fixed physical parameters are outside their physical bounds.')
    specs = raw.get('parameters')
    if not isinstance(specs, dict) or not specs or set(specs) - PARAMETERS.keys():
        raise ValueError('Select supported physical parameters to estimate.')
    specs = {k: specs[k] for k in PARAMETERS if k in specs}
    for key, spec in specs.items():
        limits = PARAMETERS[key]
        if (not isinstance(spec, dict) or set(spec) != {'initial', 'lower', 'upper'} or
                any(not finite(v) for v in spec.values()) or
                not limits['min'] <= spec['lower'] <= spec['initial'] <= spec['upper'] <= limits['max'] or
                spec['upper'] - spec['lower'] < limits['scale'] * 1e-5):
            raise ValueError('Initial guesses and bounds must lie inside physical parameter limits.')
    noise = raw.get('noise', {})
    if not isinstance(noise, dict) or set(noise) - set(OUTPUTS):
        raise ValueError('Specify output measurement noise standard deviations.')
    noise = {k: noise.get(k, .002 if k.startswith('level') else .0002) for k in OUTPUTS}
    if any(not finite(v) or not 1e-8 <= v <= 10 for v in noise.values()):
        raise ValueError('Noise standard deviations must be positive finite values between 1e-8 and 10.')
    step = raw.get('integrationStep', .05)
    budget = raw.get('maxEvaluations', 80)
    if not finite(step) or not .005 <= step <= .25:
        raise ValueError('Integration step must be between 0.005 and 0.25 seconds.')
    if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 200:
        raise ValueError('Use 1–200 optimizer evaluations.')
    return dict(parameters=specs, nominal=nominal, noise=noise, integrationStep=step, maxEvaluations=budget)


def initial_state(config, data, *, estimated=()):
    c = dict(config)
    for i, key in enumerate(('initial1', 'initial2')):
        signal = f'level{i+1}'
        if key not in estimated and signal in data.values and np.isfinite(data.values[signal][0]):
            c[key] = float(np.clip(data.values[signal][0], 0, 10))
    return c


def predict(config, data, step=.05, *, with_balance=False):
    """Stable public twin interface: parameters + timestamped inputs -> outputs.

    No output is assimilated here. Initial conditions must be supplied explicitly.
    Fluxes and donor limits are the exact same functions as the physical simulator.
    """
    c = DEFAULTS | config | dict(fault='healthy', noise=0.)
    c['pumpRate'] *= config.get('pumpEfficiency', 1.)
    heads = [c['initial1'], c['initial2']]
    initial_volume = c['area1']*heads[0] + c['area2']*heads[1]
    totals = [0.]*6
    result = np.empty((len(data.times), len(OUTPUTS)))
    mass_error = 0.
    for i, target in enumerate(data.times):
        if i:
            # Interval [t[i-1], t[i]) uses only the previous command sample.
            t = float(data.times[i-1])
            while t < target - 1e-10:
                dt = min(step, target-t)
                f = flows(c, heads, 0., None, 0., {})[0]
                left, f1 = euler_stage(c, heads, dt, f)
                right, f2 = euler_stage(c, left, dt, flows(c, left, 0., None, 0., {})[0])
                heads = [(a+b)/2 for a,b in zip(heads,right)]
                totals = [v+dt*(a+b)/2 for v,a,b in zip(totals,f1,f2)]
                t += dt
        c['pumpControl'] = float(data.values['pump'][i]) if 'pump' in data.values else config['pumpControl']
        c['valve'] = float(data.values['valve'][i]) if 'valve' in data.values else config['valve']
        f = flows(c, heads, 0., None, 0., {})[0]
        result[i] = [*heads, *f[:3]]
        volume = c['area1']*heads[0] + c['area2']*heads[1]
        mass_error = max(mass_error, abs(volume-initial_volume-totals[0]+sum(totals[2:])))
    return (result, mass_error) if with_balance else result


def jacobian(function, x, scales, relative_step=1e-4):
    columns = []
    for j, scale in enumerate(scales):
        delta = max(abs(x[j]), scale)*relative_step
        plus, minus = x.copy(), x.copy()
        plus[j] += delta
        minus[j] -= delta
        # Bounds limit fitting, not the local derivative. Avoid negative physics.
        minus[j] = max(0., minus[j])
        columns.append((function(plus)-function(minus))/(plus[j]-minus[j]))
    return np.stack(columns, axis=-1)


def diagnostics(observed, predicted, sigma, *, skip_first=False):
    result = {}
    for key, obs in observed.items():
        if key not in OUTPUTS:
            continue
        residual = predicted[:, OUTPUTS.index(key)] - obs
        if skip_first:
            residual = residual[1:]
        adjacent = np.isfinite(residual[:-1]) & np.isfinite(residual[1:])
        previous,following=residual[:-1][adjacent],residual[1:][adjacent]
        residual = residual[np.isfinite(residual)]
        if not len(residual):
            raise ValueError('Each output needs finite observations after initialization.')
        n = len(residual)
        mean = float(np.mean(residual))
        std = float(np.std(residual))
        centered = residual-mean
        energy = float(centered @ centered)
        lag1 = float((previous-mean) @ (following-mean)/energy) if energy > n*sigma[key]**2*1e-12 else 0.
        edges = np.linspace(float(residual.min())-1e-12, float(residual.max())+1e-12, 13)
        counts, edges = np.histogram(residual, edges)
        result[key] = dict(samples=n, rmse=float(np.sqrt(np.mean(residual**2))), mae=float(np.mean(np.abs(residual))),
                           bias=mean, std=std, lag1=lag1, quantiles=np.quantile(residual,[.05,.5,.95]).tolist(),
                           histogram=dict(edges=edges.tolist(), counts=counts.tolist()),
                           systematic=bool(abs(mean) > 3*sigma[key]/math.sqrt(n) or
                                           (std > .1*sigma[key] and abs(lag1) > 3/math.sqrt(n))),
                           normalizedRmse=float(np.sqrt(np.mean(residual**2))/sigma[key]))
    return result


def identifiability(jac, names, scales, fitted, specs):
    scaled = jac*np.array(scales)
    _, singular, vh = np.linalg.svd(scaled, full_matrices=False)
    tolerance = max(1e-7, float(singular[0])*1e-6)
    rank = int(np.sum(singular > tolerance))
    norms = np.linalg.norm(scaled, axis=0)
    cosine = scaled.T @ scaled / np.maximum(np.outer(norms, norms), 1e-30)
    condition = float(singular[0]/singular[-1]) if rank == len(names) else None
    # One noise-standard-deviation along a scaled parameter direction must be
    # smaller than its characteristic scale to be practically informative.
    weak = [dict(singularValue=float(s), combination={k:float(v) for k,v in zip(names, vector)})
            for s,vector in zip(singular,vh) if s <= max(tolerance, 1.)]
    bound = [k for k,v in zip(names,fitted) if min(v-specs[k]['lower'],specs[k]['upper']-v) <=
             1e-4*(specs[k]['upper']-specs[k]['lower'])]
    covariance = None
    correlation = None
    if rank == len(names):
        cov_scaled = (vh.T / singular**2) @ vh
        covariance = cov_scaled*np.outer(scales,scales)
        sd = np.sqrt(np.diag(covariance))
        correlation = covariance / np.maximum(np.outer(sd,sd),1e-30)
    return dict(rank=rank, parameterCount=len(names), singularValues=singular.tolist(), rankTolerance=tolerance,
                conditionNumber=condition, sensitivityNorms=dict(zip(names,norms.tolist())),
                sensitivityCosine=cosine.tolist(), correlation=correlation.tolist() if correlation is not None else None,
                weakCombinations=weak, activeBounds=bound,
                status='rank-deficient' if rank < len(names) else 'weak' if weak or condition > 1e5 else 'locally-identifiable'), covariance


def evaluate(config, nominal, data, noise, step, *, skip_first=False, envelope=None):
    fitted, mass = predict(config,data,step,with_balance=True)
    original = predict(nominal,data,step)
    fine = predict(config,data,step/2)
    outputs = [k for k in OUTPUTS if k in data.values]
    numerical = {k:float(np.sqrt(np.mean((fine[:,OUTPUTS.index(k)]-fitted[:,OUTPUTS.index(k)])**2))) for k in outputs}
    return dict(reference=data.reference, times=data.times.tolist(),
                observed={k:[float(v) if np.isfinite(v) else None for v in data.values[k]] for k in outputs},
                predicted={k:fitted[:,OUTPUTS.index(k)].tolist() for k in outputs},
                original={k:original[:,OUTPUTS.index(k)].tolist() for k in outputs},
                residuals={k:[float(v) if np.isfinite(v) else None for v in fitted[:,OUTPUTS.index(k)]-data.values[k]] for k in outputs},
                metrics=diagnostics(data.values,fitted,noise,skip_first=skip_first),
                originalMetrics=diagnostics(data.values,original,noise,skip_first=skip_first),
                initializationExcluded=skip_first, numericalStepDifferenceRmse=numerical, massBalanceError=mass,
                parameterEnvelope=envelope)


def rolling_predictions(config, nominal, data, noise, step):
    if not all(k in data.values for k in ('level1','level2')):
        return []
    reports = []
    for horizon in (5.,20.,60.):
        pairs=[]
        eligible = np.flatnonzero(data.times <= data.times[-1]-horizon)
        for i in eligible[np.unique(np.linspace(0,len(eligible)-1,min(12,len(eligible))).astype(int))] if len(eligible) else []:
            if not all(np.isfinite(data.values[k][i]) for k in ('level1','level2')):
                continue
            j=int(np.searchsorted(data.times,data.times[i]+horizon))
            sub=Observations(data.times[i:j+1], {k:v[i:j+1] for k,v in data.values.items()},data.reference)
            initialized=initial_state(config,sub)
            base=initial_state(nominal,sub)
            pairs.append((j,float(data.times[j]-data.times[i]),predict(initialized,sub,step)[-1],predict(base,sub,step)[-1]))
        if pairs:
            observed={k:np.array([data.values[k][p[0]] for p in pairs]) for k in OUTPUTS if k in data.values}
            # Missing outputs at some rolling targets are omitted, never filled.
            observed={k:v for k,v in observed.items() if np.isfinite(v).any()}
            reports.append(dict(horizonSeconds=horizon, origins=len(pairs), actualHorizons=[p[1] for p in pairs],
                metrics=diagnostics(observed,np.array([p[2] for p in pairs]),noise),
                originalMetrics=diagnostics(observed,np.array([p[3] for p in pairs]),noise)))
    return reports


def fit(config, calibration, validation=None, progress=lambda value: None):
    started=perf_counter()
    specs=config['parameters']; names=list(specs)
    scales=np.array([PARAMETERS[k]['scale'] for k in names])
    x0=np.array([specs[k]['initial'] for k in names])
    lower=np.array([specs[k]['lower'] for k in names]); upper=np.array([specs[k]['upper'] for k in names])
    nominal=initial_state(config['nominal'],calibration)
    fixed=initial_state(config['nominal'],calibration,estimated=names)
    outputs=[k for k in OUTPUTS if k in calibration.values]
    sigma=np.array([config['noise'][k] for k in outputs])
    observed=np.column_stack([calibration.values[k] for k in outputs])
    mask=np.isfinite(observed)
    for i,key in enumerate(outputs):
        if key in ('level1','level2') and f'initial{key[-1]}' not in names:
            # A measurement used as an exact initialization is not a second,
            # independent output observation for the likelihood or its dof.
            mask[0,i]=False
    if mask.sum() <= len(names)+2:
        raise ValueError('Calibration needs more finite output observations than estimated parameters.')
    columns=[OUTPUTS.index(k) for k in outputs]
    calls=0; trace=[]
    def physical(x):
        return fixed | dict(zip(names,map(float,x)))
    def residual(x):
        return ((predict(physical(x),calibration,config['integrationStep'])[:,columns]-observed)/sigma)[mask]
    def objective(z):
        nonlocal calls
        calls+=1
        return residual(z*scales)
    def update(intermediate_result):
        entry=dict(evaluations=int(intermediate_result.nfev), cost=float(intermediate_result.cost))
        trace.append(entry)
        progress(dict(stage='fitting',**entry))
    progress(dict(stage='fitting',evaluations=0))
    solved=least_squares(objective,x0/scales,bounds=(lower/scales,upper/scales),method='trf',jac='3-point',
                         max_nfev=config['maxEvaluations'],ftol=1e-8,xtol=1e-8,gtol=1e-8,callback=update)
    x=solved.x*scales
    fitted=physical(x)
    progress(dict(stage='diagnostics',evaluations=int(solved.nfev),cost=float(solved.cost)))
    jac=jacobian(residual,x,scales)
    refined_jac=jacobian(residual,x,scales,relative_step=5e-5)
    derivative_difference=float(np.linalg.norm((refined_jac-jac)*scales) /
                                max(np.linalg.norm(jac*scales),1e-12))
    identity,covariance=identifiability(jac,names,scales,x,specs)
    cal=evaluate(fitted,nominal,calibration,config['noise'],config['integrationStep'])
    chi2=float(2*solved.cost/(mask.sum()-len(names)))
    warnings=[]
    if not solved.success: warnings.append('optimizer-incomplete')
    if identity['status'] != 'locally-identifiable': warnings.append(identity['status'])
    if identity['activeBounds']: warnings.append('active-bounds')
    if derivative_difference > .02: warnings.append('sensitivity-unstable')
    if 'pumpRate' in names and 'pumpEfficiency' in names: warnings.append('pump-product-confounding')
    if chi2 > 2 or any(v['systematic'] for v in cal['metrics'].values()): warnings.append('residual-mismatch')
    if any(v > config['noise'][k]*.1 for k,v in cal['numericalStepDifferenceRmse'].items()): warnings.append('integration-error')
    # Suppress covariance claims when local Gaussian interior assumptions fail.
    justified=not warnings and covariance is not None
    uncertainty=dict(method='local-linearized-known-noise', available=justified,
        assumptions=['independent-gaussian-output-noise','exact-held-inputs','fixed-geometry','local-interior-optimum',
                     'unestimated-initial-state-uncertainty-excluded','model-mismatch-excluded','numerical-error-excluded'],
        standardErrors={k:float(v) for k,v in zip(names,np.sqrt(np.diag(covariance)))} if justified else None,
        covariance=covariance.tolist() if justified else None)
    def envelope(data,c,reset):
        if not justified: return None
        def path(values):
            candidate=fitted | dict(zip(names,map(float,values)))
            if reset: candidate=initial_state(candidate,data)
            return predict(candidate,data,config['integrationStep'])
        derivative=jacobian(path,x,scales)
        sd=np.sqrt(np.maximum(0,np.einsum('...i,ij,...j->...',derivative,covariance,derivative)))
        center=predict(c,data,config['integrationStep'])
        return {k:dict(lower=(center[:,OUTPUTS.index(k)]-1.96*sd[:,OUTPUTS.index(k)]).tolist(),
                       upper=(center[:,OUTPUTS.index(k)]+1.96*sd[:,OUTPUTS.index(k)]).tolist())
                for k in OUTPUTS if k in data.values}
    cal['parameterEnvelope']=envelope(calibration,fitted,False)
    val=None
    if validation is not None:
        progress(dict(stage='validation',evaluations=int(solved.nfev)))
        # Only the first validation observation initializes a fresh trajectory.
        # No validation value, diagnostic or metric participates in optimization.
        vc=initial_state(fitted,validation); vn=initial_state(nominal,validation)
        val=evaluate(vc,vn,validation,config['noise'],config['integrationStep'],skip_first=True,
                     envelope=envelope(validation,vc,True))
        val['multiStep']=rolling_predictions(vc,vn,validation,config['noise'],config['integrationStep'])
    return dict(engineVersion=VERSION,modelId='coupled-tanks',fittedConfig=fitted,nominalConfig=nominal,
        parameters={k:dict(value=float(v),**specs[k],unit=PARAMETERS[k]['unit']) for k,v in zip(names,x)},
        optimizer=dict(converged=bool(solved.success),status=int(solved.status),message=solved.message,
                       evaluations=int(solved.nfev),simulationCalls=calls,cost=float(solved.cost),
                       optimality=float(solved.optimality),trace=trace),
        identifiability=identity,uncertainty=uncertainty,warnings=warnings,reducedChiSquare=chi2,
        sensitivityStepDifference=derivative_difference,
        calibration=cal,validation=val,durationMs=(perf_counter()-started)*1000)
