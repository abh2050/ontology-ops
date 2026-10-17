import json

import pytest

from ops.data import users as U


class FakeIdp:
    class exceptions:  # noqa: N801 - mirrors boto3's attribute
        class UserNotFoundException(Exception):
            pass

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.passwords: dict[str, str] = {}

    def admin_get_user(self, UserPoolId, Username):  # noqa: N803
        if Username not in self.users:
            raise self.exceptions.UserNotFoundException()
        return self.users[Username]

    def admin_create_user(self, UserPoolId, Username, MessageAction):  # noqa: N803
        assert MessageAction == "SUPPRESS"  # no invitation is ever sent
        self.users[Username] = {"UserAttributes": [{"Name": "sub", "Value": f"sub-{Username}"}]}

    def admin_set_user_password(self, UserPoolId, Username, Password, Permanent):  # noqa: N803
        assert Permanent and len(Password) >= 14
        self.passwords[Username] = Password


class FakeSm:
    def __init__(self):
        self.value = None

    def get_secret_value(self, SecretId):  # noqa: N803
        if self.value is None:
            raise RuntimeError("no value")
        return {"SecretString": self.value}

    def put_secret_value(self, SecretId, SecretString):  # noqa: N803
        self.value = SecretString


@pytest.fixture
def fakes(monkeypatch):
    idp, sm = FakeIdp(), FakeSm()
    import boto3

    monkeypatch.setattr(boto3, "client", lambda name, **kw: idp if name == "cognito-idp" else sm)
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool")
    monkeypatch.setenv("OPS_DEMO_USERS_SECRET", "secret")
    return idp, sm


def test_cognito_users_created_once_and_passwords_kept_in_secret(fakes):
    idp, sm = fakes
    subjects = U.cognito_subjects()
    assert subjects == {u: f"sub-{u}" for u in U.USERS}
    first = dict(idp.passwords)
    assert json.loads(sm.value) == first
    U.cognito_subjects()  # idempotent: existing users with stored passwords are untouched
    assert idp.passwords == first


def test_missing_configuration_fails(monkeypatch):
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)
    with pytest.raises(U.SeedError):
        U.cognito_subjects()
