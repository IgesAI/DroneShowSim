"""Show time domain.

Canonical choreography time is monotonic seconds from 0. Wall-clock, GNSS and
timecode values never enter the compiled show; they are mapped in by a TimeAxis
at execution time.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

ClockType = Literal["simulation", "gnss", "mavlink", "smpte", "midi"]


@runtime_checkable
class ShowClock(Protocol):
    """Source of canonical show time in seconds."""

    clockType: ClockType

    def now(self) -> float: ...


class SimulationShowClock:
    """Deterministic clock driven by the simulator rather than the OS.

    Time only moves when `advance`/`seek` is called, so a compile or a test
    never depends on how long it took to run.
    """

    clockType: ClockType = "simulation"

    def __init__(self, start: float = 0.0, rate: float = 1.0) -> None:
        self._t = max(0.0, float(start))
        self._rate = float(rate)
        self._running = True

    def now(self) -> float:
        return self._t

    def advance(self, dt: float) -> float:
        """Advance by `dt` external seconds, scaled by rate while running."""
        if self._running and dt > 0:
            self._t += dt * self._rate
        return self._t

    def seek(self, t: float) -> float:
        self._t = max(0.0, float(t))
        return self._t

    def pause(self) -> None:
        self._running = False

    def resume(self) -> None:
        self._running = True

    @property
    def running(self) -> bool:
        return self._running

    @property
    def rate(self) -> float:
        return self._rate

    def set_rate(self, rate: float) -> None:
        self._rate = max(0.0, float(rate))


class TimeAxis:
    """Maps external clock → show time → scene time.

    `offset` is the external instant at which show time 0 occurs. `rate` lets a
    future adapter run the show slower than real time without touching any
    compiled trajectory.
    """

    def __init__(self, clock: ShowClock, offset: float = 0.0, rate: float = 1.0) -> None:
        self.clock = clock
        self.offset = float(offset)
        self.rate = max(1e-6, float(rate))

    def show_time(self, external: float | None = None) -> float:
        ext = self.clock.now() if external is None else float(external)
        return max(0.0, (ext - self.offset) * self.rate)

    def external_time(self, show_time: float) -> float:
        return self.offset + float(show_time) / self.rate

    def scene_time(self, show_time: float, scene_start: float) -> float:
        return float(show_time) - float(scene_start)

    def normalized_scene_time(self, show_time: float, scene_start: float, scene_duration: float) -> float:
        if scene_duration <= 1e-9:
            return 0.0
        u = (float(show_time) - float(scene_start)) / float(scene_duration)
        return min(1.0, max(0.0, u))


ExecutionState = Literal[
    "UNLOADED",
    "LOADED",
    "READY",
    "AUTHORIZED",
    "WAITING",
    "RUNNING",
    "SUSPENDED",
    "COMPLETED",
    "ABORTED",
]

EXECUTION_TRANSITIONS: dict[ExecutionState, tuple[ExecutionState, ...]] = {
    "UNLOADED": ("LOADED",),
    "LOADED": ("READY", "UNLOADED"),
    "READY": ("AUTHORIZED", "LOADED", "ABORTED"),
    "AUTHORIZED": ("WAITING", "READY", "ABORTED"),
    "WAITING": ("RUNNING", "ABORTED"),
    "RUNNING": ("SUSPENDED", "COMPLETED", "ABORTED"),
    "SUSPENDED": ("RUNNING", "ABORTED"),
    "COMPLETED": ("UNLOADED",),
    "ABORTED": ("UNLOADED",),
}


class ShowExecutionConfig(BaseModel):
    """How a compiled show is started. Deliberately not part of the show data."""

    startMethod: Literal["manual", "scheduled", "external-trigger"] = "manual"
    startClockType: ClockType = "simulation"
    scheduledStartTime: float | None = None
    authorizationState: Literal["none", "requested", "granted", "revoked"] = "none"
    state: ExecutionState = "UNLOADED"
    rate: float = 1.0
    notes: list[str] = Field(default_factory=list)

    def can_transition(self, target: ExecutionState) -> bool:
        return target in EXECUTION_TRANSITIONS.get(self.state, ())

    def transition(self, target: ExecutionState) -> "ShowExecutionConfig":
        if not self.can_transition(target):
            raise ValueError(f"illegal execution transition {self.state} -> {target}")
        return self.model_copy(update={"state": target})
