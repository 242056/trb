"""Устойчивый разбор JSON из ответов LLM."""

from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def parse_json_lenient(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not text:
        raise json.JSONDecodeError("empty", text, 0)

    try:
        data = json.loads(text, strict=False)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # вырезать первый {...}
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        span = text[start : end + 1]
        try:
            data = json.loads(span, strict=False)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            escaped = re.sub(r",\s*}", "}", span)
            escaped = re.sub(r",\s*]", "]", escaped)
            try:
                data = json.loads(escaped, strict=False)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError as exc:
                try:
                    result = ast.literal_eval(span)
                    if isinstance(result, dict):
                        return result
                except Exception:
                    raise exc from None

    raise json.JSONDecodeError("cannot parse llm json", text, 0)
