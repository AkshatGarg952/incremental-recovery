"""Classifier eval runner — BUILD.md task 5.8.

Runs the classifier against the golden set and reports accuracy, a
confusion matrix, and what fraction of cases needed an LLM call at all.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.agent.classifier import ClassificationResult, classify_failure
from src.llm.client import ChatClient
from src.simulator.schemas import PaymentFailure, RecoveryClass

_DEFAULT_GOLDEN_SET_PATH = Path("evals/golden_set.jsonl")
_EXCEPTION_LABEL = "exception"


@dataclass
class ClassifierEvalReport:
    total: int
    correct: int
    llm_calls: int
    exceptions: int
    confusion: dict[tuple[str, str], int] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def llm_call_rate(self) -> float:
        return self.llm_calls / self.total if self.total else 0.0

    @property
    def exception_rate(self) -> float:
        return self.exceptions / self.total if self.total else 0.0

    def render(self) -> str:
        lines = [
            f"Classifier eval — {self.total} cases",
            f"  accuracy:       {self.accuracy:.1%} ({self.correct}/{self.total})",
            f"  llm call rate:  {self.llm_call_rate:.1%}",
            f"  exception rate: {self.exception_rate:.1%}",
            "  confusion (gold -> predicted): count",
        ]
        for (gold, predicted), count in sorted(self.confusion.items()):
            lines.append(f"    {gold} -> {predicted}: {count}")
        return "\n".join(lines)


def load_golden_set(
    path: str | Path = _DEFAULT_GOLDEN_SET_PATH,
) -> list[tuple[PaymentFailure, RecoveryClass]]:
    cases: list[tuple[PaymentFailure, RecoveryClass]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            failure = PaymentFailure.model_validate(row["failure"])
            gold = RecoveryClass(row["gold_recovery_class"])
            cases.append((failure, gold))
    return cases


def run_classifier_eval(
    cases: list[tuple[PaymentFailure, RecoveryClass]],
    client: ChatClient,
    model: str,
    prompt_version: str = "v1",
) -> ClassifierEvalReport:
    correct = 0
    llm_calls = 0
    exceptions = 0
    confusion: dict[tuple[str, str], int] = {}

    for failure, gold in cases:
        result: ClassificationResult = classify_failure(failure, client, model, prompt_version)

        if result.source == "llm":
            llm_calls += 1

        predicted_label = result.recovery_class.value if result.recovery_class else _EXCEPTION_LABEL
        if result.recovery_class is None:
            exceptions += 1
        elif result.recovery_class == gold:
            correct += 1

        key = (gold.value, predicted_label)
        confusion[key] = confusion.get(key, 0) + 1

    return ClassifierEvalReport(
        total=len(cases),
        correct=correct,
        llm_calls=llm_calls,
        exceptions=exceptions,
        confusion=confusion,
    )
