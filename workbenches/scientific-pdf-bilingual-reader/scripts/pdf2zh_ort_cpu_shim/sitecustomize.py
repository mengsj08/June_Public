"""Force ONNX Runtime away from CoreML when explicitly requested.

This module is loaded only when its directory is placed on PYTHONPATH. The
workbench does that for the CPU fallback retry, never for the healthy path.
"""

from __future__ import annotations

import os


def _provider_name(provider) -> str:
    if isinstance(provider, (tuple, list)) and provider:
        return str(provider[0])
    return str(provider)


def _cpu_only_providers(providers):
    if not providers:
        return ["CPUExecutionProvider"]
    filtered = [
        provider for provider in providers
        if _provider_name(provider) != "CoreMLExecutionProvider"
    ]
    names = {_provider_name(provider) for provider in filtered}
    if "CPUExecutionProvider" not in names:
        filtered.append("CPUExecutionProvider")
    return filtered


def _install() -> None:
    if os.environ.get("PDF_READER_ORT_CPU_ONLY") != "1":
        return
    try:
        import onnxruntime
    except Exception:
        return

    original_session = getattr(onnxruntime, "InferenceSession", None)
    if original_session and not getattr(original_session, "_pdf_reader_cpu_only", False):
        def inference_session(*args, **kwargs):
            if len(args) >= 3:
                args = list(args)
                args[2] = _cpu_only_providers(args[2])
                args = tuple(args)
            else:
                kwargs["providers"] = _cpu_only_providers(kwargs.get("providers"))
            return original_session(*args, **kwargs)

        inference_session._pdf_reader_cpu_only = True
        onnxruntime.InferenceSession = inference_session

    original_available = getattr(onnxruntime, "get_available_providers", None)
    if original_available and not getattr(original_available, "_pdf_reader_cpu_only", False):
        def get_available_providers():
            return _cpu_only_providers(original_available())

        get_available_providers._pdf_reader_cpu_only = True
        onnxruntime.get_available_providers = get_available_providers


_install()
