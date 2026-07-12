import asyncio

from blockstead.scheduler import Scheduler


def test_close_tolerates_completed_task_from_closed_loop() -> None:
    loop = asyncio.new_event_loop()
    task = loop.create_task(asyncio.sleep(0))
    loop.run_until_complete(task)
    loop.close()

    scheduler = Scheduler.__new__(Scheduler)
    scheduler._task = task
    asyncio.run(scheduler.close())

    assert scheduler._task is None
