"""Versioned prompts and reply templates (SPEC-agent, "Prompts"). Their version is stored on
every step, so a recorded answer always matches the question that produced it."""

import string
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from backend.providers.types import ChoiceQuestion, NoulCriteria, NoulQuestion, Option, Question

PROMPTS_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PROMPTS_DIR / "templates"


class _Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    type: Literal["choice"]
    prompt: str
    options: dict[str, str | None]


class _Criteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yes: str
    no: str


class _Noul(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    type: Literal["noul"]
    statement: str
    criteria: _Criteria | None = None


class _QuestionFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    questions: list[Annotated[_Choice | _Noul, Field(discriminator="type")]]


@dataclass(frozen=True)
class QuestionSet:
    version: str
    questions: tuple[Question, ...]


class _ChoicePromptFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    prompt: str


@dataclass(frozen=True)
class ChoicePrompt:
    """A Choice whose options come at run time, such as the clauses search found."""

    version: str
    prompt: str


@cache
def load_choice_prompt(name: str) -> ChoicePrompt:
    """Load a Choice prompt such as `clause-choice-v1`."""
    path = PROMPTS_DIR / f"{name}.yaml"
    parsed = _ChoicePromptFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if parsed.version != name:
        raise ValueError(f"{path.name}: version {parsed.version!r} must match the file name")
    return ChoicePrompt(version=parsed.version, prompt=parsed.prompt)


@cache
def load_prompt(name: str) -> str:
    """A system prompt such as `draft-v1`, sent exactly as written, so its prefix caches."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


@cache
def load_questions(name: str) -> QuestionSet:
    """Load a question file such as `triage-v2`."""
    path = PROMPTS_DIR / f"{name}.yaml"
    # The criteria keys are quoted in the files ("yes", "no"): YAML 1.1 would read bare
    # yes/no as booleans.
    parsed = _QuestionFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if parsed.version != name:
        raise ValueError(f"{path.name}: version {parsed.version!r} must match the file name")
    questions: list[Question] = []
    for question in parsed.questions:
        if isinstance(question, _Choice):
            questions.append(
                ChoiceQuestion(
                    key=question.key,
                    prompt=question.prompt,
                    options=[Option(key=k, description=v) for k, v in question.options.items()],
                )
            )
        else:
            criteria = question.criteria
            questions.append(
                NoulQuestion(
                    key=question.key,
                    statement=question.statement,
                    criteria=NoulCriteria(yes=criteria.yes, no=criteria.no) if criteria else None,
                )
            )
    return QuestionSet(version=parsed.version, questions=tuple(questions))


def render_template(name: str, lang: str, values: Mapping[str, str]) -> str | None:
    """A reply template such as `refunded.en`, or None when there is none for that language.
    Templates use $placeholders, so the {{first_name}} placeholder stays as written."""
    path = TEMPLATES_DIR / f"{name}.{lang}.txt"
    if not path.exists():
        return None
    return string.Template(path.read_text(encoding="utf-8").strip()).substitute(values)
