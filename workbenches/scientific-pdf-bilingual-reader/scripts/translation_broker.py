#!/usr/bin/env python3
"""Shared task-local translation cache for repair and scan pipelines."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
from pathlib import Path


GLOSSARY = {
    "Total": "总计", "PART 3": "第3部分", "Canada": "加拿大", "Japan": "日本",
    "China": "中国", "Korea": "韩国", "Brazil": "巴西", "Barbados": "巴巴多斯",
    "Venezuela": "委内瑞拉", "Mexico": "墨西哥", "Morocco": "摩洛哥",
    "United States": "美国", "European Community": "欧洲共同体",
    "Contracting Parties": "缔约方", "Other Contracting Parties": "其他缔约方",
    "Trinidad & Tobago": "特立尼达和多巴哥",
    "UK (Overseas Territories) (4)": "英国（海外领土）(4)",
    "France (St. Pierre et Miquelon) (4)": "法国（圣皮埃尔和密克隆）(4)",
}


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).replace("\u00ad", "")).strip()


class TranslationBroker:
    """Task-local translation cache with bounded, ID-stable AI batches."""

    def __init__(self, cache_path: Path, *, max_calls: int = 12, batch_size: int = 40,
                 max_batch_chars: int = 8000):
        self.cache_path = cache_path
        try:
            self.cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
        except Exception:
            self.cache = {}
        self.max_calls = max_calls
        self.batch_size = batch_size
        self.max_batch_chars = max_batch_chars
        self.metrics = {"requests": 0, "ai_seconds": 0.0, "cache_hits": 0,
                        "glossary_hits": 0, "unique_ai_items": 0, "unresolved": [], "errors": []}

    @staticmethod
    def cache_key(text: str, instruction: str) -> str:
        payload = "repair-v2\n" + normalized_text(instruction) + "\n" + normalized_text(text)
        return hashlib.sha256(payload.encode()).hexdigest()

    def save(self) -> None:
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.cache_path)

    def _request(self, entries: list[dict], instruction: str) -> dict[str, str]:
        if self.metrics["requests"] >= self.max_calls:
            return {}
        base = os.environ.get("OPENAILIKED_BASE_URL")
        model = os.environ.get("OPENAILIKED_MODEL", "codex")
        key = os.environ.get("OPENAILIKED_API_KEY", "local")
        if not base:
            raise RuntimeError("修复翻译缺少 OPENAILIKED_BASE_URL")
        prompt = (
            instruction
            + "\n输入是带稳定 id 的 JSON 数组。只返回 JSON 数组，每项必须包含原 id 和 translation；"
              "不要省略、合并或改变 id。\n"
            + json.dumps(entries, ensure_ascii=False)
        )
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}).encode()
        request = urllib.request.Request(
            base.rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        started = time.monotonic()
        self.metrics["requests"] += 1
        try:
            with urllib.request.urlopen(request, timeout=100) as response:
                payload = json.loads(response.read())
            content = payload["choices"][0]["message"]["content"].strip()
            match = re.search(r"\[[\s\S]*\]", content)
            decoded = json.loads(match.group(0) if match else content)
            return {
                str(item.get("id")): str(item.get("translation", "")).strip()
                for item in decoded if isinstance(item, dict) and item.get("id") is not None
            }
        except Exception as exc:
            self.metrics["errors"].append(type(exc).__name__)
            return {}
        finally:
            self.metrics["ai_seconds"] += round(time.monotonic() - started, 3)

    def translate(self, texts: list[str], instruction: str) -> list[str]:
        normalized = [normalized_text(text) for text in texts]
        resolved: dict[str, str] = {}
        pending: list[str] = []
        for text in dict.fromkeys(normalized):
            if text in GLOSSARY:
                resolved[text] = GLOSSARY[text]
                self.metrics["glossary_hits"] += 1
                continue
            cache_key = self.cache_key(text, instruction)
            if cache_key in self.cache:
                resolved[text] = self.cache[cache_key]
                self.metrics["cache_hits"] += 1
            else:
                pending.append(text)
        self.metrics["unique_ai_items"] += len(pending)

        batches, current, current_chars = [], [], 0
        for text in pending:
            if current and (len(current) >= self.batch_size or current_chars + len(text) > self.max_batch_chars):
                batches.append(current); current, current_chars = [], 0
            current.append(text); current_chars += len(text)
        if current:
            batches.append(current)

        for batch in batches:
            entries = [{"id": f"t{index}", "text": text} for index, text in enumerate(batch)]
            returned = self._request(entries, instruction)
            missing = []
            for entry in entries:
                translation = returned.get(entry["id"], "")
                if translation:
                    text = entry["text"]
                    resolved[text] = translation
                    self.cache[self.cache_key(text, instruction)] = translation
                else:
                    missing.append(entry)
            if missing and self.metrics["requests"] < self.max_calls:
                retry = self._request(missing, instruction)
                for entry in missing:
                    translation = retry.get(entry["id"], "")
                    if translation:
                        text = entry["text"]
                        resolved[text] = translation
                        self.cache[self.cache_key(text, instruction)] = translation
                    else:
                        self.metrics["unresolved"].append(entry["text"])
        self.save()
        return [resolved.get(text, text) for text in normalized]
