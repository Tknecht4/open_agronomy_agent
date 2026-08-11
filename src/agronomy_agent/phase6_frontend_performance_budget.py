from __future__ import annotations


EXPECTED_FRONTEND_PERFORMANCE_BUDGET_IDS = (
    "CLS",
    "INP",
    "LCP",
    "TTI",
    "first_visible_progress",
    "long_task",
    "model_download_notice",
    "open_interaction",
    "open_time",
    "render_time",
    "standard_thread_report_preview",
)
EXPECTED_FRONTEND_PERFORMANCE_PACKET_METRIC_IDS = (
    "all primary routes/CLS",
    "all primary routes/INP",
    "answer stream/first_token_visible",
    "answer stream/first_visible_progress",
    "evidence drawer/open_interaction",
    "existing thread/open_time",
    "home/app shell/LCP",
    "local model preview/model_download_notice",
    "login -> app shell/time_to_interactive",
    "report preview/standard_thread_report_preview",
    "thread list/render_time",
    "trace/debug drawer/main_thread_blocking",
)
EXPECTED_FRONTEND_PERFORMANCE_BLOCKER_PACKET_METRIC_IDS = tuple(
    metric_id
    for metric_id in EXPECTED_FRONTEND_PERFORMANCE_PACKET_METRIC_IDS
    if metric_id != "answer stream/first_token_visible"
)
EXPECTED_FRONTEND_PERFORMANCE_EXCEPTION_IDS = ("answer stream/first_token_visible",)
