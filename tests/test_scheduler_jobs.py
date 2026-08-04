"""Scheduled jobs must survive a late start.

APScheduler drops a job entirely if it fires later than `misfire_grace_time`,
and the default is 1 second. In production every daily run was arriving ~1.7s
late and being silently skipped, so no subscription was ever auto-logged.
"""
from apscheduler.triggers.cron import CronTrigger

from app.bot.app import build_application
from app.scheduler import register_jobs

_UNSET = object()


def _registered_jobs():
    app = build_application()
    register_jobs(app)
    return [j.job for j in app.job_queue.jobs()]


def test_daily_jobs_are_not_skipped_when_they_start_late():
    cron_jobs = [j for j in _registered_jobs() if isinstance(j.trigger, CronTrigger)]
    assert len(cron_jobs) == 2, "expected the daily sub check and the weekly digest"
    for job in cron_jobs:
        assert getattr(job, "misfire_grace_time", _UNSET) is None, (
            f"{job.name} inherits APScheduler's 1s default grace time and will be "
            "dropped whenever the process is a moment late"
        )


def test_startup_catch_up_is_not_skipped_when_it_starts_late():
    one_shot = [j for j in _registered_jobs() if not isinstance(j.trigger, CronTrigger)]
    assert len(one_shot) == 1, "expected the startup catch-up job"
    assert getattr(one_shot[0], "misfire_grace_time", _UNSET) is None
