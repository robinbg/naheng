"""Validated model registry and bounded expression execution.

Executable is a software capability; it is not a formal evidence category.
The built-in chemistry backend remains the declared synthetic SiteModel.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import inspect
import json
import math
from pathlib import Path
from collections.abc import Mapping
from fractions import Fraction

from naheng.domain.expressions import Expression, ExpressionError, parse_expression, expression_from_dict
from .domain_check import check_domain

_DERIVED={"package_hash","validation_status","execution_binding","parameter_hash","binding_hashes","evidence_validity"}
_ZERO=(Fraction(0),)*5
# Dimension basis: seconds, amperes, volts, kelvin, mol.
_UNITS={"1":_ZERO,"s":(1,0,0,0,0),"A":(0,1,0,0,0),"V":(0,0,1,0,0),"K":(0,0,0,1,0),"mol":(0,0,0,0,1),
        "s^-1":(-1,0,0,0,0),"mol/s":(-1,0,0,0,1),"K/s":(-1,0,0,1,0),"A/s":(-1,1,0,0,0),"V/s":(-1,0,1,0,0),
        "C":(1,1,0,0,0),"C/mol":(1,1,0,0,-1),"J":(1,1,1,0,0),"W":(0,1,1,0,0),"ohm":(0,-1,1,0,0),
        "J/K":(1,1,1,-1,0),"W/K":(0,1,1,-1,0),"J/mol":(1,1,1,0,-1)}
_INPUT_UNITS={"current_A":"A","ambient_K":"K","thermal_W":"W","time_s":"s"}

def content_hash(value) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

def _dimension(unit):
    if not isinstance(unit,str) or unit not in _UNITS:raise ValueError(f"Unsupported SI unit: {unit}")
    return tuple(Fraction(x) for x in _UNITS[unit])

def _finite(value,name):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError(f"Finite real value required: {name}")
    return float(value)

def _infer(expression: Expression, units):
    op=expression.op
    if op=="const":return None if expression.value==0 else _ZERO
    if op=="var":return units[str(expression.value)]
    dims=[_infer(arg,units) for arg in expression.args]
    if op in {"add","sub","min","max"}:
        concrete=[dim for dim in dims if dim is not None]
        if concrete and any(dim!=concrete[0] for dim in concrete):raise ValueError("Incompatible units in additive expression")
        return concrete[0] if concrete else None
    if op in {"neg","abs"}:return dims[0]
    if op in {"exp","log"}:
        if dims[0] not in (None,_ZERO):raise ValueError(f"{op} requires a dimensionless argument")
        return _ZERO
    if op=="sqrt":return None if dims[0] is None else tuple(x/2 for x in dims[0])
    if op=="mul":return None if None in dims else tuple(a+b for a,b in zip(*dims))
    if op=="div":
        if dims[1] is None:raise ValueError("Literal zero divisor")
        return None if dims[0] is None else tuple(a-b for a,b in zip(*dims))
    if op=="pow":
        if dims[1] not in (None,_ZERO):raise ValueError("Exponent must be dimensionless")
        if dims[0] in (None,_ZERO):return dims[0]
        exponent=expression.args[1]
        if exponent.op!="const" or abs(float(exponent.value))>8:raise ValueError("Dimensional powers require a bounded constant exponent")
        return tuple(x*Fraction(str(exponent.value)) for x in dims[0])
    raise ValueError(f"Unknown typed AST operator: {op}")

def _compile(value,variable_units,expected_unit):
    allowed=set(variable_units)
    expression=parse_expression(value,allowed) if isinstance(value,str) else expression_from_dict(value,allowed)
    dim=_infer(expression,{name:_dimension(unit) for name,unit in variable_units.items()})
    if dim is not None and dim!=_dimension(expected_unit):raise ValueError(f"Expression output unit does not match {expected_unit}")
    return expression

class ModelRegistry:
    def __init__(self, root: Path):
        self.root=Path(root).resolve()
        self.packages={}
        self._programs={}

    def _path(self,name):
        if not isinstance(name,str) or not name:raise ValueError("Controlled source path required")
        path=(self.root/name).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():raise ValueError("Model source/artifact must be a project file")
        return path

    def _stale(self,package_id,reason):
        if package_id in self.packages:self.packages[package_id]["evidence_validity"]="stale"
        raise ValueError(reason)

    def _program(self,package):
        dynamics=package["dynamics_ast"]
        states=package.get("state_definition")
        if not dynamics or not states:return {"kind":"metadata_only"}
        if not isinstance(states,dict) or not states or any(not isinstance(n,str) or not n.isidentifier() or n.startswith("_") for n in states):raise ValueError("Invalid state definition")
        for unit in states.values():_dimension(unit)
        domain=package["domain"]
        if not isinstance(domain,dict) or "temperature_K" not in domain or "max_current_A" not in domain:raise ValueError("Declared physical domain required")
        temperatures=domain["temperature_K"]
        if not isinstance(temperatures,(tuple,list)) or len(temperatures)!=2 or not 0<_finite(temperatures[0],"lower K")<_finite(temperatures[1],"upper K"):raise ValueError("Invalid temperature domain")
        if _finite(domain["max_current_A"],"max current")<=0:raise ValueError("Positive model current limit required")
        hashes={}
        for name,expected in package.get("artifact_hashes",{}).items():
            path=self._path(name);actual=hashlib.sha256(path.read_bytes()).hexdigest()
            if actual!=expected:raise ValueError("Artifact checksum mismatch invalidates dependency evidence")
            hashes[name]=actual
        maps={}
        if dynamics.get("model")=="two_site_current_adapter_v1":
            from naheng.models.site_model import SiteModel, SiteParameters
            if set(dynamics)-{"model","states","source"}:raise ValueError("Unknown built-in dynamics fields")
            if states!=dict(zip(SiteModel.state_names,SiteModel.state_units)) or dynamics.get("states")!=list(SiteModel.state_names):raise ValueError("State names/order/units mismatch with built-in chemistry")
            if package.get("readout_ast")!={"model":"synthetic_voltage_thermal_v1"}:raise ValueError("Unknown built-in readout")
            parameters=dict(package.get("parameters",{}))
            for name in ("site_capacity_mol","rate_s_inv","equilibrium_drive_V","side_rate_s_inv"):
                if name in parameters:parameters[name]=tuple(parameters[name])
            defaults=asdict(SiteParameters())
            if set(parameters)-set(defaults):raise ValueError("Unknown built-in parameter")
            for name,value in parameters.items():
                if isinstance(defaults[name],(tuple,list)):
                    if len(value)!=2:raise ValueError("Two site parameter values required")
                    for item in value:_finite(item,name)
                elif type(defaults[name]) is bool:
                    if type(value) is not bool:raise ValueError("Boolean flag required")
                elif type(defaults[name]) is str:
                    if not isinstance(value,str) or not value:raise ValueError("Explicit parameter provenance required")
                    if name=="model_kind" and value!="theory_fixture":raise ValueError("Synthetic built-in cannot become public measurements")
                else:_finite(value,name)
            try:model=SiteModel(SiteParameters(**parameters))
            except (TypeError,ValueError) as error:raise ValueError("Invalid built-in parameters") from error
            for name,value in asdict(model.params).items():
                if isinstance(value,(list,tuple)):
                    for item in value:_finite(item,name)
                elif type(value) in (int,float):_finite(value,name)
            source=self._path(dynamics.get("source"))
            hashes[dynamics["source"]]=hashlib.sha256(source.read_bytes()).hexdigest()
            source_file=Path(inspect.getsourcefile(SiteModel)).resolve()
            if not source_file.is_relative_to(self.root):raise ValueError("Built-in implementation must be inside controlled project root")
            hashes[source_file.relative_to(self.root).as_posix()]=hashlib.sha256(source_file.read_bytes()).hexdigest()
            for dependency in (source_file.with_name("thermal.py"),source_file.with_name("degradation.py")):
                if not dependency.is_file():raise ValueError("Built-in dependency missing")
                hashes[dependency.relative_to(self.root).as_posix()]=hashlib.sha256(dependency.read_bytes()).hexdigest()
            variable_units={**states,**_INPUT_UNITS,"N1":"mol","N2":"mol"}
            for name,value in package.get("reduction_map",{}).items():
                if name!="q":raise ValueError("Undeclared reduction output/unit")
                maps[name]=_compile(value,variable_units,"mol")
            return {"kind":"builtin_site_v1","model":model,"maps":maps,"hashes":hashes,"parameter_hash":content_hash(asdict(model.params))}
        if dynamics.get("kind")!="expressions_v1":raise ValueError("Unknown model binding; arbitrary dynamic code is forbidden")
        if set(dynamics)-{"kind","expressions","input_units","parameters","derivative_units"}:raise ValueError("Unknown expression-program fields")
        input_units=dynamics.get("input_units",{})
        if not isinstance(input_units,dict) or any(name in states for name in input_units):raise ValueError("Input/state symbols must be disjoint")
        for name,unit in input_units.items():
            if name not in _INPUT_UNITS or unit!=_INPUT_UNITS[name]:raise ValueError("Input unit or semantics mismatch")
        parameters=dynamics.get("parameters",{})
        variable_units={**states,**input_units};parameter_values={}
        for name,spec in parameters.items():
            if not name.isidentifier() or name.startswith("_") or name in variable_units or not isinstance(spec,dict) or set(spec)!={"value","unit","source_id"}:raise ValueError("Invalid parameter declaration")
            if not isinstance(spec["source_id"],str) or not spec["source_id"]:raise ValueError("Parameter source required")
            _dimension(spec["unit"]);variable_units[name]=spec["unit"];parameter_values[name]=_finite(spec["value"],name)
        expressions=dynamics.get("expressions",{});derivative_units=dynamics.get("derivative_units",{})
        if set(expressions)!=set(states) or set(derivative_units)!=set(states):raise ValueError("Every state requires exactly one derivative")
        compiled={}
        for name,value in expressions.items():
            target=tuple(a-b for a,b in zip(_dimension(states[name]),_dimension("s")))
            if _dimension(derivative_units[name])!=target:raise ValueError("Derivative unit must be state unit per second")
            compiled[name]=_compile(value,variable_units,derivative_units[name])
        readout=package.get("readout_ast",{})
        if set(readout)!={"expressions","units"} or set(readout["expressions"])!=set(readout["units"]):raise ValueError("Readout expressions require explicit matching units")
        readouts={name:_compile(value,variable_units,readout["units"][name]) for name,value in readout["expressions"].items()}
        if package.get("reduction_map"):raise ValueError("Generic reduction map needs a declared output-unit schema; not implemented")
        return {"kind":"expressions_v1","dynamics":compiled,"readouts":readouts,"parameters":parameter_values,"input_units":input_units,"hashes":hashes,"parameter_hash":content_hash(parameters)}

    def register(self,package: dict,expected_hash: str | None=None):
        mandatory={"package_id","chemistry_id","parameter_revision","dynamics_ast","domain","evidence_refs"}
        if not isinstance(package,dict) or not mandatory.issubset(package):raise ValueError("Incomplete model package")
        if package["chemistry_id"]!="synthetic_two_site":raise ValueError("Chemistry identity mismatch")
        if any(not isinstance(package[k],str) or not package[k] for k in ("package_id","parameter_revision")):raise ValueError("Package/revision identity required")
        if not isinstance(package["dynamics_ast"],dict) or not isinstance(package["domain"],dict):raise ValueError("Dynamics/domain must be structured")
        if not isinstance(package["evidence_refs"],list) or any(not isinstance(ref,str) or not ref for ref in package["evidence_refs"]):raise ValueError("Evidence references must be explicit identifiers")
        payload={key:value for key,value in package.items() if key not in _DERIVED}
        actual=content_hash(payload)
        if expected_hash is not None and actual!=expected_hash:self._stale(package["package_id"],"Changed package invalidates evidence")
        program=self._program(payload)
        stored=json.loads(json.dumps(payload,allow_nan=False))
        stored.update(package_hash=actual,validation_status="metadata_only" if program["kind"]=="metadata_only" else "executable",execution_binding=program["kind"],parameter_hash=program.get("parameter_hash"),binding_hashes=program.get("hashes",{}),evidence_validity="unverified")
        self.packages[package["package_id"]]=stored;self._programs[package["package_id"]]=program
        return json.loads(json.dumps({k:v for k,v in stored.items() if k not in _DERIVED or k=="package_hash"}))

    def _fresh(self,package_id):
        stored=self.packages[package_id]
        if stored["evidence_validity"]=="stale":raise ValueError("Model package dependencies are stale")
        if content_hash({k:v for k,v in stored.items() if k not in _DERIVED})!=stored["package_hash"]:self._stale(package_id,"Stored expression/parameters changed; re-register required")
        for name,expected in stored["binding_hashes"].items():
            if hashlib.sha256(self._path(name).read_bytes()).hexdigest()!=expected:self._stale(package_id,"Bound implementation or source changed; evidence is stale")
        return stored

    def evaluate(self,package_id,state: Mapping[str,float],inputs: Mapping[str,float],*,parameter_revision: str):
        package=self._fresh(package_id);program=self._programs[package_id]
        if program["kind"]=="metadata_only":raise ValueError("Metadata-only registration is not executable")
        if parameter_revision!=package["parameter_revision"]:raise ValueError("Parameter revision is stale")
        if set(state)!=set(package["state_definition"]):raise ValueError("State semantics mismatch")
        state={name:_finite(value,name) for name,value in state.items()}
        allowed=set(_INPUT_UNITS if program["kind"]=="builtin_site_v1" else program["input_units"])
        if set(inputs)-allowed:raise ValueError("Undeclared inputs cannot enter model execution")
        inputs={name:_finite(value,name) for name,value in inputs.items()}
        if "temperature_K" in state and not package["domain"]["temperature_K"][0]<=state["temperature_K"]<=package["domain"]["temperature_K"][1]:raise ValueError("State temperature outside declared model domain")
        if "current_A" in inputs and abs(inputs["current_A"])>package["domain"]["max_current_A"]:raise ValueError("Current outside declared model domain")
        if "ambient_K" in inputs and not package["domain"]["temperature_K"][0]<=inputs["ambient_K"]<=package["domain"]["temperature_K"][1]:raise ValueError("Ambient temperature outside declared model domain")
        if program["kind"]=="builtin_site_v1":
            if not {"current_A","ambient_K"}.issubset(inputs):raise ValueError("Current and ambient temperature inputs are required")
            model=program["model"];vector=[state[name] for name in model.state_names]
            current=inputs["current_A"];ambient=inputs["ambient_K"]
            derivatives=model.rhs(inputs.get("time_s",0),vector,current,ambient,inputs.get("thermal_W",0))
            dynamics=dict(zip(model.state_names,map(float,derivatives)));readouts=model.observe(vector,current)
            values={**state,**inputs,"N1":model.params.site_capacity_mol[0],"N2":model.params.site_capacity_mol[1]}
            reductions={name:expr.evaluate(values) for name,expr in program["maps"].items()}
        else:
            if set(inputs)!=set(program["input_units"]):raise ValueError("All declared inputs are required")
            values={**state,**inputs,**program["parameters"]}
            dynamics={name:expr.evaluate(values) for name,expr in program["dynamics"].items()}
            readouts={name:expr.evaluate(values) for name,expr in program["readouts"].items()};reductions={}
        return {"package_id":package_id,"package_hash":package["package_hash"],"parameter_revision":parameter_revision,"parameter_hash":package["parameter_hash"],"binding":program["kind"],"dynamics":dynamics,"readouts":readouts,"reduction":reductions,"evidence_validity":package["evidence_validity"],"formal_coverage":"unverified; executable AST is not a proved error contract"}

    def applicable(self,package_id,snapshot,ambient_K=298.15):
        try:package=self._fresh(package_id)
        except ValueError as error:return {"status":"FAIL","reason":str(error),"checks":[],"evidence_validity":"stale"}
        if snapshot.model_package_id!=package_id:raise ValueError("Snapshot model package mismatch")
        if package["validation_status"]!="executable":return {"status":"UNKNOWN","reason":"Metadata-only package cannot authorize execution","checks":[]}
        if snapshot.parameter_revision!=package["parameter_revision"]:return {"status":"FAIL","reason":"Parameter revision is stale","checks":[]}
        for name,unit in package["state_definition"].items():
            if name not in snapshot.state_names:return {"status":"UNKNOWN","reason":"State semantics missing","checks":[]}
            if snapshot.state_units[snapshot.state_names.index(name)]!=unit:return {"status":"FAIL","reason":"Snapshot unit mismatch","checks":[]}
        checks=check_domain(package,snapshot,ambient_K)
        status="FAIL" if any(c["status"]=="FAIL" for c in checks) else "UNKNOWN" if any(c["status"]=="UNKNOWN" for c in checks) else "PASS"
        return {"status":status,"checks":checks,"evidence_validity":package["evidence_validity"],"scope":"represented posterior samples; not a full-support or formal certificate"}
