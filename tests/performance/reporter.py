"""Native Locust report generation module.

Leverages Locust's built-in HTML report generator (locust.html) and CSV statistics writer
(locust.stats) to organize performance reports in timestamped directories upon test completion.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from locust.html import get_html_report
from locust.stats import PERCENTILES_TO_REPORT, StatsCSVFileWriter

from tests.performance.config import config

logger = logging.getLogger(__name__)


def generate_native_reports(environment: Any) -> None:
    """Generate native Locust HTML and CSV performance reports inside dedicated output directory.

    Args:
        environment: Locust Environment instance containing request statistics.
    """
    if not environment.stats or not environment.stats.total.num_requests:
        logger.info("No request statistics recorded. Skipping report generation.")
        return

    base_dir = Path(config.REPORT_DIRECTORY)
    prefix = config.REPORT_FILENAME_PREFIX

    if config.ENABLE_TIMESTAMPED_REPORTS:
        timestamp_folder = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target_dir = base_dir / timestamp_folder
    else:
        target_dir = base_dir

    target_dir.mkdir(parents=True, exist_ok=True)
    base_filepath = str(target_dir / prefix)

    # 1. Generate Native Locust CSV Reports (stats, failures, exceptions)
    try:
        csv_writer = StatsCSVFileWriter(
            environment=environment,
            percentiles_to_report=PERCENTILES_TO_REPORT,
            base_filepath=base_filepath,
            full_history=False,
        )
        csv_writer.requests_flush()
        csv_writer.failures_flush()
        csv_writer.exceptions_flush()
        csv_writer.close_files()
    except Exception as exc:
        logger.warning("Failed to write CSV performance reports: %s", exc)

    # 2. Generate Native Locust HTML Report
    html_filepath = target_dir / f"{prefix}.html"
    try:
        html_report_content: str = get_html_report(environment)  # type: ignore[no-untyped-call]
        with html_filepath.open("w", encoding="utf-8") as f:
            f.write(html_report_content)
    except Exception as exc:
        logger.warning("Failed to write HTML performance report: %s", exc)

    # 3. Prominent Discoverability Summary Log
    logger.info(
        "\n"
        "================================================================================\n"
        "Performance test completed.\n"
        "Reports generated in:\n"
        "  %s\n"
        "  ├── HTML: %s\n"
        "  └── CSV:  %s_stats.csv\n"
        "================================================================================",
        target_dir.resolve(),
        html_filepath.name,
        prefix,
    )
