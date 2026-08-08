from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from backend.db.models import ProviderConfig
from backend.db.types import ProviderKind, ProviderName


def test_provider_config_unique_kind_name(session):
    session.add(
        ProviderConfig(
            name="default",
            kind=ProviderKind.chat.value,
            provider=ProviderName.openai_compatible.value,
            api_key_ref="env:PAPER_CLAW_CHAT_API_KEY",
        )
    )
    session.commit()

    session.add(
        ProviderConfig(
            name="default",
            kind=ProviderKind.chat.value,
            provider=ProviderName.openai_compatible.value,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
