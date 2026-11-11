"""Groq chat-completions client.

* Preferred models come from config.GROQ_MODELS and are filtered against Groq's
  live /models list (cached 1h) so retired models are skipped automatically.
* On failure it falls through to the next model; if every model fails it RAISES
  AIError. (The old code returned an error *string*, which could end up being
  committed to a user's repo as if it were generated code.)
* Responses are never logged — they can contain private repo contents.
"""

import json
import logging
import re
import threading
import time
from typing import List, Optional

import requests

import config

log = logging.getLogger("gitsetlive.ai")

GROQ_URL = "https://api.groq.com/openai/v1"


class AIError(Exception):
    pass


_models_lock = threading.Lock()
_models_cache = {"at": 0.0, "ids": None}


def _active_models() -> Optional[set]:
    with _models_lock:
        if _models_cache["ids"] is not None and time.time() - _models_cache["at"] < 3600:
            return _models_cache["ids"]
    try:
        r = requests.get(f"{GROQ_URL}/models", headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}, timeout=10)
        if r.status_code == 200:
            ids = {m["id"] for m in r.json().get("data", []) if m.get("active", True)}
            with _models_lock:
                _models_cache.update(at=time.time(), ids=ids)
            return ids
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


def candidate_models() -> List[str]:
    preferred = list(config.GROQ_MODELS)
    active = _active_models()
    if active:
        usable = [m for m in preferred if m in active]
        if usable:
            return usable
    return preferred


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def chat(messages: List[dict], *, temperature: float = 0.2, max_tokens: int = 4096, timeout: int = 90) -> str:
    if not config.GROQ_API_KEY:
        raise AIError("AI is not configured on this server (GROQ_API_KEY is missing).")

    last_err = "unknown error"
    for model in candidate_models():
        body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"  # keep the token budget for the actual answer
        try:
            r = requests.post(
                f"{GROQ_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}", "Content-Type": "application/json"},
                json=body, timeout=timeout,
            )
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            last_err = f"{model}: {type(e).__name__}"
            log.warning("AI call failed on %s: %s", model, type(e).__name__)
            continue

        if r.status_code == 200 and data.get("choices"):
            text = (data["choices"][0].get("message") or {}).get("content") or ""
            text = _THINK_RE.sub("", text).strip()
            if text:
                return text
            last_err = f"{model}: empty response"
            continue

        err = data.get("error", {}) if isinstance(data, dict) else {}
        last_err = f"{model}: {err.get('message', f'HTTP {r.status_code}')[:160]}"
        log.warning("AI model %s unavailable (HTTP %s)", model, r.status_code)
        if r.status_code == 401:
            raise AIError("The Groq API key was rejected. Check GROQ_API_KEY on the server.")

    raise AIError(f"The AI service is unavailable right now ({last_err}). Please try again in a minute.")


def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply, tolerating fences and chatter."""
    if not text:
        raise AIError("The AI returned an empty answer.")
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", "", text.strip())
    decoder = json.JSONDecoder()
    for i, ch in enumerate(cleaned):
        if ch in "[{":
            try:
                obj, _ = decoder.raw_decode(cleaned[i:])
                return obj
            except ValueError:
                continue
    raise AIError("The AI answer wasn't valid JSON. Please try again.")


def chat_json(messages: List[dict], **kwargs):
    """chat() + extract_json(), with one retry that reminds the model to return JSON only."""
    first = chat(messages, **kwargs)
    try:
        return extract_json(first)
    except AIError:
        retry = messages + [
            {"role": "assistant", "content": first[:2000]},
            {"role": "user", "content": "That was not valid JSON. Reply again with ONLY the JSON, no prose, no markdown fences."},
        ]
        return extract_json(chat(retry, **kwargs))
