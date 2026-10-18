import pytest

from ops.jobs.consumer import WorkerDeps
from ops.providers.fixture import FixtureProvider
from ops.worker import apply_fault_injection


def deps():
    return WorkerDeps(engine=None, provider=FixtureProvider())


def test_off_by_default():
    d = deps()
    apply_fault_injection(d, None)
    assert d.hooks == {} and isinstance(d.provider, FixtureProvider)


def test_unknown_fault_refused():
    with pytest.raises(RuntimeError):
        apply_fault_injection(deps(), "drop_tables")


def test_crash_hook_installed_only_for_before_ack():
    d = deps()
    apply_fault_injection(d, "crash_before_ack")
    assert set(d.hooks) == {"before_ack"}
