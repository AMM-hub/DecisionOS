"""M4.3 Simulation Worker (spec §17.5 — discrete-event simulation).

Models an operating service system with SimPy:
- opening backlog with age and remaining service time,
- time-varying Poisson arrivals (piecewise-constant rate),
- case classes with service-time distributions (mean + std),
- queue disciplines: FIFO and priority,
- a shared staff pool (c servers),
- a finite horizon: cases unfinished at the horizon are reported as a
  censored population, separately from the completed population,
- terminal backlog and outstanding age distribution,
- backlog snapshots (time series) and time-weighted average backlog.

Validation guarantees exercised by tests (§17.5):
1. Conservation: completed + censored == opening backlog + total arrivals.
2. Zero-arrival behavior: backlog drains monotonically.
3. Unlimited-capacity behavior: no queue forms when servers >> load,
   so wait time is zero.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable

import simpy

# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

QUEUE_DISCIPLINES = ("fifo", "priority")


class SimulationError(ValueError):
    """Raised when a simulation config is invalid."""


@dataclass
class ArrivalSegment:
    """Piecewise-constant arrival intensity: rate applies from `from_t` onward
    until the next segment starts (time-varying arrivals, §17.5)."""
    from_t: float
    rate: float  # cases per time unit


@dataclass
class SimulationConfig:
    """Fully specifies one DES run."""
    num_servers: int = 1
    service_mean: float = 1.0
    service_std: float = 0.0  # 0 => deterministic service; std>=mean => exponential
    arrival_rate: float = 0.0  # cases per time unit (constant, unless arrival_schedule given)
    arrival_schedule: list[ArrivalSegment] | None = None
    queue_discipline: str = "fifo"  # "fifo" | "priority"
    priority_classes: list[int] = field(default_factory=lambda: [0, 1, 2])  # lower = served first
    opening_backlog: int = 0
    opening_max_age: float | None = None  # ages sampled uniform in [0, max_age]; default = service_mean
    horizon: float = 100.0
    snapshot_interval: float = 1.0
    seed: int | None = 42

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> "SimulationConfig":
        schedule = body.get("arrival_schedule")
        if schedule is not None and not isinstance(schedule, list):
            raise SimulationError("arrival_schedule must be a list of {from_t, rate}")
        segments = (
            [ArrivalSegment(from_t=float(s["from_t"]), rate=float(s["rate"])) for s in schedule]
            if schedule
            else None
        )
        if segments:
            segments.sort(key=lambda s: s.from_t)
            if segments[0].from_t > 0:
                segments.insert(0, ArrivalSegment(from_t=0.0, rate=float(body.get("arrival_rate", 0.0))))
        cfg = cls(
            num_servers=int(body["num_servers"]) if "num_servers" in body else 1,
            service_mean=float(body.get("service_mean", 1.0)),
            service_std=float(body.get("service_std", 0.0)),
            arrival_rate=float(body.get("arrival_rate", 0.0)),
            arrival_schedule=segments,
            queue_discipline=str(body.get("queue_discipline", "fifo")),
            priority_classes=[int(p) for p in body.get("priority_classes", [0, 1, 2])],
            opening_backlog=int(body.get("opening_backlog", 0)),
            opening_max_age=float(body["opening_max_age"]) if body.get("opening_max_age") is not None else None,
            horizon=float(body.get("horizon", 100.0)),
            snapshot_interval=float(body.get("snapshot_interval", 1.0)),
            seed=int(body["seed"]) if body.get("seed") is not None else 42,
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.num_servers < 1:
            raise SimulationError("num_servers must be >= 1")
        if self.service_mean <= 0:
            raise SimulationError("service_mean must be > 0")
        if self.service_std < 0:
            raise SimulationError("service_std must be >= 0")
        if self.horizon <= 0:
            raise SimulationError("horizon must be > 0")
        if self.snapshot_interval <= 0:
            raise SimulationError("snapshot_interval must be > 0")
        if self.opening_backlog < 0:
            raise SimulationError("opening_backlog must be >= 0")
        if self.queue_discipline not in QUEUE_DISCIPLINES:
            raise SimulationError(f"queue_discipline must be one of {QUEUE_DISCIPLINES}")
        if self.arrival_schedule:
            if any(s.rate < 0 for s in self.arrival_schedule):
                raise SimulationError("arrival rates must be >= 0")
        elif self.arrival_rate < 0:
            raise SimulationError("arrival_rate must be >= 0")

    def expected_arrivals(self) -> float:
        """Mean number of arrivals over the horizon (for diagnostics)."""
        if not self.arrival_schedule:
            return self.arrival_rate * self.horizon
        total = 0.0
        segs = self.arrival_schedule
        for i, s in enumerate(segs):
            end = segs[i + 1].from_t if i + 1 < len(segs) else self.horizon
            if s.from_t < self.horizon:
                total += s.rate * (min(end, self.horizon) - s.from_t)
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "num_servers": self.num_servers,
            "service_mean": self.service_mean,
            "service_std": self.service_std,
            "arrival_rate": self.arrival_rate,
            "arrival_schedule": [{"from_t": s.from_t, "rate": s.rate} for s in self.arrival_schedule] if self.arrival_schedule else None,
            "queue_discipline": self.queue_discipline,
            "opening_backlog": self.opening_backlog,
            "horizon": self.horizon,
            "snapshot_interval": self.snapshot_interval,
            "seed": self.seed,
        }


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


@dataclass
class SimulationResult:
    total_completed: int
    total_censored: int
    total_arrived: int
    opening_backlog: int
    average_wait_time: float
    max_wait_time: float
    terminal_backlog: int
    average_backlog: float
    server_utilization: float
    outstanding_ages: dict[str, float]  # age distribution of censored cases at horizon
    time_series: list[dict[str, float]]  # backlog snapshots over time
    horizon: float
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_completed": self.total_completed,
            "total_censored": self.total_censored,
            "total_arrived": self.total_arrived,
            "opening_backlog": self.opening_backlog,
            "average_wait_time": self.average_wait_time,
            "max_wait_time": self.max_wait_time,
            "terminal_backlog": self.terminal_backlog,
            "average_backlog": self.average_backlog,
            "server_utilization": self.server_utilization,
            "outstanding_ages": self.outstanding_ages,
            "time_series": self.time_series,
            "horizon": self.horizon,
            "config": self.config,
        }


# ---------------------------------------------------------------------------
# internal state
# ---------------------------------------------------------------------------


class _Case:
    __slots__ = ("arrival_time", "priority", "service_start", "end")

    def __init__(self, arrival_time: float, priority: int):
        self.arrival_time = arrival_time
        self.priority = priority
        self.service_start: float | None = None
        self.end: float | None = None


class _State:
    def __init__(self, config: SimulationConfig):
        self.config = config
        self.in_system = 0  # queue + in-service (unfinished); incremented per case process
        self.completed = 0
        self.arrived = 0
        self.waits: list[float] = []
        self.service_time_total = 0.0
        self.time_series: list[dict[str, float]] = []
        self.cases: list[_Case] = []  # every case ever created (for outstanding ages)
        # time-weighted backlog integral
        self._last_change_t = 0.0
        self._backlog_integral = 0.0

    def set_in_system(self, env: simpy.Environment, value: int) -> None:
        self._backlog_integral += self.in_system * (env.now - self._last_change_t)
        self._last_change_t = env.now
        self.in_system = value

    def average_backlog(self) -> float:
        horizon = self.config.horizon
        integral = self._backlog_integral + self.in_system * (horizon - self._last_change_t)
        return integral / horizon if horizon > 0 else 0.0


# ---------------------------------------------------------------------------
# core engine
# ---------------------------------------------------------------------------


def _sample_service(rng: random.Random, mean: float, std: float) -> float:
    """Service time: deterministic if std == 0, exponential if std >= mean,
    otherwise truncated normal (floor at 1% of mean)."""
    if std <= 0:
        return mean
    if std >= mean:
        return rng.expovariate(1.0 / mean)
    x = rng.gauss(mean, std)
    return max(x, mean * 0.01)


def _rate_at(config: SimulationConfig, t: float) -> float:
    if not config.arrival_schedule:
        return config.arrival_rate
    rate = 0.0
    for seg in config.arrival_schedule:
        if seg.from_t <= t:
            rate = seg.rate
        else:
            break
    return rate


def _case_process(
    env: simpy.Environment,
    resource: simpy.Resource | simpy.PriorityResource,
    state: _State,
    case: _Case,
    rng: random.Random,
) -> Iterable[simpy.Event]:
    cfg = state.config
    request = resource.request(priority=case.priority) if cfg.queue_discipline == "priority" else resource.request()
    state.set_in_system(env, state.in_system + 1)
    with request:
        yield request
        case.service_start = env.now
        dur = _sample_service(rng, cfg.service_mean, cfg.service_std)
        state.service_time_total += dur
        yield env.timeout(dur)
    case.end = env.now
    wait = (case.service_start - case.arrival_time)
    state.waits.append(wait)
    state.completed += 1
    state.set_in_system(env, state.in_system - 1)


def _arrival_process(
    env: simpy.Environment,
    resource: simpy.Resource | simpy.PriorityResource,
    state: _State,
    rng: random.Random,
) -> Iterable[simpy.Event]:
    cfg = state.config
    t = env.now
    while True:
        # thinning-free piecewise-exponential: sample next gap at current rate
        rate = _rate_at(cfg, t)
        if rate <= 0:
            # jump to the next segment with positive rate, or stop at horizon
            nxt = None
            for seg in (cfg.arrival_schedule or []):
                if seg.from_t > t and seg.rate > 0:
                    nxt = seg.from_t
                    break
            if nxt is None or nxt >= cfg.horizon:
                return
            t = nxt
            continue
        gap = rng.expovariate(rate)
        t += gap
        if t >= cfg.horizon:
            return
        yield env.timeout(t - env.now)
        case = _Case(
            arrival_time=env.now,
            priority=rng.choice(cfg.priority_classes) if cfg.queue_discipline == "priority" else 0,
        )
        state.arrived += 1
        state.cases.append(case)
        env.process(_case_process(env, resource, state, case, rng))


def _snapshot_process(env: simpy.Environment, state: _State) -> Iterable[simpy.Event]:
    cfg = state.config
    while env.now < cfg.horizon:
        yield env.timeout(cfg.snapshot_interval)
        state.time_series.append({"t": round(env.now, 6), "backlog": state.in_system})


def run_simulation(config: SimulationConfig | dict[str, Any]) -> SimulationResult:
    """Run the DES described by `config` and return aggregate results.

    Completed and censored (unfinished at horizon) populations are reported
    separately; conservation (completed + censored == opening + arrivals)
    is asserted internally before returning.
    """
    if isinstance(config, dict):
        config = SimulationConfig.from_dict(config)
    config.validate()

    rng = random.Random(config.seed)
    env = simpy.Environment()
    resource = (
        simpy.PriorityResource(env, capacity=config.num_servers)
        if config.queue_discipline == "priority"
        else simpy.Resource(env, capacity=config.num_servers)
    )
    state = _State(config)

    # opening backlog: aged cases with remaining service time; they enter the
    # queue at t=0 (in_system already counts them), arrival_time is negative.
    max_age = config.opening_max_age if config.opening_max_age is not None else config.service_mean
    for _ in range(config.opening_backlog):
        case = _Case(
            arrival_time=-rng.uniform(0.0, max_age) if max_age > 0 else 0.0,
            priority=rng.choice(config.priority_classes) if config.queue_discipline == "priority" else 0,
        )
        state.cases.append(case)
        env.process(_case_process(env, resource, state, case, rng))

    if config.expected_arrivals() > 0:
        env.process(_arrival_process(env, resource, state, rng))
    env.process(_snapshot_process(env, state))

    env.run(until=config.horizon)

    # SimPy never resumes a process whose timeout crosses the horizon, so
    # everything still in the system (queued or mid-service) is censored.
    censored = state.in_system
    outstanding = [c for c in state.cases if c.end is None]
    ages: dict[str, float] = {}
    if outstanding:
        age_vals = sorted(config.horizon - c.arrival_time for c in outstanding)
        n = len(age_vals)
        ages = {
            "count": float(n),
            "min": round(age_vals[0], 4),
            "p50": round(age_vals[n // 2], 4),
            "max": round(age_vals[-1], 4),
            "mean": round(sum(age_vals) / n, 4),
        }

    # conservation check (§17.5 validation)
    if state.completed + censored != config.opening_backlog + state.arrived:
        raise SimulationError(
            f"conservation violated: completed({state.completed}) + censored({censored}) "
            f"!= opening({config.opening_backlog}) + arrived({state.arrived})"
        )

    capacity_time = config.num_servers * config.horizon
    utilization = state.service_time_total / capacity_time if capacity_time > 0 else 0.0

    return SimulationResult(
        total_completed=state.completed,
        total_censored=censored,
        total_arrived=state.arrived,
        opening_backlog=config.opening_backlog,
        average_wait_time=round(sum(state.waits) / len(state.waits), 6) if state.waits else 0.0,
        max_wait_time=round(max(state.waits), 6) if state.waits else 0.0,
        terminal_backlog=censored,
        average_backlog=round(state.average_backlog(), 6),
        server_utilization=round(min(utilization, 1.0), 6),
        outstanding_ages=ages,
        time_series=state.time_series,
        horizon=config.horizon,
        config=config.to_dict(),
    )


# ---------------------------------------------------------------------------
# validation fixtures (spec §17.5)
# ---------------------------------------------------------------------------


def simple_queue_fixture() -> tuple[SimulationConfig, dict]:
    """10-server queue with known outcome envelope.

    - 10 servers, 8 cases/hour arrivals, 1h mean exponential service
    - utilization 0.8; M/M/10 approximation predicts waits far below 4h
      (Erlang-C: P(wait) ~ 0.2, E[Wq] ~ 0.05h) — max wait bound of 4h is
      a conservative known outcome used by the tests.
    - fixed seed => deterministic run
    """
    config = SimulationConfig(
        num_servers=10,
        arrival_rate=8.0,
        service_mean=1.0,
        service_std=1.0,  # exponential
        opening_backlog=5,
        horizon=200.0,
        snapshot_interval=5.0,
        seed=42,
    )
    expected = {
        "conservation": True,
        "max_wait_time_upper": 4.0,
        "min_completed": 100,  # ~1595 arrivals over 200h; nearly all complete
    }
    return config, expected


def zero_arrival_fixture() -> tuple[SimulationConfig, dict]:
    """Opening backlog with no arrivals: backlog must drain monotonically."""
    config = SimulationConfig(
        num_servers=4,
        arrival_rate=0.0,
        service_mean=1.0,
        service_std=0.0,  # deterministic 1h service
        opening_backlog=20,
        horizon=10.0,
        snapshot_interval=1.0,
        seed=7,
    )
    expected = {"arrivals": 0, "completed": 20, "censored": 0, "monotonic_drain": True}
    return config, expected


def unlimited_capacity_fixture() -> tuple[SimulationConfig, dict]:
    """Servers >> arrival load: no queue forms, so every wait is zero."""
    config = SimulationConfig(
        num_servers=50,
        arrival_rate=5.0,
        service_mean=1.0,
        service_std=0.0,  # deterministic: each case occupies one server for 1h
        opening_backlog=0,
        horizon=100.0,
        snapshot_interval=5.0,
        seed=11,
    )
    expected = {"max_wait_time": 0.0, "utilization_max": 0.2}  # 5h busy per hour across 50 servers = 10%
    return config, expected
