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
"""Plugin Addons."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from oso.framework.config import ImportableConfig

if TYPE_CHECKING:
    from typing import Any, Callable, ClassVar

class BaseAddonConfig(ImportableConfig):
    """Base Configuration."""

    pass


class AddonProtocol(Protocol):
    """Addon Interface.

    Methods
    -------
    configure(config: Any)
        Configure and return a concrete addon.
    """

    NAME: ClassVar[str]
    configure: ClassVar[Callable[[Any, BaseAddonConfig], AddonProtocol]]
