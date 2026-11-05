from ac_traceability import INCREMENT_1_ACS, register  # noqa: F401

pytest_plugins = ["pytester"]


def pytest_configure(config):
    register(config)
