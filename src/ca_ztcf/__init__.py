"""CA-ZTCF: Coexistence-Aware Zero Trust Continuity Framework (research prototype).

A service-domain Zero Trust continuity function that re-evaluates IoT device trust
at 5G/WiFi access transitions using only evidence that each access domain can
realistically expose, without cross-domain identifier sharing.

This package makes no performance or security claim. Its properties are design
objectives to be evaluated experimentally.
"""

from __future__ import annotations

from ca_ztcf.version import SCHEMA_VERSION, __version__

__all__ = ["SCHEMA_VERSION", "__version__"]
