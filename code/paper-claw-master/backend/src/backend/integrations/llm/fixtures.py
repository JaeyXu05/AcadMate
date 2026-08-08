from __future__ import annotations

from backend.schemas import ResolvedProviderConfig


class FixtureChatModelAdapter:
    def generate_text(self, provider: ResolvedProviderConfig, messages: list[dict]) -> str:
        user_content = "\n".join(str(message.get("content", "")) for message in messages if message.get("role") == "user")
        title = provider.settings.get("title", "Fixture Report")
        return (
            f"# {title}\n\n"
            "## Part I: Story & Method\n\n"
            f"This fixture report summarizes the supplied paper content and instructions. {user_content[:500]}\n\n"
            "## Part II: Experiments & Findings\n\n"
            "This fixture report describes experimental evidence, findings, and limitations when present in the supplied context.\n\n"
            "## Part III: Summary & Critique\n\n"
            "This fixture report provides a concise critique grounded in the supplied evidence chunks or processed paper body.\n\n"
            "## Evidence\n\nThis fixture report cites the supplied evidence chunks."
        )
