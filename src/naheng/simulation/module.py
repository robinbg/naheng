"""Four-series-cell synthetic module with shared current and heat coupling."""
from dataclasses import dataclass
import math
import numpy as np
from scipy.integrate import solve_ivp

from naheng.models.site_model import DomainError, SiteModel


@dataclass(frozen=True)
class ModuleResult:
    state: np.ndarray
    energy_J: float
    elapsed_s: float
    events: list[dict]
    inventory_residual_mol: list[float]
    thermal_management_energy_J: float
    topology: str = "4s"


class ModuleModel:
    topology = "4s"
    cell_count = 4

    def __init__(self, cells: tuple[SiteModel, ...] | None = None, coupling_W_per_K: float = .04):
        self.cells = cells or tuple(SiteModel() for _ in range(4))
        if len(self.cells) != 4:
            raise DomainError("declared 4s topology requires exactly four cells")
        if not math.isfinite(coupling_W_per_K) or coupling_W_per_K < 0:
            raise DomainError("thermal coupling must be finite and nonnegative")
        self.coupling_W_per_K = coupling_W_per_K

    def initial_state(self, soc=.6, temperature_K=298.15):
        socs = [soc]*4 if np.isscalar(soc) else soc
        temperatures = [temperature_K]*4 if np.isscalar(temperature_K) else temperature_K
        if len(socs) != 4 or len(temperatures) != 4:
            raise DomainError("module initialization requires four cell values")
        return np.array([m.initial_state(s,t) for m,s,t in zip(self.cells,socs,temperatures)])

    def _validate(self, state):
        state = np.asarray(state,dtype=float)
        if state.shape != (4,5): raise DomainError("module state must have shape (4,5)")
        for model,s in zip(self.cells,state): model._validate_state(s,numerical_tolerance=1e-8)
        return state

    def coupling_heat_W(self, state):
        state = self._validate(state)
        flows = np.zeros(4)
        for i in range(3):
            heat = self.coupling_W_per_K*(state[i+1,4]-state[i,4])
            flows[i] += heat
            flows[i+1] -= heat
        return flows

    def observe(self, state, current_A):
        state = self._validate(state)
        cells = [m.observe(s,current_A) for m,s in zip(self.cells,state)]
        return {"voltage_V":sum(x["voltage_V"] for x in cells), "current_A":current_A,
                "cell_observations":cells,"topology":"4s"}

    def rhs(self, t, state, current_A, ambient_K=298.15, thermal_W=0.0):
        state = self._validate(state)
        coupling = self.coupling_heat_W(state)
        return np.array([m.rhs(t,s,current_A,ambient_K,thermal_W/4+heat)
                         for m,s,heat in zip(self.cells,state,coupling)])

    def integrate(self, state, current_A, duration_s, ambient_K=298.15, thermal_W=0.0, max_step_s=60):
        initial = self._validate(state).copy()
        if not all(math.isfinite(value) for value in (duration_s,max_step_s,current_A,ambient_K,thermal_W)) or duration_s <= 0 or max_step_s <= 0 or ambient_K<=0:
            raise DomainError("module duration and step must be positive")
        self.observe(initial,current_A)
        event_functions, descriptions = [], []
        for index,model in enumerate(self.cells):
            p = model.params
            for name,limit,sign,field in (("voltage_low",p.voltage_min_V,1,"voltage_V"),
                                          ("voltage_high",p.voltage_max_V,-1,"voltage_V"),
                                          ("temperature_low",p.temperature_min_K,1,"temperature_K"),
                                          ("temperature_high",p.temperature_max_K,-1,"temperature_K"),
                                          ("reservoir_depleted",0,1,"reservoir_mol")):
                def event(t,aug,index=index,model=model,limit=limit,sign=sign,field=field):
                    s = aug[:20].reshape(4,5)[index]
                    value = s[3] if field == "reservoir_mol" else (s[4] if field == "temperature_K" else model.observe(s,current_A)["voltage_V"])
                    return sign*(value-limit)
                event.terminal, event.direction = True, -1
                event_functions.append(event)
                descriptions.append((index,name,limit,field))
        start = np.r_[initial.ravel(),0.0]
        initial_events = [i for i,event in enumerate(event_functions) if event(0,start) <= 0]
        if initial_events:
            return ModuleResult(initial,0,0,[{"cell_id":f"cell-{descriptions[i][0]+1}","name":descriptions[i][1],"time_s":0,"limit":descriptions[i][2]} for i in initial_events],[0.]*4,0)
        def rhs(t,aug):
            states = aug[:20].reshape(4,5)
            return np.r_[self.rhs(t,states,current_A,ambient_K,thermal_W).ravel(),current_A*self.observe(states,current_A)["voltage_V"]]
        result = solve_ivp(rhs,(0,duration_s),start,rtol=1e-7,atol=1e-10,max_step=min(max_step_s,duration_s),events=event_functions)
        if not result.success: raise RuntimeError(result.message)
        final = result.y[:20,-1].reshape(4,5)
        elapsed = float(result.t[-1])
        events = []
        for i,times in enumerate(result.t_events):
            for time,aug in zip(times,result.y_events[i]):
                index,name,limit,field = descriptions[i]
                s = aug[:20].reshape(4,5)[index]
                actual = float(s[3] if field=="reservoir_mol" else (s[4] if field=="temperature_K" else self.cells[index].observe(s,current_A)["voltage_V"]))
                events.append({"cell_id":f"cell-{index+1}","name":name,"time_s":float(time),"limit":limit,"value":actual,"direction":"exit"})
        residuals = [m.inventory_mol(after)-m.inventory_mol(before) for m,after,before in zip(self.cells,final,initial)]
        electrical_thermal = sum(abs(thermal_W/4)*elapsed/m.params.thermal_cop for m in self.cells)
        return ModuleResult(final,float(result.y[20,-1]),elapsed,events,residuals,electrical_thermal)
