import pytest
import sqlalchemy as sa


def test_engines_hide_bound_parameters():
    from ops.db import engine

    for role in ("admin", "import", "api", "worker"):
        assert engine(role).hide_parameters is True


def test_errors_do_not_echo_parameters(db):
    secret = "do-not-print-this-value"
    with pytest.raises(sa.exc.DBAPIError) as exc, db("admin").connect() as c:
        c.execute(sa.text("SELECT format('%L', :p)"), {"p": secret})
    assert secret not in str(exc.value)
