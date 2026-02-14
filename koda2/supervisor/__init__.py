"""Koda2 Self-Healing & Self-Improving Supervisor.

Components:
- ProcessMonitor: spawns, watches, and restarts the Koda2 process
- RepairEngine: LLM-powered crash analysis and code repair
- EvolutionEngine: self-improvement via plan → apply → test → commit (with self-correction)
- SafetyGuard: git-based safety net, audit logging, retry limits
- ContinuousLearner: background loop that gathers signals and queues improvements
- SupervisorNotifier: WhatsApp/log notifications for supervisor events
- ImprovementQueue: persistent queue with concurrent workers
"""

from koda2.supervisor.monitor import ProcessMonitor
from koda2.supervisor.repair import RepairEngine
from koda2.supervisor.evolution import EvolutionEngine
from koda2.supervisor.safety import SafetyGuard
from koda2.supervisor.learner import ContinuousLearner
from koda2.supervisor.notifier import SupervisorNotifier

__all__ = [
    "ProcessMonitor",
    "RepairEngine",
    "EvolutionEngine",
    "SafetyGuard",
    "ContinuousLearner",
    "SupervisorNotifier",
]
