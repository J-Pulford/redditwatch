"""Background auto-refresh scheduler (APScheduler), living in the API process.

The interval job only exists while auto_refresh_enabled is true. Toggling the
setting or changing the interval reschedules live, with no restart.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

import db

log = logging.getLogger("scheduler")

JOB_ID = "refresh_job"
_scheduler = None
_refresh_fn = None


def init(refresh_callable) -> None:
    """Start the scheduler and apply the current settings."""
    global _scheduler, _refresh_fn
    _refresh_fn = refresh_callable
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.start()
    apply_settings()


def _job_wrapper() -> None:
    try:
        result = _refresh_fn()
        log.info("Scheduled refresh: %s new item(s).",
                 result.get("new_items", 0))
    except Exception as exc:
        log.warning("Scheduled refresh failed: %s", exc)


def apply_settings() -> None:
    """(Re)configure the interval job from the current settings."""
    if _scheduler is None:
        return
    settings = db.get_all_settings()
    enabled = settings["auto_refresh_enabled"]
    interval = settings["refresh_interval_minutes"]

    if _scheduler.get_job(JOB_ID):
        _scheduler.remove_job(JOB_ID)

    if enabled:
        _scheduler.add_job(
            _job_wrapper,
            trigger="interval",
            minutes=interval,
            id=JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60,
        )
        log.info("Auto-refresh ON — every %s minute(s).", interval)
    else:
        log.info("Auto-refresh OFF.")


def next_run_time():
    """ISO timestamp of the next scheduled run, or None."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def shutdown() -> None:
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
