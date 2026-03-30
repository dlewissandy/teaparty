"""Human presence tracking — dynamic proxy handoff.

Tracks which levels of the team hierarchy the human currently occupies.
When the human is present at a level, gates at that level route directly
to the human; the proxy observes and records observation chunks.  When
the human departs, the proxy resumes with fresh observation data.

Issue #202.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum


class PresenceLevel(Enum):
    """Levels in the team hierarchy where a human can be present."""
    OFFICE_MANAGER = 'office_manager'
    PROJECT = 'project'
    SUBTEAM = 'subteam'


# CfA states that map to each presence level.
_STATE_TO_LEVEL: dict[str, PresenceLevel] = {
    'INTENT_ASSERT': PresenceLevel.PROJECT,
    'INTENT_ESCALATE': PresenceLevel.PROJECT,
    'PLAN_ASSERT': PresenceLevel.PROJECT,
    'PLANNING_ESCALATE': PresenceLevel.PROJECT,
    'WORK_ASSERT': PresenceLevel.PROJECT,
    'WORK_ESCALATE': PresenceLevel.PROJECT,
    'TASK_ASSERT': PresenceLevel.SUBTEAM,
    'TASK_ESCALATE': PresenceLevel.SUBTEAM,
    'OFFICE_MANAGER': PresenceLevel.OFFICE_MANAGER,
}

# States where the proxy never escalates BY DEFAULT (when human is absent).
# This is the original static set from actors.py.
_DEFAULT_NEVER_ESCALATE: frozenset[str] = frozenset({
    'TASK_ASSERT',
    'TASK_ESCALATE',
})


@dataclass
class Observation:
    """An observation recorded during direct human participation."""
    state: str
    team: str
    human_response: str
    context: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class _PresenceEntry:
    """Internal tracking for a single presence at a level+team."""
    arrival_time: float
    observations: list[Observation] = field(default_factory=list)


class HumanPresence:
    """Tracks where the human is currently present in the hierarchy.

    Thread-safe: arrive/depart/is_present can be called from any thread.
    The proxy checks presence at gate time to decide routing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Key: (PresenceLevel, team) where team='' for non-subteam levels
        self._entries: dict[tuple[PresenceLevel, str], _PresenceEntry] = {}

    @staticmethod
    def _key(level: PresenceLevel, team: str = '') -> tuple[PresenceLevel, str]:
        # Subteam presence is team-scoped; others use empty string
        if level == PresenceLevel.SUBTEAM:
            return (level, team)
        return (level, '')

    def arrive(self, level: PresenceLevel, *, team: str = '') -> None:
        """Human arrives at the given level. Proxy steps aside."""
        key = self._key(level, team)
        with self._lock:
            if key not in self._entries:
                self._entries[key] = _PresenceEntry(arrival_time=time.time())

    def depart(self, level: PresenceLevel, *, team: str = '') -> list[Observation]:
        """Human departs the given level. Returns accumulated observations.

        The returned observations should be fed to the proxy as fresh
        learning material (ACT-R memory chunks).
        """
        key = self._key(level, team)
        with self._lock:
            entry = self._entries.pop(key, None)
        if entry is None:
            return []
        return entry.observations

    def is_present(self, level: PresenceLevel, *, team: str = '') -> bool:
        """Check whether the human is present at the given level."""
        key = self._key(level, team)
        with self._lock:
            return key in self._entries

    def active_levels(self) -> list[tuple[PresenceLevel, str]]:
        """Return all levels where the human is currently present."""
        with self._lock:
            return list(self._entries.keys())

    def arrival_time(self, level: PresenceLevel, *, team: str = '') -> float | None:
        """Return the timestamp when the human arrived, or None."""
        key = self._key(level, team)
        with self._lock:
            entry = self._entries.get(key)
            return entry.arrival_time if entry else None

    def human_should_answer(self, state: str, *, team: str = '') -> bool:
        """Should the human answer this gate directly (vs proxy)?

        Returns True when the human is present at the level that
        corresponds to the given CfA state.
        """
        level = _STATE_TO_LEVEL.get(state)
        if level is None:
            return False
        return self.is_present(level, team=team)

    def record_observation(
        self,
        level: PresenceLevel,
        team: str,
        state: str,
        human_response: str,
        context: str,
    ) -> Observation | None:
        """Record what the human did during direct participation.

        Returns the Observation, or None if the human is not present
        at the specified level.
        """
        key = self._key(level, team)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            obs = Observation(
                state=state,
                team=team,
                human_response=human_response,
                context=context,
            )
            entry.observations.append(obs)
            return obs

    def get_observations(
        self, level: PresenceLevel, *, team: str = '',
    ) -> list[Observation]:
        """Return observations accumulated so far (without departing)."""
        key = self._key(level, team)
        with self._lock:
            entry = self._entries.get(key)
            return list(entry.observations) if entry else []


def should_never_escalate(
    state: str,
    presence: HumanPresence | None,
    *,
    team: str = '',
) -> bool:
    """Should this state never escalate to the human?

    When presence is None (no tracking configured), uses the original
    static set for backward compatibility.

    When presence is provided and the human is present at the level
    corresponding to the state, the state becomes escalatable (returns False).
    """
    if presence is None:
        return state in _DEFAULT_NEVER_ESCALATE

    if state not in _DEFAULT_NEVER_ESCALATE:
        return False

    # Human present at the relevant level → allow escalation
    if presence.human_should_answer(state, team=team):
        return False

    return True
