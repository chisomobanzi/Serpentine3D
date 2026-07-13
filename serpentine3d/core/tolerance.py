"""Document tolerance policy.

One absolute modelling tolerance, expressed in document units, used
consistently across joins, sewing, splits and closure tests instead of
scattered magic numbers. `units` changes rescale it implicitly because
model numbers stay numerically the same.
"""

from __future__ import annotations

_ABS_TOL = 1e-3          # modelling tolerance in document units
_TIGHT_FACTOR = 1e-3     # for "same point" style identity tests


def tol() -> float:
    """The document's absolute modelling tolerance."""
    return _ABS_TOL


def tight() -> float:
    """Identity tolerance (coincident points, closure tests)."""
    return _ABS_TOL * _TIGHT_FACTOR


def set_tolerance(value: float):
    global _ABS_TOL
    if value <= 0:
        raise ValueError("Tolerance must be positive")
    _ABS_TOL = float(value)
