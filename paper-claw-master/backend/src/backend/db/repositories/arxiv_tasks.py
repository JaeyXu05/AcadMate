from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.db.models import ArxivTaskDailyConfig, ArxivTaskHarvestJob, ArxivTaskPaper, ArxivTaskPaperSubscription, ArxivTaskQueryWindow, ArxivTaskSubscription
from backend.db.types import ArxivTaskDailyStatus, ArxivTaskJobKind, ArxivTaskJobStatus, ArxivTaskWindowStatus


class ArxivTaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def daily_config(self) -> ArxivTaskDailyConfig:
        config = self.session.scalar(select(ArxivTaskDailyConfig).order_by(ArxivTaskDailyConfig.id).limit(1))
        if config is None:
            config = ArxivTaskDailyConfig(status=ArxivTaskDailyStatus.enabled.value, run_time="08:00", metadata_json={})
            self.session.add(config)
            self.session.flush()
        return config

    def update_daily_config(self, *, enabled: bool, run_time: str) -> ArxivTaskDailyConfig:
        config = self.daily_config()
        config.status = ArxivTaskDailyStatus.enabled.value if enabled else ArxivTaskDailyStatus.disabled.value
        config.run_time = run_time
        self.session.flush()
        return config

    def list_subscriptions(self) -> list[ArxivTaskSubscription]:
        return list(
            self.session.scalars(
                select(ArxivTaskSubscription).order_by(ArxivTaskSubscription.name, ArxivTaskSubscription.id)
            )
        )

    def get_subscription(self, subscription_id: int) -> ArxivTaskSubscription | None:
        return self.session.get(ArxivTaskSubscription, subscription_id)

    def enabled_subscriptions(self) -> list[ArxivTaskSubscription]:
        return list(self.session.scalars(select(ArxivTaskSubscription).where(ArxivTaskSubscription.enabled.is_(True)).order_by(ArxivTaskSubscription.name, ArxivTaskSubscription.id)))

    def create_subscription(self, *, name: str, query: str, description: str | None, enabled: bool) -> ArxivTaskSubscription:
        subscription = ArxivTaskSubscription(name=name, query=query, description=description, enabled=enabled)
        self.session.add(subscription)
        self.session.flush()
        return subscription

    def update_subscription(self, subscription: ArxivTaskSubscription, *, name: str, query: str, description: str | None, enabled: bool) -> ArxivTaskSubscription:
        subscription.name = name
        subscription.query = query
        subscription.description = description
        subscription.enabled = enabled
        self.session.flush()
        return subscription

    def delete_subscription(self, subscription_id: int) -> bool:
        result = self.session.execute(delete(ArxivTaskSubscription).where(ArxivTaskSubscription.id == subscription_id))
        self.session.flush()
        return bool(result.rowcount)

    def create_job(self, kind: str, subscription_ids: list[int], **values: Any) -> ArxivTaskHarvestJob:
        job = ArxivTaskHarvestJob(kind=kind, subscription_ids_json=subscription_ids, **values)
        self.session.add(job)
        self.session.flush()
        return job

    def list_jobs(self, *, limit: int = 20) -> list[ArxivTaskHarvestJob]:
        return list(self.session.scalars(select(ArxivTaskHarvestJob).order_by(ArxivTaskHarvestJob.created_at.desc()).limit(limit)))

    def running_job(self) -> ArxivTaskHarvestJob | None:
        return self.session.scalar(select(ArxivTaskHarvestJob).where(ArxivTaskHarvestJob.status == ArxivTaskJobStatus.running.value).order_by(ArxivTaskHarvestJob.updated_at.desc()))

    def active_job(self) -> ArxivTaskHarvestJob | None:
        return self.session.scalar(
            select(ArxivTaskHarvestJob)
            .where(ArxivTaskHarvestJob.status.in_([ArxivTaskJobStatus.pending.value, ArxivTaskJobStatus.running.value, ArxivTaskJobStatus.stopping.value]))
            .order_by(ArxivTaskHarvestJob.updated_at.desc())
        )

    def next_pending_job(self) -> ArxivTaskHarvestJob | None:
        return self.session.scalar(
            select(ArxivTaskHarvestJob)
            .where(ArxivTaskHarvestJob.status == ArxivTaskJobStatus.pending.value)
            .order_by(ArxivTaskHarvestJob.created_at, ArxivTaskHarvestJob.id)
            .limit(1)
        )

    def list_running_history_jobs(self) -> list[ArxivTaskHarvestJob]:
        return list(
            self.session.scalars(
                select(ArxivTaskHarvestJob)
                .where(ArxivTaskHarvestJob.kind == ArxivTaskJobKind.history.value, ArxivTaskHarvestJob.status == ArxivTaskJobStatus.running.value)
                .order_by(ArxivTaskHarvestJob.updated_at)
            )
        )

    def create_window(self, subscription_id: int, query_snapshot: str, window_start: datetime, window_end: datetime, **values: Any) -> ArxivTaskQueryWindow:
        window = ArxivTaskQueryWindow(subscription_id=subscription_id, query_snapshot=query_snapshot, window_start=window_start, window_end=window_end, **values)
        self.session.add(window)
        self.session.flush()
        return window

    def list_windows(self, *, subscription_id: int | None = None, limit: int = 100) -> list[ArxivTaskQueryWindow]:
        statement = select(ArxivTaskQueryWindow).order_by(ArxivTaskQueryWindow.window_start.desc(), ArxivTaskQueryWindow.id.desc()).limit(limit)
        if subscription_id is not None:
            statement = statement.where(ArxivTaskQueryWindow.subscription_id == subscription_id)
        return list(self.session.scalars(statement))

    def successful_subscription_ids_with_papers(self) -> list[int]:
        rows = self.session.execute(select(ArxivTaskPaperSubscription.subscription_id).distinct().order_by(ArxivTaskPaperSubscription.subscription_id)).all()
        return [row[0] for row in rows]

    def latest_successful_window_end(self, subscription_id: int) -> datetime | None:
        return self.session.scalar(
            select(func.max(ArxivTaskQueryWindow.window_end)).where(
                ArxivTaskQueryWindow.subscription_id == subscription_id,
                ArxivTaskQueryWindow.status == ArxivTaskWindowStatus.succeeded.value,
            )
        )

    def list_papers(self, *, subscription_id: int | None = None, published_start: datetime | None = None, published_end: datetime | None = None, limit: int = 50, offset: int = 0) -> list[ArxivTaskPaper]:
        statement = select(ArxivTaskPaper).order_by(ArxivTaskPaper.published_at.desc().nullslast(), ArxivTaskPaper.id.desc()).limit(limit).offset(offset)
        if subscription_id is not None:
            statement = statement.join(ArxivTaskPaperSubscription).where(ArxivTaskPaperSubscription.subscription_id == subscription_id)
        if published_start is not None:
            statement = statement.where(ArxivTaskPaper.published_at >= published_start)
        if published_end is not None:
            statement = statement.where(ArxivTaskPaper.published_at < published_end)
        return list(self.session.scalars(statement))

    def count_papers(self) -> int:
        return int(self.session.scalar(select(func.count(ArxivTaskPaper.id))) or 0)

    def upsert_paper(self, *, arxiv_base_id: str, values: dict[str, Any], now: datetime) -> tuple[ArxivTaskPaper, bool]:
        paper = self.session.scalar(select(ArxivTaskPaper).where(ArxivTaskPaper.arxiv_base_id == arxiv_base_id))
        inserted = paper is None
        if paper is None:
            paper = ArxivTaskPaper(arxiv_base_id=arxiv_base_id, first_seen_at=now, last_seen_at=now, **values)
            self.session.add(paper)
        else:
            for key, value in values.items():
                setattr(paper, key, value)
            paper.last_seen_at = now
        self.session.flush()
        return paper, inserted

    def upsert_paper_subscription(self, paper_id: int, subscription_id: int, *, query_snapshot: str) -> ArxivTaskPaperSubscription:
        link = self.session.scalar(select(ArxivTaskPaperSubscription).where(ArxivTaskPaperSubscription.paper_id == paper_id, ArxivTaskPaperSubscription.subscription_id == subscription_id))
        if link is None:
            link = ArxivTaskPaperSubscription(paper_id=paper_id, subscription_id=subscription_id, query_snapshot=query_snapshot, created_at=datetime.now().astimezone())
            self.session.add(link)
        else:
            link.query_snapshot = query_snapshot
        self.session.flush()
        return link
