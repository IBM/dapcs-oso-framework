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

"""Example plugin implemented as a module."""


from types import SimpleNamespace
from typing import Any

from oso.framework.data.types import V1_3, V1_5

mod_g = SimpleNamespace(
    _isv=[],
    _status_code=500,
    _status_msg="Not ready",
)

internalViews = {}
externalViews = {}


def _set_test_documents(isv: list[str]):
    mod_g._isv = isv


def _set_status(status_code: int, status_msg: str):
    mod_g._status_code = status_code
    mod_g._status_msg = status_msg


def to_oso(isv: Any = None) -> V1_3.DocumentList:
    """Convert from ISV to OSO.

    Say an ISV's format is a list of ``ID:Content``, convert to OSO's format.

    Parameters
    ----------
    isv : `typing.Any`, default=None
        An ISV formatted input data stream.

    Returns
    -------
    `oso.framework.data.types.DocumentList`
        An OSO formatted output data stream.
    """
    docs: list[V1_3.Document] = list()
    for id, content in [i.split(":") for i in mod_g._isv]:
        docs.append(V1_3.Document(id=id, content=content))
    mod_g._isv.clear()
    return V1_3.DocumentList(documents=docs, count=len(docs))


def to_isv(oso: V1_3.DocumentList) -> list[str]:
    """Convert from OSO to ISV.

    Convert an OSO's format into an ISV's format, say a list of ``ID:Content``

    Parameters
    ----------
    oso : `oso.framework.data.types.DocumentList`
        An OSO formatted input data stream.

    Returns
    -------
    list[str]
        An ISV formatted output data stream.
    """
    docs: list[str] = list()
    for doc in oso.documents:
        docs.append(f"{doc.id}:{doc.content}")
    return docs


def status() -> V1_3.ComponentStatus:
    """Return a downstream component's status.

    Returns
    -------
    `oso.framework.data.types.ComponentStatus`
        The downstream's component status.
    """
    return V1_3.ComponentStatus(
        status_code=mod_g._status_code,
        status=mod_g._status_msg,
        errors=list(),
    )


def on_events(events: V1_5.EventList) -> V1_5.EventResponse:
    """Handle an inbound batch of document events.

    Parameters
    ----------
    events : `oso.framework.data.types.EventList`
        Validated list of document events.

    Returns
    -------
    `oso.framework.data.types.EventResponse`
        Empty response (no holds).
    """
    return V1_5.EventResponse()
