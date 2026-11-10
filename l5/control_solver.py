"""Dense convex QP using SciPy SLSQP, with independently checked KKT evidence.

min 1/2 x' H x + g' x, subject to lower <= A x <= upper.
All constraints (including bounds) are explicit so SLSQP returns every KKT
multiplier. A successful exit alone is insufficient: feasibility, stationarity,
dual sign and complementarity must also pass the configured tolerance.
"""
from __future__ import annotations

import numpy as np
from scipy.linalg import qr
from scipy.optimize import minimize


def solve_qp(h, g, a, lower, upper, *, initial=None, iterations=1200, tolerance=1e-5):
    h,g,a,lower,upper=(np.asarray(v,dtype=float) for v in (h,g,a,lower,upper))
    if not all(np.all(np.isfinite(v)) for v in (h,g,a)) or np.any(lower>upper):
        raise ValueError('Invalid QP coefficients.')
    if not np.allclose(h,h.T,atol=1e-12):
        raise ValueError('QP Hessian must be symmetric positive definite.')
    np.linalg.cholesky(h)  # KKT sufficiency relies on convexity.
    scale=np.maximum(np.linalg.norm(a,axis=1),1.)
    a,lower,upper=a/scale[:,None],lower/scale,upper/scale
    equality=lower==upper
    eq=a[equality]; eq_target=lower[equality]
    if len(eq):
        # Fixed actuators plus zero slew can express the same equality repeatedly.
        # SLSQP requires an independent basis; original rows remain in the final
        # primal check, so inconsistent redundant targets cannot be accepted.
        _,triangular,pivots=qr(eq.T,mode='economic',pivoting=True)
        rank=int(np.sum(np.abs(np.diag(triangular))>1e-10))
        keep=sorted(pivots[:rank]);eq,eq_target=eq[keep],eq_target[keep]
    lo=np.isfinite(lower)&~equality;hi=np.isfinite(upper)&~equality
    inequality=np.concatenate([a[lo],-a[hi]])
    target=np.r_[lower[lo],-upper[hi]]
    constraints=[]
    if len(eq):constraints.append(dict(type='eq',fun=lambda x:eq@x-eq_target,jac=lambda x:eq))
    if len(inequality):constraints.append(dict(type='ineq',fun=lambda x:inequality@x-target,jac=lambda x:inequality))
    x0=np.zeros(len(g)) if initial is None else np.asarray(initial,dtype=float).copy()
    result=minimize(lambda x:float(.5*x@h@x+g@x),x0,jac=lambda x:h@x+g,method='SLSQP',constraints=constraints,
                    options=dict(maxiter=iterations,ftol=min(1e-12,tolerance**2*.01),disp=False))
    x=result.x
    if not np.all(np.isfinite(x)):
        return dict(status='nonfinite',x=None,iterations=int(result.nit),primalResidual=None,stationarityResidual=None)
    ax=a@x
    primal=float(max(0.,np.max(lower-ax),np.max(ax-upper)))
    multipliers=np.asarray(result.multipliers)
    gradient=h@x+g
    if len(eq):gradient-=eq.T@multipliers[:len(eq)]
    dual=multipliers[len(eq):]
    if len(inequality):gradient-=inequality.T@dual
    stationarity=float(np.max(np.abs(gradient)))
    complementarity=float(np.max(np.abs(dual*(inequality@x-target)))) if len(dual) else 0.
    dual_violation=float(max(0.,-np.min(dual))) if len(dual) else 0.
    # SLSQP may stop its line search (status 8) at a machine-precision optimum.
    # For this strictly convex QP, independently verified KKT conditions suffice
    # to accept that point. An iteration limit is always rejected.
    accepted=bool(result.status in (0,8) and max(primal,stationarity,complementarity,dual_violation)<=tolerance)
    status='solved' if accepted else 'iteration-limit' if result.status==9 else 'residual-check-failed' if result.success else 'numerical-failure'
    return dict(status=status,x=x if accepted else None,iterations=int(result.nit),primalResidual=primal,
                stationarityResidual=stationarity,complementarityResidual=complementarity,dualViolation=dual_violation,
                optimizerStatus=int(result.status),optimizerConverged=bool(result.success),certificate='independent-kkt' if accepted else None)
