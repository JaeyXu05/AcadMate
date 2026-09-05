"""Local dense embeddings backed by FastEmbed/ONNX.

The model is cached per process.  This keeps PDF analysis independent from an
external embedding endpoint while still using a real multilingual semantic
retriever instead of token overlap.
"""

from __future__ import annotations

import os
from functools import lru_cache

from backend.schemas import ResolvedProviderConfig

_HF_MIRROR = "https://hf-mirror.com"
_HF_OFFICIAL = "https://huggingface.co"


def _apply_hf_env(provider: ResolvedProviderConfig) -> None:
    """把镜像/离线开关写入进程环境，并强制 huggingface_hub 重读。

    huggingface_hub 在 import 时就把 ``constants.ENDPOINT`` 固化了，所以这里
    既写 ``os.environ`` 也直接改写 ``constants``，两种路径都生效。
    """
    hf_endpoint = str(provider.settings.get("hf_endpoint") or "").strip() or _HF_OFFICIAL
    _set_hf_endpoint(hf_endpoint)
    # FastEmbed's Xet transport is fragile behind mirrors/proxies.  Downloads
    # still work with Xet disabled and it avoids hard-to-debug first-run
    # timeouts, so keep Xet off for every endpoint.
    _set_hf_disable_xet()


def _set_hf_endpoint(hf_endpoint: str) -> None:
    os.environ["HF_ENDPOINT"] = hf_endpoint
    try:
        import huggingface_hub.constants as _constants

        _constants.ENDPOINT = hf_endpoint
    except Exception:  # noqa: BLE001 - hugginface_hub optional
        pass
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


def _set_hf_disable_xet() -> None:
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    try:
        import huggingface_hub.constants as _constants

        _constants.HF_HUB_DISABLE_XET = "1"  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - huggingface_hub optional
        pass


@lru_cache(maxsize=4)
def _model(model_name: str, cache_dir: str | None):
    from fastembed import TextEmbedding  # lazy import: 确保上面的 env 先设置

    kwargs: dict[str, object] = {"model_name": model_name}
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    return TextEmbedding(**kwargs)


class FastEmbedEmbeddingAdapter:
    def embed_texts(
        self, provider: ResolvedProviderConfig, texts: list[str]
    ) -> list[list[float]]:
        if not provider.model:
            raise ValueError("A local embedding model name is required.")
        _apply_hf_env(provider)
        cache_dir = str(provider.settings.get("cache_dir") or "") or None
        configured_endpoint = (
            str(provider.settings.get("hf_endpoint") or "").strip() or _HF_OFFICIAL
        )
        candidates = [configured_endpoint]
        for candidate in (_HF_MIRROR, _HF_OFFICIAL):
            if candidate not in candidates:
                candidates.append(candidate)
        last_error: Exception | None = None
        for endpoint in candidates:
            _set_hf_endpoint(endpoint)
            _set_hf_disable_xet()
            try:
                model = _model(provider.model, cache_dir)
                return [vector.astype(float).tolist() for vector in model.embed(texts)]
            except Exception as exc:  # noqa: BLE001 - retry with the next endpoint
                last_error = exc
        assert last_error is not None
        raise last_error
