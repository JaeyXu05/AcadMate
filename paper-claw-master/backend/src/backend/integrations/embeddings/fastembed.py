"""Local dense embeddings backed by FastEmbed/ONNX.

The model is cached per process.  This keeps PDF analysis independent from an
external embedding endpoint while still using a real multilingual semantic
retriever instead of token overlap.
"""

from __future__ import annotations

import os
from functools import lru_cache

from backend.schemas import ResolvedProviderConfig


def _apply_hf_env(provider: ResolvedProviderConfig) -> None:
    """把镜像/离线开关写入进程环境，并强制 huggingface_hub 重读。

    huggingface_hub 在 import 时就把 ``constants.ENDPOINT`` 固化了，所以这里
    既写 ``os.environ`` 也直接改写 ``constants``，两种路径都生效。
    """
    hf_endpoint = str(provider.settings.get("hf_endpoint") or "").strip()
    if hf_endpoint:
        os.environ.setdefault("HF_ENDPOINT", hf_endpoint)
    if str(provider.settings.get("hf_disable_xet", "")).strip().casefold() in {
        "1",
        "true",
        "yes",
    }:
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    # Reflect into huggingface_hub.constants (already imported by fastembed),
    # otherwise the global ENDPOINT stays frozen at the compiled-in default.
    try:
        import huggingface_hub.constants as _constants

        if hf_endpoint:
            _constants.ENDPOINT = hf_endpoint
        if _constants is not None and os.environ.get("HF_HUB_DISABLE_XET"):
            # Xet 开关常量在 huggingface_hub.utils / file_download 中读取；
            # 环境变量已设置即可，这里保证后续 imported 进程一致。
            pass
    except Exception:  # noqa: BLE001 - hugginface_hub optional
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
        model = _model(provider.model, cache_dir)
        return [vector.astype(float).tolist() for vector in model.embed(texts)]
