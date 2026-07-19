"""Deterministic reference portfolio simulation."""

from quantresearch.simulation.brackets import (
    BracketExitReason,
    BracketResolution,
    resolve_long_bracket,
)
from quantresearch.simulation.demand import DemandSimulationConfig, DemandTradeSimulator
from quantresearch.simulation.metrics import PerformanceReport, calculate_performance
from quantresearch.simulation.models import Bar, Signal, SignalAction, SimulationConfig
from quantresearch.simulation.reference import ReferenceSimulator

__all__ = [
    "Bar",
    "BracketExitReason",
    "BracketResolution",
    "DemandSimulationConfig",
    "DemandTradeSimulator",
    "PerformanceReport",
    "ReferenceSimulator",
    "Signal",
    "SignalAction",
    "SimulationConfig",
    "calculate_performance",
    "resolve_long_bracket",
]
