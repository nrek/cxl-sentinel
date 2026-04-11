"""CXL Sentinel Agent -- deployment change detector.

Runs as a systemd service (--mode service) or one-shot scan (--mode oneshot).
Detects git HEAD changes in configured project directories and reports
deploy events to the central Sentinel API.
"""

import argparse
import logging
import logging.handlers
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from agent.config import AgentConfig, load_config
from agent.collector import collect_commit_metadata
from agent.detector import detect_change, get_current_branch
from agent.reporter import Reporter
from agent.state import StateManager

logger = logging.getLogger("sentinel")

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
_shutdown_requested = False


def get_version() -> str:
    try:
        return _VERSION_FILE.read_text().strip()
    except OSError:
        return "unknown"


def _setup_logging(config: AgentConfig) -> None:
    log_cfg = config.logging
    root = logging.getLogger("sentinel")
    root.setLevel(getattr(logging, log_cfg.level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        log_path = Path(log_cfg.file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_cfg.file,
            maxBytes=log_cfg.max_bytes,
            backupCount=log_cfg.backup_count,
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as e:
        root.warning("Could not set up file logging at %s: %s", log_cfg.file, e)


def _handle_signal(signum: int, _frame) -> None:
    global _shutdown_requested
    logger.info("Received signal %d, shutting down gracefully...", signum)
    _shutdown_requested = True


def run_scan_cycle(config: AgentConfig, state: StateManager, reporter: Reporter) -> None:
    """Scan all configured projects for git changes and report events."""
    reporter.send_heartbeat(
        server_id=config.sentinel.server_id,
        environment=config.sentinel.environment,
        projects=[p.name for p in config.projects],
        agent_version=get_version(),
    )

    for project in config.projects:
        try:
            _scan_project(config, project, state, reporter)
        except Exception:
            logger.exception("Unexpected error scanning project '%s'", project.name)

    state.save()


def _scan_project(config, project, state, reporter) -> None:
    last_hash = state.get_last_hash(project.name)

    branch = project.branch
    if not branch or branch == "current":
        detected = get_current_branch(project.path)
        branch = detected if detected else "unknown"

    result = detect_change(project.path, branch, last_hash)

    if result.error:
        logger.warning("Skipping '%s': %s", project.name, result.error)
        return

    state.set_last_hash(project.name, result.current_hash)

    if not result.changed:
        logger.debug("No change in '%s' (%s)", project.name, result.current_hash[:12])
        return

    metadata = collect_commit_metadata(
        project.path, result.current_hash, result.previous_hash, branch,
    )
    if not metadata:
        logger.error("Failed to collect metadata for '%s', skipping event", project.name)
        return

    reporter.send_event(
        server_id=config.sentinel.server_id,
        environment=config.sentinel.environment,
        project=project.name,
        client=project.client,
        metadata=metadata,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="CXL Sentinel Agent")
    parser.add_argument(
        "--mode", choices=["service", "oneshot"], default="service",
        help="Execution mode: 'service' (loop) or 'oneshot' (scan and exit)",
    )
    parser.add_argument(
        "--config", required=True,
        help="Path to agent YAML config file",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    _setup_logging(config)
    logger.info("CXL Sentinel Agent v%s starting in %s mode", get_version(), args.mode)

    state = StateManager(config.sentinel.state_file)
    reporter = Reporter(
        api_url=config.sentinel.api_url,
        api_token=config.sentinel.api_token,
        queue_file=str(Path(config.sentinel.state_file).parent / "queue.json"),
    )

    if args.mode == "oneshot":
        run_scan_cycle(config, state, reporter)
        logger.info("Oneshot scan complete")
        return

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("Service mode: scanning every %d seconds", config.sentinel.scan_interval)

    while not _shutdown_requested:
        try:
            run_scan_cycle(config, state, reporter)
        except Exception:
            logger.exception("Unhandled error in scan cycle")

        for _ in range(config.sentinel.scan_interval):
            if _shutdown_requested:
                break
            time.sleep(1)

    logger.info("Agent shutdown complete")


if __name__ == "__main__":
    main()
