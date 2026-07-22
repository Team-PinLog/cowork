from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.main import LoginLimiter


def test_login_limiter_reservation_is_atomic_under_concurrency():
    limiter = LoginLimiter(max_attempts=5, window_seconds=300)
    barrier = Barrier(20)

    def attempt():
        barrier.wait()
        return limiter.reserve("203.0.113.10", "member@example.com")

    with ThreadPoolExecutor(max_workers=20) as executor:
        reservations = list(executor.map(lambda _: attempt(), range(20)))

    accepted = [reservation for reservation in reservations if reservation is not None]
    assert len(accepted) == 5
    assert len(set(accepted)) == 5

    limiter.release_success("203.0.113.10", "member@example.com", accepted[0])
    assert limiter.reserve("203.0.113.10", "member@example.com") is not None
