from runner.main import PROHIBITED, _bounded


def test_prohibited_program_behaviors_are_detected() -> None:
    for source in ["system('id')", "download.file('https://example.test')", "install.packages('x')", "read.csv('/etc/passwd')"]:
        assert PROHIBITED.search(source)


def test_logs_are_bounded_and_nul_free() -> None:
    assert _bounded("x" * 30_000 + "\x00").endswith("x" * 19_999)

