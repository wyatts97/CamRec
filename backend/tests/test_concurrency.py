"""Tests for the per-user recording claim that closes the monitor/manual race."""
import os
import tempfile
import threading

import pytest


@pytest.fixture(scope="module")
def tm():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["RECORDINGS_DIR"] = os.path.join(tmp, "rec")
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "t.db").replace("\\", "/")
    import importlib, app.config
    importlib.reload(app.config)
    from app.core.task_manager import TaskManager
    return TaskManager()


def test_claim_is_exclusive(tm):
    with tm.claim_user(1) as first:
        assert first is True
        with tm.claim_user(1) as second:
            assert second is False, "a second claim on the same user must be refused"


def test_claim_is_released_on_exit(tm):
    with tm.claim_user(2) as a:
        assert a is True
    with tm.claim_user(2) as b:
        assert b is True, "the claim must be released when the block exits"


def test_claim_is_released_on_exception(tm):
    with pytest.raises(RuntimeError):
        with tm.claim_user(3) as a:
            assert a is True
            raise RuntimeError("boom")
    with tm.claim_user(3) as b:
        assert b is True, "the claim must be released even when the block raises"


def test_different_users_do_not_block_each_other(tm):
    with tm.claim_user(4) as a, tm.claim_user(5) as b:
        assert a is True and b is True


def test_only_one_thread_wins_a_contended_claim(tm):
    """The actual race: many threads trying to start the same user at once."""
    winners = []
    barrier = threading.Barrier(8)

    def attempt():
        barrier.wait()
        with tm.claim_user(99) as claimed:
            if claimed:
                winners.append(threading.current_thread().name)
                # Hold it briefly so the others genuinely overlap.
                threading.Event().wait(0.05)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(winners) == 1, f"expected exactly one winner, got {winners}"
