"""Print queue records and submission evidence, separate from display wording.

Existing order JSON remains a dictionary at storage boundaries. PrintItem is the
typed view used by queue display and mutations; unknown record keys are retained.
"""

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NotRequired, TypedDict


class SubmissionState(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    UNCERTAIN = "uncertain"


class OrderState(StrEnum):
    SUBMITTED = "submitted"
    PREFLIGHT_FAILED = "preflight_failed"
    UNCERTAIN = "uncertain"


@dataclass
class SubmissionResult:
    payload: dict
    state: OrderState
    error: str = ""

    @property
    def status(self) -> str:
        labels = {
            OrderState.SUBMITTED: "已提交",
            OrderState.PREFLIGHT_FAILED: "提交前检查失败（未提交任何任务）：",
            OrderState.UNCERTAIN: "需核对：",
        }
        return labels[self.state] + self.error


class PrintOptions(TypedDict):
    paper: str
    color: str
    duplex: str
    copies: int
    dpi: NotRequired[int]
    printer: NotRequired[str]
    paper_mm: NotRequired[list[float]]
    range: NotRequired[str]
    fit: NotRequired[str]
    pdf_fit: NotRequired[str]
    orientation: NotRequired[str]
    landscape: NotRequired[bool]
    quality_level: NotRequired[str]


class PrintItemRecord(TypedDict):
    source: str
    prepared: str | list[str]
    kind: str
    count: int
    selected: list[int]
    options: PrintOptions
    status: str
    submission_state: NotRequired[str]
    submitted_copies: NotRequired[int]
    last_order_id: NotRequired[str]
    printer: NotRequired[str]
    source_files: NotRequired[list[str]]
    coverage: NotRequired[dict[str, Any]]
    engine: NotRequired[str]
    quality_name: NotRequired[str]
    queue_id: NotRequired[str]
    preview_margins: NotRequired[tuple[float, float, float, float]]


@dataclass
class PrintItem:
    """A queue record with explicit state transitions, preserving order evidence."""

    record: PrintItemRecord

    @property
    def submission_state(self) -> SubmissionState:
        code = self.record.get("submission_state")
        if code is not None:
            return SubmissionState(code)
        # Compatibility for in-memory records created before this version.
        if self.record.get("status", "").startswith("已提交"):
            return SubmissionState.SUBMITTED
        if self.record.get("status", "").startswith("需核对"):
            return SubmissionState.UNCERTAIN
        return SubmissionState.PENDING

    @property
    def needs_repeat_confirmation(self) -> bool:
        return (
            self.submission_state != SubmissionState.PENDING
            or self.record.get("submitted_copies", 0) > 0
        )

    def apply_options(self, options: dict, selected: list[int]) -> None:
        state = self.submission_state
        self.record.update(options=deepcopy(options), selected=list(selected))
        self.record["submission_state"] = state.value
        self.record["status"] = {
            SubmissionState.PENDING: "待打印",
            SubmissionState.SUBMITTED: "已提交 · 设置已修改",
            SubmissionState.UNCERTAIN: "需核对 · 设置已修改",
        }[state]
        self.record.pop("coverage", None)

    def finish_submission(
        self, order_id: str, copies: int, state: SubmissionState
    ) -> None:
        self.record["last_order_id"] = order_id
        self.record["submitted_copies"] = max(
            copies, self.record.get("submitted_copies", 0)
        )
        self.record["submission_state"] = state.value
        self.record["status"] = {
            SubmissionState.PENDING: "待打印",
            SubmissionState.SUBMITTED: "已提交",
            SubmissionState.UNCERTAIN: "需核对",
        }[state]
