"""
Core module for dependency resolution and environment management.

This module provides:
- Dependency graph construction and analysis
- Version conflict resolution using PubGrub algorithm
- Lock file generation and management
"""

from envknit.core.graph import DependencyGraph, PackageNode
from envknit.core.lock import (
    Alternative,
    Dependency,
    DependencyGraphLock,
    GraphEdge,
    GraphNode,
    LegacyLockFile,
    LockedPackage,
    LockFile,
    ResolutionLogEntry,
    SelectionReason,
)
from envknit.core.resolver import (
    Conflict,
    DecisionAction,
    DecisionLog,
    PackageCandidate,
    PubGrubResolver,
    Resolution,
    Resolver,
    VersionConstraint,
)

__all__ = [
    # Resolver classes
    "Resolver",
    "PubGrubResolver",
    "Resolution",
    "VersionConstraint",
    "Conflict",
    "DecisionAction",
    "DecisionLog",
    "PackageCandidate",
    # Graph classes
    "DependencyGraph",
    "PackageNode",
    # Lock file classes
    "LockFile",
    "LockedPackage",
    "SelectionReason",
    "Alternative",
    "Dependency",
    "GraphNode",
    "GraphEdge",
    "DependencyGraphLock",
    "ResolutionLogEntry",
    "LegacyLockFile",
]
