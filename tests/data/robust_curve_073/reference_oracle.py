"""Independent reference: direct scalar rho minimization, not the production solver."""
import math
import numpy as np
from scipy.optimize import minimize, least_squares

MODEL_PARAMETERS = {'Straight line': ['Intercept','Slope'], 'One-phase decay': ['Plateau','Span','Rate'],
                    'Horizontal line': ['Mean'], 'Logistic (4 parameters)': ['Low','High','Midpoint','Slope']}


def equation(model, x, p):
    if model == 'Straight line': return p[0] + p[1]*x
    if model == 'One-phase decay': return p[0] + p[1]*np.exp(-p[2]*x)
    if model == 'Horizontal line': return np.full_like(x,p[0],dtype=float)
    if model == 'Logistic (4 parameters)': return p[0]+(p[1]-p[0])/(1+np.exp(-(x-p[2])*p[3]))
    raise ValueError(model)


def rho_weights(u, loss):
    u=np.asarray(u,dtype=float); a=np.abs(u); z=u*u
    if loss=='Cauchy': return np.log1p(z), 1/(1+z)
    if loss=='Soft L1':
        h=np.hypot(1,u); return 2*z/(h+1), 1/h
    if loss=='Huber': return np.where(a<=1,z,2*a-1), np.where(a<=1,1,1/np.maximum(a,np.finfo(float).tiny))
    raise ValueError(loss)


def reference_fit(model,x,y,initial,loss='Cauchy',scale=1,scale_method='Fixed'):
    x=np.asarray(x,float); y=np.asarray(y,float); p0=np.asarray(initial,float)
    units=np.where(p0==0,1,np.abs(p0)); start=p0/units
    def resid(q): return y-equation(model,x,q*units)
    source='Fixed'
    if scale_method=='Pilot MAD':
        pilot=least_squares(lambda q:resid(q)/max(np.max(np.abs(y)),np.finfo(float).tiny),start,
                            ftol=1e-13,gtol=1e-13,xtol=1e-13,max_nfev=20000)
        r=resid(pilot.x); scale=1.482602218505602*float(np.median(np.abs(r-np.median(r))))
        start=pilot.x;source='Pilot MAD'
        if scale==0:
            scale=float(np.quantile(np.abs(r),.6827,method='linear')); source='Absolute residual quantile fallback'
        if scale==0 and np.any(r!=0):
            scale=float(np.median(np.abs(r[r!=0])));source='Positive residual fallback'
        if scale==0:
            return {'parameters':(pilot.x*units).tolist(),'scale':0.,'scale_source':'Exact pilot',
                    'objective':0.,'predicted':y.tolist(),'residuals':np.zeros(len(y)).tolist(),
                    'weights':np.ones(len(y)).tolist(),'raw_ss':0.}
    def objective(q):
        if model=='One-phase decay' and q[2]<0:return 1e100
        if model=='Logistic (4 parameters)' and q[3]<0:return 1e100
        return float(np.sum(rho_weights(resid(q)/scale,loss)[0]))
    # No Trama imports and no robust least_squares loss. Nelder-Mead is intentionally
    # a different route. Tight simplex tolerances; fixtures are small and well identified.
    opt=minimize(objective,start,method='Nelder-Mead',options={'maxiter':40000,'xatol':1e-12,'fatol':1e-12})
    if not opt.success: raise RuntimeError(opt.message)
    p=opt.x*units;pred=equation(model,x,p);r=y-pred;rho,w=rho_weights(r/scale,loss)
    return {'parameters':p.tolist(),'scale':float(scale),'scale_source':source,'objective':float(rho.sum()),
            'predicted':pred.tolist(),'residuals':r.tolist(),'weights':w.tolist(),'raw_ss':float(r@r)}
