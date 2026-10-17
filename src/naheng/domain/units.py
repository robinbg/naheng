"""SI kernel. Positive current is discharge."""
from math import isfinite

SI_UNITS = {"time": "s", "temperature": "K", "current": "A", "voltage": "V", "amount": "mol", "energy": "J", "power": "W", "resistance": "ohm"}

def kelvin(celsius: float) -> float:
    result = celsius + 273.15
    if not isfinite(result) or result <= 0:
        raise ValueError("Temperature must be above absolute zero")
    return result

def kwh(joules: float) -> float:
    return joules / 3_600_000

def validate_units(units: dict[str, str]) -> None:
    if units != SI_UNITS:
        raise ValueError("Kernel unit contract mismatch; convert explicitly before import")
