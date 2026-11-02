"""Submit an already confirmed order with complete preflight before first output."""

import logging
from pathlib import Path
from typing import Callable

from print_models import OrderState, SubmissionResult
from quality import resolve

logger = logging.getLogger(__name__)


def submit_order(
    payload: dict,
    configuration: dict,
    progress: Callable[[str], None],
    cancelled: Callable[[], bool],
    make_printer: Callable,
    render: Callable,
) -> SubmissionResult:
    """Count only completed copies; any failure after preflight requires queue audit."""
    from printing import preview_margins
    from windows_driver import driver_identity, print_item

    order_id = payload["order_id"]
    preflight_finished = False
    jobs = payload["items"] + (
        [payload["receipt_item"]] if payload.get("receipt_item") else []
    )
    try:
        for name in dict.fromkeys(item["printer"] for item in jobs):
            try:
                logger.info(
                    "Order %s printer=%s driver=%s",
                    order_id,
                    name,
                    driver_identity(name),
                )
            except Exception:
                logger.warning(
                    "Order %s could not read driver metadata: printer=%s",
                    order_id,
                    name,
                )
        for item in jobs:
            progress("提交前检查：" + Path(item["source"]).name)
            preview_margins(item, configuration)
        preflight_finished = True
        for index, item in enumerate(jobs):
            for copy in range(item["options"]["copies"]):
                if cancelled():
                    raise RuntimeError("已停止后续提交，请核对系统打印队列")
                progress(f"正在提交 {Path(item['source']).name} · 第{copy + 1}份")
                quality = resolve(configuration, item["printer"], item["options"])
                item["options"]["dpi"] = quality["dpi"]
                item["quality_name"] = quality["label"]
                logger.info(
                    "Order %s item %d copy %d printer=%s options=%s",
                    order_id,
                    index,
                    copy + 1,
                    item["printer"],
                    {
                        key: item["options"].get(key)
                        for key in ("paper", "color", "duplex", "dpi")
                    },
                )
                if quality["profile"]:
                    logger.info(
                        "Order %s driver fingerprint=%s",
                        order_id,
                        quality["profile"].get("driver"),
                    )
                    print_item(item, quality["profile"], cancelled)
                else:
                    printer = make_printer(item["printer"], item["options"])
                    render(item, printer, cancelled)
                item["submitted_copies"] += 1
        logger.info("Order %s submitted", order_id)
        payload["submission_state"] = OrderState.SUBMITTED.value
        return SubmissionResult(payload, OrderState.SUBMITTED)
    except Exception as error:
        logger.exception(
            "Order %s failed; preflight_finished=%s", order_id, preflight_finished
        )
        state = (
            OrderState.UNCERTAIN if preflight_finished else OrderState.PREFLIGHT_FAILED
        )
        payload["submission_state"] = state.value
        return SubmissionResult(payload, state, str(error))
