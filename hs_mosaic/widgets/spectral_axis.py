"""Shared helpers for spectral-axis unit handling."""

CM_INV_UNIT = "cm\u207b\u00b9"
NM_UNIT = "nm"
INDEX_UNIT = "index"
INDEX_UNIT_DISPLAY = "Index"

_NM_ALIASES = {"nm", "nanometer", "nanometers", "wavelength"}
_INDEX_ALIASES = {
    "index",
    "indices",
    "idx",
    "channel",
    "channels",
    "frame",
    "frames",
}
_CM_INV_ALIASES = {
    "cm-1",
    "cm^-1",
    "cm**-1",
    "1/cm",
    "cm\u207b\u00b9",
    "wavenumber",
    "wavenumbers",
    "raman",
    "raman shift",
}


def normalize_spectral_unit(unit: str | None) -> str:
    """Return the internal unit key: ``cm⁻¹``, ``nm``, or ``index``."""
    raw = "" if unit is None else str(unit).strip()
    key = (
        raw.lower()
        .replace("\u2212", "-")
        .replace("\u207b", "-")
        .replace("\u00b9", "1")
        .replace(" ", "")
    )
    raw_key = raw.lower().strip()
    if key in _NM_ALIASES or raw_key in _NM_ALIASES:
        return NM_UNIT
    if key in _INDEX_ALIASES or raw_key in _INDEX_ALIASES:
        return INDEX_UNIT
    if key in _CM_INV_ALIASES or raw_key in _CM_INV_ALIASES:
        return CM_INV_UNIT
    return CM_INV_UNIT


def spectral_unit_display(unit: str | None) -> str:
    unit = normalize_spectral_unit(unit)
    if unit == NM_UNIT:
        return NM_UNIT
    if unit == INDEX_UNIT:
        return INDEX_UNIT_DISPLAY
    return CM_INV_UNIT


def is_index_unit(unit: str | None) -> bool:
    return normalize_spectral_unit(unit) == INDEX_UNIT


def spectral_axis_label(
        unit: str | None,
        *,
        raman_shift: bool = False,
        parentheses: bool = False,
) -> str:
    unit = normalize_spectral_unit(unit)
    if unit == INDEX_UNIT:
        return "Channel"
    if unit == NM_UNIT:
        return "Wavelength (nm)" if parentheses else "Wavelength [nm]"
    label = "Raman Shift" if raman_shift else "Wavenumber"
    return f"{label} (1/cm)" if parentheses else f"{label} [{CM_INV_UNIT}]"


def spectral_unit_suffix(unit: str | None, *, index_suffix: str = "") -> str:
    unit = normalize_spectral_unit(unit)
    if unit == INDEX_UNIT:
        return index_suffix
    if unit == NM_UNIT:
        return " nm"
    return f" {CM_INV_UNIT}"


def spectral_csv_header(unit: str | None, *, labels: bool = False) -> str:
    if labels:
        return "Channel Label"
    unit = normalize_spectral_unit(unit)
    if unit == INDEX_UNIT:
        return "Channel"
    if unit == NM_UNIT:
        return "Wavelength (nm)"
    return "Wavenumber (1/cm)"
