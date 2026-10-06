import sentinel


class TestPackage:
    def test_should_import(self) -> None:
        assert sentinel.__name__ == "sentinel"
