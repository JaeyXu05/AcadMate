from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import ProviderConfig


class ProviderConfigRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, **values: object) -> ProviderConfig:
        provider_config = ProviderConfig(**values)
        self.session.add(provider_config)
        self.session.flush()
        return provider_config

    def get(self, provider_config_id: int) -> ProviderConfig | None:
        return self.session.get(ProviderConfig, provider_config_id)

    def list(self) -> list[ProviderConfig]:
        return list(self.session.scalars(select(ProviderConfig).order_by(ProviderConfig.id)))

    def get_default(self, kind: str) -> ProviderConfig | None:
        return self.session.scalar(
            select(ProviderConfig).where(ProviderConfig.kind == kind, ProviderConfig.is_default.is_(True))
        )
