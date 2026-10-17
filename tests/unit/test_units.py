import pytest
from naheng.domain.units import kelvin, kwh, validate_units, SI_UNITS

def test_conversions_and_invalid_units():
    assert kelvin(25) == 298.15
    assert kwh(3_600_000) == 1
    with pytest.raises(ValueError): kelvin(-300)
    with pytest.raises(ValueError): validate_units({**SI_UNITS,"temperature":"C"})
