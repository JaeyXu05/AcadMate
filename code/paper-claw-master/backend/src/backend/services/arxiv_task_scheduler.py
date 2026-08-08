from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, time as day_time

from backend.db.repositories import ArxivTaskRepository
from backend.db.session import get_session
from backend.db.types import ArxivTaskDailyStatus
from backend.services.arxiv_tasks import ArxivTaskService

logger = logging.getLogger(__name__)

_scheduler: ArxivTaskScheduler | None = None


class ArxivTaskScheduler:
    def __init__(self, *, interval_seconds: float = 60.0, daily_time: day_time = day_time(hour=8, tzinfo=UTC)) -> None:
        self.interval_seconds = interval_seconds
        self.daily_time = daily_time
        self._stop_event = threading.Event()
        self._poke_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="arxiv-task-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._poke_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def poke(self) -> None:
        self._poke_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("arXiv task scheduler tick failed")
            self._poke_event.wait(self.interval_seconds)
            self._poke_event.clear()

    def run_once(self) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            with get_session() as session:
                repository = ArxivTaskRepository(session)
                service = ArxivTaskService(session)
                if _daily_due(repository) and repository.active_job() is None:
                    service.enqueue_daily_run()
                service.run_next_queue_step()
        finally:
            self._lock.release()


def start_arxiv_task_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        _scheduler = ArxivTaskScheduler()
    _scheduler.start()


def stop_arxiv_task_scheduler() -> None:
    if _scheduler is not None:
        _scheduler.stop()


def poke_arxiv_task_scheduler() -> None:
    if _scheduler is not None:
        _scheduler.poke()


def _daily_due(repository: ArxivTaskRepository, now: datetime | None = None) -> bool:
    config = repository.daily_config()
    if config.status != ArxivTaskDailyStatus.enabled.value:
        return False
    current = now or datetime.now(UTC)
    if config.last_started_at is not None and config.last_started_at.astimezone(UTC).date() == current.date():
        return False
    return current.timetz() >= _parse_run_time(config.run_time)


def _parse_run_time(value: str) -> day_time:
    try:
        hour_text, minute_text = value.split(":", 1)
        return day_time(hour=int(hour_text), minute=int(minute_text), tzinfo=UTC)
    except Exception:
        return day_time(hour=8, tzinfo=UTC)


def daily_is_due(now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    return current.timetz() >= day_time(hour=8, tzinfo=UTC)
