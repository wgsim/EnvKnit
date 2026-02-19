"""
Security vulnerability scanning for EnvKnit.

Provides vulnerability detection and update recommendations
for installed packages.
"""

from envknit.security.models import (
    ScanResult,
    UpdateRecommendation,
    Vulnerability,
    VulnerabilitySeverity,
)
from envknit.security.scanner import VulnerabilityScanner

__all__ = [
    "Vulnerability",
    "VulnerabilitySeverity",
    "ScanResult",
    "UpdateRecommendation",
    "VulnerabilityScanner",
]
