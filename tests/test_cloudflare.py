from urllib.error import URLError

import pytest

from sentinel.speed.cloudflare import CloudflareSpeedTester, mbps

MB = 1_000_000


class Blob:
    def __init__(self, size: int) -> None:
        self.size = size

    def __len__(self) -> int:
        return self.size


class FakeNetwork:
    def __init__(self, down: dict[int, float], up: dict[int, float]) -> None:
        self.down = down
        self.up = up
        self.now = 0.0
        self.requests: list[tuple[str, str, int]] = []
        self.failing: set[tuple[str, int]] = set()

    def clock(self) -> float:
        return self.now

    def open_url(self, request, timeout):
        size = (
            int(request.full_url.split("bytes=")[1]) if request.data is None else len(request.data)
        )
        method = request.get_method()
        self.requests.append((method, request.get_header("User-agent"), size))
        if (method, size) in self.failing:
            raise URLError("network is unreachable")
        if method == "POST":
            self.now += self.up[size]
        return FakeResponse(self, size if method == "GET" else 0)


class FakeResponse:
    def __init__(self, network: FakeNetwork, size: int) -> None:
        self.network = network
        self.remaining = size

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, _size=-1):
        if not self.remaining:
            return b""
        self.network.now += self.network.down[self.remaining]
        chunk, self.remaining = Blob(self.remaining), 0
        return chunk


def speed_tester(network: FakeNetwork) -> CloudflareSpeedTester:
    return CloudflareSpeedTester(open_url=network.open_url, clock=network.clock)


def test_mbps_is_megabits_per_second():
    assert mbps(25 * MB, 0.4) == pytest.approx(500.0)


def test_a_fast_link_grows_to_the_largest_size_and_repeats_it():
    network = FakeNetwork(
        down={1 * MB: 0.02, 10 * MB: 0.2, 25 * MB: 0.4, 50 * MB: 0.8},
        up={1 * MB: 0.1, 10 * MB: 0.9, 25 * MB: 2.1},
    )
    download, upload = speed_tester(network).measure()
    assert download == pytest.approx(500.0)
    assert upload == pytest.approx(25 * 8 / 2.1)
    assert [size for _, _, size in network.requests] == [
        1 * MB,
        10 * MB,
        25 * MB,
        50 * MB,
        50 * MB,
        1 * MB,
        10 * MB,
        25 * MB,
    ]


def test_a_tiny_transfer_does_not_count_on_a_fast_link():
    network = FakeNetwork(
        down={1 * MB: 0.001, 10 * MB: 2.0},
        up={1 * MB: 0.001, 10 * MB: 2.0},
    )
    download, upload = speed_tester(network).measure()
    assert download == pytest.approx(40.0)
    assert upload == pytest.approx(40.0)


def test_a_slow_link_counts_the_first_long_transfer_and_stops():
    network = FakeNetwork(down={1 * MB: 2.0}, up={1 * MB: 4.0})
    download, upload = speed_tester(network).measure()
    assert download == pytest.approx(4.0)
    assert upload == pytest.approx(2.0)
    assert len(network.requests) == 2


def test_no_network_means_no_result_not_an_error(caplog):
    network = FakeNetwork(down={}, up={})
    network.failing = {("GET", 1 * MB), ("POST", 1 * MB)}
    assert speed_tester(network).measure() == (None, None)
    assert "speedtest transfer failed" in caplog.text


def test_a_failure_midway_keeps_what_was_measured():
    network = FakeNetwork(down={1 * MB: 0.01, 10 * MB: 0.2}, up={1 * MB: 0.01, 10 * MB: 0.4})
    network.failing = {("GET", 25 * MB), ("POST", 25 * MB)}
    download, upload = speed_tester(network).measure()
    assert download == pytest.approx(400.0)
    assert upload == pytest.approx(200.0)


def test_requests_identify_themselves():
    network = FakeNetwork(down={1 * MB: 2.0}, up={1 * MB: 2.0})
    speed_tester(network).measure()
    assert {agent for _, agent, _ in network.requests} == {"sentinel"}
