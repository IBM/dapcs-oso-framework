#
# (c) Copyright IBM Corp. 2025, 2026
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
"""PluginProtocol class for defining plugins."""

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from flask.views import View

from oso.framework.data.types import V1_3, V1_5


@runtime_checkable
class PluginProtocol(Protocol):
    """
    PluginProtocol Constructor.

    Config:
        Any BaseModel extended class can be utilized to add environment variables after
        registering with the config_manager.

    Attributes
    ----------
        internalViews:
            Any internal API endpoints that the ISV wishes to expose to any
            peer containers. These endpoints are prepended with ``/internal/``.

        externalViews
            Any external API endpoints that the ISV wishes to expose to users
            outside the container. These endpoints are prepended with ``/api/isv/``.
    """

    internalViews: Mapping[str, View] = {}
    externalViews: Mapping[str, View] = {}

    def to_oso(self, isv: Any = None) -> V1_3.DocumentList:
        """
        Convert ISV data to OSO formatted document list.

        Return
        -------

            `oso.framework.data.types.DocumentList`:

                OSO formatted document list.

        Raises
        ------
            `werkzeug.exceptions.HTTPException`:

                Any HTTP response other than 200 should return a subclass.
        """
        ...

    def to_isv(self, oso: V1_3.DocumentList) -> Any:
        """
        Convert OSO formatted document list to ISV data.

        Parameters
        ----------
            oso (`oso.framework.data.types.DocumentList`):

                OSO formatted document list.

        Return
        -------

            `Any`:

                ISV formatted document list.

        Raises
        ------
            `werkzeug.exceptions.HTTPException`:

                Any HTTP response other than 200 should return a subclass.
        """
        ...

    def status(self) -> V1_3.ComponentStatus:
        """
        Return the status of the component.

        Return
        -------

            `oso.framework.data.types.ComponentStatus`:

                Mode dependent component's

        Raises
        ------
            `werkzeug.exceptions.HTTPException`:

                Any HTTP response other than 200 should return a subclass.
        """
        ...

    def on_events(self, events: V1_5.EventList) -> V1_5.EventResponse:
        """
        Handle an inbound batch of document events.

        Parameters
        ----------
            events (`oso.framework.data.types.EventList`):

                A validated list of `.DocumentEvent` objects sent by OSO.

        Return
        -------

            `oso.framework.data.types.EventResponse`:

                Either an empty response (``{}``) or a hold list
                (``{"hold": [event_id, ...]}``) of event IDs to defer.

        Raises
        ------
            `werkzeug.exceptions.HTTPException`:

                Any HTTP response other than 200 should return a subclass.
        """
        ...
