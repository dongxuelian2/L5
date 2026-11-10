"""Measurement-only PI and locally linear receding-horizon tank MPC.

Controller constructors receive nominal design constants and operator settings,
never the scenario, fault schedule, seed, hidden heads or future measurements.
Pump variables inside the optimizer are fractions of nominal flow (1 = 100%).
"""
from __future__ import annotations

import math
import numpy as np

from .control_solver import solve_qp

NOMINAL_KEYS = ('area1','area2','connection','outlet','outletValve','pumpRate','tankHeight')


def reference_at(reference, when):
    return next(p['level'] for p in reversed(reference) if p['time'] <= when)


def actuator_limits(constraints, previous, dt):
    low = np.array([constraints['pumpMin']/100,constraints['valveMin']])
    high = np.array([constraints['pumpMax']/100,constraints['valveMax']])
    rates = np.array([constraints['pumpRate']/100 if constraints['pumpRate'] is not None else np.inf,
                      constraints['valveRate'] if constraints['valveRate'] is not None else np.inf])
    return np.maximum(low,previous-rates*dt),np.minimum(high,previous+rates*dt)


class PIController:
    def __init__(self, nominal, settings, constraints, initial):
        self.nominal,self.settings,self.constraints = nominal,settings,constraints
        self.previous = np.array(initial,dtype=float)
        self.integral = 0.

    def step(self, measurement, reference, dt):
        target = reference_at(reference,measurement['t'])
        error = target-measurement['level2']
        # Equilibrium feedforward plus PI correction; all internal units fraction.
        feedforward = self.nominal['outlet']*self.nominal['outletValve']*math.sqrt(max(0,target))/max(self.nominal['pumpRate'],1e-9)
        proportional = self.settings['kp']/100*error
        low,high = actuator_limits(self.constraints,self.previous,dt)
        candidate = self.integral+self.settings['ki']/100*error*dt
        raw = feedforward+proportional+candidate
        # Conditional integration applies to magnitude AND slew saturation. Permit
        # integration toward the admissible region, freeze integration away from it.
        if low[0] <= raw <= high[0] or (raw > high[0] and error < 0) or (raw < low[0] and error > 0):
            self.integral = candidate
        raw = feedforward+proportional+self.integral
        valve = self.settings['valveBias']+self.settings['valveKp']*error if self.settings['actuateValve'] else self.previous[1]
        command = np.clip([raw,valve],low,high)
        self.previous = command
        return command,dict(status='pi',integral=float(self.integral),unconstrainedPump=float(raw*100),saturated=bool(abs(raw-command[0])>1e-8))


def local_dynamics(nominal, state, command, dt, disturbance=None, pump_gain=None):
    """Analytic hydraulic Jacobian; affine RK2 discretization at (state,command).

    Square-root derivatives are regularized below 0.02 m. The affine offset
    retains the exact nominal vector field at the operating point. The physical
    simulator continues to use the original unregularized conservative equations.
    """
    c=nominal; h1,h2=state; pump,valve=command
    delta=h1-h2; root=math.copysign(math.sqrt(abs(delta)),delta)
    transfer=c['connection']*valve*root
    slope=c['connection']*valve/(2*math.sqrt(max(abs(delta),.02)))
    outlet=c['outlet']*c['outletValve']*math.sqrt(max(0,h2))
    out_slope=c['outlet']*c['outletValve']/(2*math.sqrt(max(h2,.02)))
    spill=np.array([.1*max(0,h-c['tankHeight'])**1.5 for h in state])
    spill_slope=np.array([.15*math.sqrt(max(0,h-c['tankHeight'])) for h in state])
    gain=c['pumpRate'] if pump_gain is None else pump_gain
    f=np.array([(gain*pump-transfer-spill[0])/c['area1'],(transfer-outlet-spill[1])/c['area2']])
    if disturbance is not None:
        f += disturbance
    a=np.array([[(-slope-spill_slope[0])/c['area1'],slope/c['area1']],
                [slope/c['area2'],(-slope-out_slope-spill_slope[1])/c['area2']]])
    b=np.array([[gain/c['area1'],-c['connection']*root/c['area1']],
                [0.,c['connection']*root/c['area2']]])
    # Repeated RK2 substeps preserve stability at fast, shallow-head operating
    # points without Euler-discretization artifacts over a long control interval.
    steps=max(1,math.ceil(dt/.25)); ds=dt/steps
    one=np.eye(2)+ds*a+.5*ds*ds*a@a
    gain_map=ds*np.eye(2)+.5*ds*ds*a
    offset=f-a@state-b@command
    ad=np.eye(2); bd=np.zeros((2,2)); cd=np.zeros(2)
    for _ in range(steps):
        ad,bd,cd=one@ad,one@bd+gain_map@b,one@cd+gain_map@offset
    return ad,bd,cd


class MPCController:
    def __init__(self, nominal, settings, constraints, initial):
        self.nominal,self.settings,self.constraints=nominal,settings,constraints
        self.previous=np.array(initial,dtype=float)
        self.disturbance=np.zeros(2); self.nominal_next=None
        self.plan=None
        self.fallback=PIController(nominal,settings['fallbackPI'],constraints,initial)

    def step(self, measurement, reference, dt):
        s=self.settings; c=self.constraints
        state=np.maximum([measurement['level1'],measurement['level2']],0.)
        if self.nominal_next is not None:
            innovation=(state-self.nominal_next)/dt
            self.disturbance=.8*self.disturbance+.2*np.clip(innovation,-.05,.05)
        # Inlet flow and the previous commanded pump are available measurements.
        gain=self.nominal['pumpRate']
        if self.previous[0] > .05:
            gain=float(np.clip(measurement['inlet']/self.previous[0],0,2*gain))
        ad,bd,cd=local_dynamics(self.nominal,state,self.previous,dt,self.disturbance,gain)
        n,m=s['predictionHorizon'],s['controlHorizon']; size=2*m+2
        constant=state.copy(); sensitivity=np.zeros((2,size))
        paths=[]; offsets=[]
        for k in range(n):
            selector=np.zeros((2,size)); selector[:,2*min(k,m-1):2*min(k,m-1)+2]=np.eye(2)
            constant=ad@constant+cd
            sensitivity=ad@sensitivity+bd@selector
            paths.append(sensitivity.copy()); offsets.append(constant.copy())
        paths=np.asarray(paths); offsets=np.asarray(offsets)
        tracking=paths[:,1,:]; targets=np.array([reference_at(reference,measurement['t']+(k+1)*dt if s['preview'] else measurement['t']) for k in range(n)])
        h=2*s['trackingWeight']*tracking.T@tracking
        g=2*s['trackingWeight']*tracking.T@(offsets[:,1]-targets)
        difference=np.zeros((2*m,size)); difference[:,:2*m]=np.eye(2*m)
        for k in range(1,m):
            difference[2*k:2*k+2,2*k-2:2*k]=-np.eye(2)
        previous=np.zeros(2*m); previous[:2]=self.previous
        h+=2*s['moveWeight']*difference.T@difference
        g-=2*s['moveWeight']*difference.T@previous
        # Penalize normalized pump energy and valve magnitude. No hidden
        # reference-dependent optimal action is supplied.
        effort=np.tile([1.,.2],m)
        h[np.arange(2*m),np.arange(2*m)]+=2*s['effortWeight']*effort
        h[-2:,-2:]+=np.eye(2)*2*s['levelWeight']
        h+=np.eye(size)*1e-8
        a=[]; lower=[]; upper=[]
        minimum=np.array([c['pumpMin']/100,c['valveMin']]); maximum=np.array([c['pumpMax']/100,c['valveMax']])
        if not s['actuateValve']:
            minimum[1]=maximum[1]=self.previous[1]
        rate=np.array([c['pumpRate']/100 if c['pumpRate'] is not None else np.inf,c['valveRate'] if c['valveRate'] is not None else np.inf])*dt
        for k in range(m):
            selector=np.zeros((2,size)); selector[:,2*k:2*k+2]=np.eye(2)
            a.extend(selector); lower.extend(minimum); upper.extend(maximum)
        a.extend(difference); lower.extend(previous-np.tile(rate,m)); upper.extend(previous+np.tile(rate,m))
        # Two nonnegative shared slacks bound worst predicted excursion for each
        # tank. Operational limits are SOFT; actuator constraints remain HARD.
        for k in range(n):
            for j in range(2):
                high=paths[k,j].copy(); high[2*m+j]=-1
                low=-paths[k,j].copy(); low[2*m+j]=-1
                a.extend([high,low]); lower.extend([-np.inf,-np.inf])
                upper.extend([c[f'levelMax{j+1}']-offsets[k,j],offsets[k,j]-c[f'levelMin{j+1}']])
        slack=np.zeros((2,size)); slack[:,-2:]=np.eye(2)
        a.extend(slack); lower.extend([0.,0.]); upper.extend([np.inf,np.inf])
        initial=np.r_[np.tile(self.previous,m),0.,0.]
        if self.plan is not None:
            initial[:2*m]=np.r_[self.plan[2:2*m],self.plan[2*m-2:2*m]]
        try:
            result=solve_qp(h,g,a,lower,upper,initial=initial,iterations=s['maxIterations'],tolerance=s['tolerance'])
        except (np.linalg.LinAlgError,FloatingPointError):
            result=dict(status='numerical-failure',x=None,iterations=0,primalResidual=None,stationarityResidual=None)
        solution=result.pop('x'); status=result['status']
        if solution is None:
            self.fallback.previous=self.previous.copy()
            command,fallback_info=self.fallback.step(measurement,reference,dt)
            self.plan=None
            info=dict(**result,fallback=True,fallbackController='pi',fallbackInfo=fallback_info,prediction=[],plan=[])
        else:
            low,high=actuator_limits(c,self.previous,dt)
            command=np.clip(solution[:2],low,high)  # Remove solver tolerance at the physical boundary.
            if not s['actuateValve']:
                command[1]=self.previous[1]
            self.plan=solution
            prediction=offsets+np.einsum('kij,j->ki',paths,solution)
            constant_cost=s['trackingWeight']*np.sum((offsets[:,1]-targets)**2)+s['moveWeight']*(previous@previous)
            info=dict(**result,fallback=False,objective=float(.5*solution@h@solution+g@solution+constant_cost),
                      prediction=prediction.tolist(),plan=solution[:2*m].reshape(m,2).tolist(),
                      predictedSlack=np.maximum(solution[-2:],0).tolist(),targets=targets.tolist())
            # Keep PI fallback bumpless with the actually applied MPC action.
            target=reference_at(reference,measurement['t'])
            feed=self.nominal['outlet']*self.nominal['outletValve']*math.sqrt(max(0,target))/max(self.nominal['pumpRate'],1e-9)
            self.fallback.integral=float(command[0]-feed-s['fallbackPI']['kp']/100*(target-measurement['level2']))
        # Store an unaugmented one-step prediction so the innovation estimates the
        # total persistent model mismatch rather than repeatedly subtracting it.
        an,bn,cn=local_dynamics(self.nominal,state,command,dt,pump_gain=gain)
        self.nominal_next=an@state+bn@command+cn
        self.previous=command
        return command,{**info,'status':status,'estimatedDisturbance':self.disturbance.tolist(),'measuredPumpGain':gain}
