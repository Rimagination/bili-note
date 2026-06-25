#!/usr/bin/env python3
"""Run Qwen3-ASR and write a compact JSON transcript result."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def value_from(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def resolve_dtype(torch: Any, requested: str) -> Any:
    if requested == "auto":
        if torch.cuda.is_available():
            return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        return torch.float32
    mapping = {
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float16": torch.float16,
        "fp16": torch.float16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    if requested not in mapping:
        raise ValueError(f"Unsupported dtype: {requested}")
    return mapping[requested]


def resolve_device_map(torch: Any, requested: str) -> str:
    if requested != "auto":
        return requested
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def normalize_language(value: str) -> str:
    key = (value or "").strip().lower()
    if key in {"zh", "zh-cn", "zh_cn", "cn", "chinese", "mandarin"}:
        return "Chinese"
    if key in {"en", "english"}:
        return "English"
    return value or "Chinese"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Qwen3-ASR on one audio file.")
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default="Qwen/Qwen3-ASR-0.6B")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--max-new-tokens", type=int, default=8192)
    parser.add_argument("--chunk-seconds", type=float, default=60.0, help="Split audio into chunks; use 0 to disable.")
    args = parser.parse_args(argv)

    try:
        import torch
        import soundfile as sf
        from qwen_asr import Qwen3ASRModel
    except Exception as exc:
        print(
            "qwen-asr is not available in this Python environment. "
            "Install it in the shared environment with scripts/setup_qwen_asr_env.py, "
            "then pass --qwen-python or set RIMAGINATION_QWEN_PYTHON. "
            f"Import error: {exc}",
            file=sys.stderr,
        )
        return 3

    dtype = resolve_dtype(torch, args.dtype)
    device_map = resolve_device_map(torch, args.device_map)
    language = normalize_language(args.language)
    model = Qwen3ASRModel.from_pretrained(
        args.model,
        dtype=dtype,
        device_map=device_map,
        max_new_tokens=args.max_new_tokens,
        max_inference_batch_size=1,
    )
    segments = transcribe_with_optional_chunks(model, args.audio, language, args.chunk_seconds, sf, torch)
    text = "\n".join(segment["text"] for segment in segments if segment.get("text")).strip()
    output_language = segments[0].get("language", language) if segments else language
    payload = {
        "model": args.model,
        "backend": "qwen3-asr",
        "language": output_language,
        "audio": str(args.audio),
        "device_map": device_map,
        "dtype": str(dtype).replace("torch.", ""),
        "max_new_tokens": args.max_new_tokens,
        "chunk_seconds": args.chunk_seconds,
        "segments": segments,
        "text": text,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "chars": len(text)}, ensure_ascii=False))
    return 0


def transcribe_one(model: Any, audio: Path, language: str) -> dict[str, Any]:
    result = model.transcribe(audio=str(audio), language=language)
    if isinstance(result, list):
        first = result[0] if result else {}
    else:
        first = result
    return {
        "language": value_from(first, "language", language),
        "text": str(value_from(first, "text", "") or "").strip(),
    }


def transcribe_with_optional_chunks(
    model: Any,
    audio_path: Path,
    language: str,
    chunk_seconds: float,
    sf: Any,
    torch: Any,
) -> list[dict[str, Any]]:
    data, sample_rate = sf.read(str(audio_path), always_2d=False)
    total_samples = len(data)
    duration = total_samples / float(sample_rate or 1)
    if chunk_seconds <= 0 or duration <= chunk_seconds * 1.2:
        one = transcribe_one(model, audio_path, language)
        one.update({"start": 0.0, "end": round(duration, 3), "chunk_index": 1})
        return [one]

    chunk_size = max(1, int(sample_rate * chunk_seconds))
    segments: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="qwen3_asr_chunks_") as tmp:
        tmp_dir = Path(tmp)
        for chunk_index, start in enumerate(range(0, total_samples, chunk_size), start=1):
            end = min(start + chunk_size, total_samples)
            if end <= start:
                continue
            chunk_path = tmp_dir / f"chunk_{chunk_index:04d}.wav"
            sf.write(str(chunk_path), data[start:end], sample_rate)
            item = transcribe_one(model, chunk_path, language)
            text = item.get("text", "").strip()
            if text:
                item.update(
                    {
                        "start": round(start / sample_rate, 3),
                        "end": round(end / sample_rate, 3),
                        "chunk_index": chunk_index,
                    }
                )
                segments.append(item)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    return segments


if __name__ == "__main__":
    raise SystemExit(main())
