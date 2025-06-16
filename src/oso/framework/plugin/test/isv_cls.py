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
"""Example plugin implemented as a class."""


from typing import Any

from oso.framework.data.types import V1_3

from ..base import PluginProtocol
from .isv_view import InView


class TestISVApp(PluginProtocol):
    """Example plugin implemented as a class.

    Attributes
    ----------
    internalViews : dict[str, `flask.views.View`]
    externalViews : dict[str, `flask.views.View`]
    """

    internalViews = {"test_internal": InView}
    externalViews = {}

    def __init__(self):
        self._isv: list[str] = list()

    def _set_test_documents(self, isv: list[str]):
        self._isv = isv

    def _set_status(self, status_code: int, status_msg: str):
        self._status_code = status_code
        self._status_msg = status_msg

    def to_oso(self, isv: Any = None) -> V1_3.DocumentList:
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
        for id, content in [i.split(":") for i in self._isv]:
            docs.append(V1_3.Document(id=id, content=content))
        self._isv.clear()
        return V1_3.DocumentList(documents=docs, count=len(docs))

    def to_isv(self, oso: V1_3.DocumentList) -> list[str]:
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

    def status(self) -> V1_3.ComponentStatus:
        """Return a downstream component's status.

        Returns
        -------
        `oso.framework.data.types.ComponentStatus`
            The downstream's component status.
        """
        return V1_3.ComponentStatus(
            status_code=self._status_code,
            status=self._status_msg,
            errors=[],
        )
