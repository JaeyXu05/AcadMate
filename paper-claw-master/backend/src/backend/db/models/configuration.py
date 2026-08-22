from __future__ import annotations

from sqlalchemy import Boolean, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, JsonDict, JsonObject, TimestampMixin
from backend.db.types import ProviderKind, ProviderName


class ProviderConfig(TimestampMixin, Base):
    __tablename__ = "provider_configs"
    __table_args__ = (UniqueConstraint("kind", "name", name="uq_provider_configs_kind_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default=ProviderKind.chat.value, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), default=ProviderName.openai_compatible.value, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(1000))
    model: Mapped[str | None] = mapped_column(String(255))
    api_key_ref: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float | None] = mapped_column(Float)
    settings_json: Mapped[JsonDict] = mapped_column(JsonObject, default=dict, nullable=False)
