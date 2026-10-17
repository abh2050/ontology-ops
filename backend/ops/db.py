"""Engine factory. Each process connects with the role that matches its duty."""

from functools import cache
from typing import Literal

from sqlalchemy import Engine, create_engine

from ops.settings import get_settings

Role = Literal["admin", "import", "api", "worker"]


@cache
def engine(role: Role) -> Engine:
    # hide_parameters keeps bound values (passwords, IDs) out of exception text and logs.
    return create_engine(get_settings().database_url(role), pool_pre_ping=True,
                         pool_size=10, max_overflow=20, hide_parameters=True)
