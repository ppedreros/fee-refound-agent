"""Replay mode (D10; SPEC-providers, "Provider modes").

Real answers, recorded from live calls and committed, are served again by the hash of what was
asked: provider, model, prompt version, the masked input and the questions. A miss raises
`replay_miss`, an outage like any other, so the normal fallback follows. Recording wraps a live
adapter and writes one file per answer; only the evals runner records (`--record`, "ask first").
Every file holds masked input only, and a test scans them all for personal data.
"""

import datetime as dt
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from backend.privacy.mask import CARD, EMAIL, NUMBER, PHONE
from backend.providers.types import (
    CallMeta,
    Classification,
    Classifier,
    Draft,
    Drafter,
    DraftInput,
    ProviderUnavailable,
    Question,
)

RECORDINGS_DIR = Path(__file__).resolve().parent / "recordings"

type Provider = Literal["jev", "openai"]


def replay_key(
    *,
    provider: Provider,
    model: str,
    prompt_version: str | None,
    masked_input: Mapping[str, Any],
    questions: Sequence[Mapping[str, Any]] | None,
) -> str:
    """sha256 of the canonical JSON of everything that shapes the answer."""
    asked = {
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "masked_input": masked_input,
        "questions": questions,
    }
    canonical = json.dumps(asked, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReplayStore:
    """`<root>/<provider>/<key[:2]>/<key>.json`."""

    def __init__(self, root: Path = RECORDINGS_DIR) -> None:
        self.root = root

    def path(self, provider: Provider, key: str) -> Path:
        return self.root / provider / key[:2] / f"{key}.json"

    def load(self, provider: Provider, key: str) -> dict[str, Any] | None:
        path = self.path(provider, key)
        if not path.is_file():
            return None
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return record

    def save(self, provider: Provider, key: str, record: Mapping[str, Any]) -> Path:
        path = self.path(provider, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        return path


# --- Classifiers ---


def _classifier_request(
    state: Mapping[str, str], questions: Sequence[Question]
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    return dict(state), [question.model_dump(mode="json") for question in questions]


class ReplayClassifier:
    def __init__(self, store: ReplayStore, *, provider: Provider, model: str) -> None:
        self._store = store
        self._provider: Provider = provider
        self._model = model

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Classification:
        masked_input, asked = _classifier_request(state, questions)
        key = replay_key(
            provider=self._provider,
            model=self._model,
            prompt_version=prompt_version,
            masked_input=masked_input,
            questions=asked,
        )
        record = self._store.load(self._provider, key)
        if record is None:
            raise ProviderUnavailable("replay_miss")
        meta = CallMeta.model_validate(record["meta"]).model_copy(update={"mode": "replay"})
        return Classification.model_validate(
            {"answers": record["response"]["answers"], "meta": meta}
        )


class RecordingClassifier:
    """A live classifier whose answers are written to the store (the evals runner's `--record`)."""

    def __init__(
        self, live: Classifier, store: ReplayStore, *, provider: Provider, model: str
    ) -> None:
        self._live = live
        self._store = store
        self._provider: Provider = provider
        self._model = model

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Classification:
        answer = await self._live.classify(
            state, questions, prompt_version=prompt_version, deadline=deadline
        )
        masked_input, asked = _classifier_request(state, questions)
        key = replay_key(
            provider=self._provider,
            model=self._model,
            prompt_version=prompt_version,
            masked_input=masked_input,
            questions=asked,
        )
        self._store.save(
            self._provider,
            key,
            _record(
                key,
                provider=self._provider,
                model=self._model,
                prompt_version=prompt_version,
                request={"masked_input": masked_input, "questions": asked},
                response={"answers": answer.model_dump(mode="json")["answers"]},
                meta=answer.meta,
            ),
        )
        return answer


# --- Drafter ---


class ReplayDrafter:
    def __init__(self, store: ReplayStore, *, model: str) -> None:
        self._store = store
        self._model = model

    async def draft(
        self,
        payload: DraftInput,
        *,
        instructions: str,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Draft:
        key = _draft_key(self._model, prompt_version, payload)
        record = self._store.load("openai", key)
        if record is None:
            raise ProviderUnavailable("replay_miss")
        meta = CallMeta.model_validate(record["meta"]).model_copy(update={"mode": "replay"})
        return Draft(reply=record["response"]["reply"], meta=meta)


class RecordingDrafter:
    def __init__(self, live: Drafter, store: ReplayStore, *, model: str) -> None:
        self._live = live
        self._store = store
        self._model = model

    async def draft(
        self,
        payload: DraftInput,
        *,
        instructions: str,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Draft:
        drafted = await self._live.draft(
            payload, instructions=instructions, prompt_version=prompt_version, deadline=deadline
        )
        key = _draft_key(self._model, prompt_version, payload)
        self._store.save(
            "openai",
            key,
            _record(
                key,
                provider="openai",
                model=self._model,
                prompt_version=prompt_version,
                request={"masked_input": payload.model_dump(mode="json"), "questions": None},
                response={"reply": drafted.reply},
                meta=drafted.meta,
            ),
        )
        return drafted


def _draft_key(model: str, prompt_version: str | None, payload: DraftInput) -> str:
    return replay_key(
        provider="openai",
        model=model,
        prompt_version=prompt_version,
        masked_input=payload.model_dump(mode="json"),
        questions=None,
    )


def _record(
    key: str,
    *,
    provider: Provider,
    model: str,
    prompt_version: str | None,
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    meta: CallMeta,
) -> dict[str, Any]:
    return {
        # The request's hash (also the file name). Not called "key": that would read as an API key
        # to the secret scanner, which must keep watching recordings for real ones.
        "sha256": key,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "request": dict(request),
        "response": dict(response),
        "meta": meta.model_dump(mode="json"),
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }


# --- The recordings scan (AC9) ---


def find_personal_data(
    text: str, *, names: Iterable[str], account_numbers: Iterable[str]
) -> list[str]:
    """The kinds of personal data in `text`: seeded names and account numbers, then the masking
    patterns (email, phone, card, any other run of six or more digits)."""
    found = []
    if any(re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) for name in names):
        found.append("name")
    if any(number in text for number in account_numbers):
        found.append("account_number")
    for kind, pattern in (("email", EMAIL), ("phone", PHONE), ("card", CARD)):
        if pattern.search(text):
            found.append(kind)
    if NUMBER.search(text):
        found.append("number")
    return found
