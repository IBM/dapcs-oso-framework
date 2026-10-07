#
# (c) Copyright IBM Corp. 2025
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Authentication Flask Extension."""


from collections.abc import Iterable
from functools import wraps
from typing import Any, Callable, ClassVar

from flask import Flask, current_app, g, request
from werkzeug.datastructures import ImmutableDict
from werkzeug.exceptions import Forbidden, InternalServerError, Unauthorized

from oso.framework.core.logging import get_logger
from oso.framework.exceptions import StartupException

from .common import ALLOWLIST, EXT_NAME, AuthConfig, AuthResult


class AuthExtension:
    """Authentication Extension.

    An extension to manage authentication states for `flask.Flask` applications.

    Attributes
    ----------
    NAME : str
        The literal ``oso-auth``.

    Parameters
    ----------
    config : `.common.AuthConfig`
        Configuration with all parsers defined.
    """

    NAME: ClassVar[str] = EXT_NAME

    def __init__(self, config: AuthConfig):
        self.logger = get_logger(EXT_NAME)
        self.config = config
        self.parsers = {parser.type.NAME: parser.type for parser in self.config.parsers}
        # Parsers of the same type merge their allowlists, so a deployment can
        # add e.g. an "admin" allowlist next to one it doesn't control.
        allowlists: dict[str, dict[str, list]] = {}
        for parser in self.config.parsers:
            merged = allowlists.setdefault(parser.type.NAME, {})
            for k, allowlist in parser.allowlist.items():
                merged.setdefault(k, []).extend(parser.type.parse_allowlist(allowlist))
        setattr(self, ALLOWLIST, ImmutableDict(allowlists))

    def init_app(self, app: Flask) -> None:
        """Attach to a `flask.Flask` application.

        Parameters
        ----------
        app : `flask.Flask`
            Application.
        """
        # Setup basic application
        app.extensions = getattr(app, "extensions", {})

        if EXT_NAME not in app.extensions:
            app.extensions[EXT_NAME] = {}

        if "self" in app.extensions[EXT_NAME]:
            raise StartupException("Plugin already initialized")

        app.before_request(self.parse_request_auth)
        app.extensions[EXT_NAME]["self"] = self
        self.logger.info(
            f"Authentication Loaded with: [ {', '.join(self.parsers.keys())} ]"
        )

    def parse_request_auth(self) -> None:
        """Authenticate a `flask.Request` with all parsers."""
        results = ImmutableDict(
            {name: self.parsers[name].parse(request) for name in self.parsers.keys()}
        )
        self._log_results(results)
        setattr(g, EXT_NAME, results)

    def _log_results(self, results: ImmutableDict[str, AuthResult]) -> None:
        for name, result in results.items():
            self.logger.debug(
                f"{name}: " + "Authorized"
                if result["authorized"]
                else ", ".join(result["errors"])
            )


def current_auth_ext() -> AuthExtension:
    """Get Current Authentication Extension.

    Returns
    -------
    `.AuthExtension`
        The current authentication extension registered to the `flask.Flask`
        application.
    """
    return current_app.extensions[EXT_NAME]["self"]


def _raise_on_unauthorized(handler_name: str) -> None:
    """Check if user is autherized under a `AuthParser`.

    Parameters
    ----------
    hander_name : str
        Parser's name.

    Raises
    ------
    `werkzeug.exceptions.Unauthorized`
        If the user is not authorized. Returns a ``HTTP 401: Unauthorized`` response.

    `werkzeug.exceptions.InternalServerError`
        Should never happen.
    """
    try:
        if getattr(g, EXT_NAME)[handler_name]["authorized"] is True:
            return
    except (KeyError, AttributeError):
        # There is a missing key, so authentication parsers were not successful.
        # Handle this like the user was not authorized.
        pass
    except Exception:
        raise InternalServerError()
    raise Unauthorized()


def _get_user(handler_name: str) -> str | None:
    """Return the user from a `~flask.Request`.

    Parameters
    ----------
    handler_name : str
        The `AuthParser`'s name.

    Returns
    -------
    str | None
        The user, if any.
    """
    try:
        return getattr(g, EXT_NAME, {})[handler_name]["_user"]
    except (KeyError, AttributeError):
        return None


def _get_allowlist(handler_name: str, key: str) -> Iterable:
    """Return the allowlist for an `AuthParser`.

    Parameters
    ----------
    handler_name : str
        The `AuthParser`'s name.
    key : str
        The allowlist's name.

    Returns
    -------
    `collections.abc.Iterable`
    """
    try:
        return getattr(current_auth_ext(), ALLOWLIST)[handler_name][key.lower()]
    except (KeyError, AttributeError):
        return []


def RequireAuth(handler_name: str, allowlist: str, *allowlists: str) -> Callable:
    """Mark an endpoint as requiring authentication.

    Parameters
    ----------
    handler_name : str
        The `AuthParser` that is required.
    *allowlists : list[str]
        The allowlists that is allowed for the endpoint.

    Returns
    -------
    `~typing.Callable`
        The wrapped function.
    """

    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated(*args, **kwargs) -> Any:
            _raise_on_unauthorized(handler_name)
            for key in [allowlist, *allowlists]:
                _allowlist = _get_allowlist(handler_name, key)
                _user = _get_user(handler_name)
                if _user in _allowlist:
                    # User is allowed to utilize this path
                    return f(*args, **kwargs)
            # User is forbidden from utilizing this path.
            raise Forbidden()

        return decorated

    return decorator
