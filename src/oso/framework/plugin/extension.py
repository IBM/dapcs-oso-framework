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

"""PluginExtension class for initializing and configuring plugins."""

from typing import ClassVar, Literal, Type

from flask import Flask, current_app
from flask.views import View
from pydantic import BaseModel
from pydantic.types import ImportString

from oso.framework.config import AutoLoadConfig, ImportListMixin
from oso.framework.core.logging import get_logger
from oso.framework.exceptions import StartupException

from .base import PluginProtocol
from .addons.main import AddonProtocol, BaseAddonConfig

class PluginConfig(
    AutoLoadConfig,
    ImportListMixin({"addons": BaseAddonConfig}),
    _config_prefix="plugin"
):
    """
    Configuration model for plugins.

    Attributes
    ----------
        mode (Literal["frontend", "backend"]): The mode of the plugin.
        application (ImportString): The application class or string.
        schema (Literal["v1.3", "v1.5"]): The OSO schema version the plugin
            implements.  Defaults to ``"v1.3"``.  Set to ``"v1.5"`` to enable
            eventing support (``POST /events`` endpoint).
    """

    mode: Literal["frontend", "backend"]
    application: ImportString
    schema: Literal["v1.3", "v1.5"] = "v1.3"


class PluginExtension:
    """
    The PluginExtension class initializes and configures plugins in the OSO framework.

    Attributes
    ----------
        KEY (ClassVar[Literal["oso-plugin"]]): The key for the plugin extension.
        config (PluginConfig): The configuration for the plugin.
    """

    KEY: ClassVar[Literal["oso-plugin"]] = "oso-plugin"

    # TODO: perhaps PluginConfig should be application wide config
    def __init__(self, config: PluginConfig):
        """
        Initialize the PluginExtension instance.

        Args:
            config (PluginConfig): The configuration for the plugin.
        """
        self.config = config
        self._init_addons(config.addons) # type: ignore [reportAttributeAccessError]

    def _init_addons(self, addons: list[BaseAddonConfig]):
        self.addons: dict[str, AddonProtocol] = {}
        for addon in addons:
            self.addons[addon.type.NAME] = addon.type.configure(self.config, addon)

    def init_app(self, app: Flask) -> None:
        """
        Initialize the plugin with the Flask application.

        Args:
            app (Flask): The Flask application instance.

        Raises
        ------
            StartupException:
                If the plugin doesn't follow the PluginProtocol or
                isn't initialized.
        """
        self.logger = get_logger(self.KEY)

        if not isinstance(self.config.application, PluginProtocol):
            raise StartupException(
                "Plugin does not follow oso.framework.plugin.PluginProtocol"
            )

        # Setup plugin instance
        self.plugin = self.config.application
        if isinstance(self.plugin, Type):
            self.plugin = self.plugin()

        # Setup basic application
        app.extensions = getattr(app, "extensions", {})

        if self.KEY not in app.extensions:
            app.extensions[self.KEY] = {}

        if "self" in app.extensions[self.KEY]:
            raise StartupException("Plugin already initialized")

        # Initialize APIs
        from .api import V1DocumentsApi, V1EventsApi, V1StatusApi

        self._add_endpoint(
            app=app,
            rule=f"/api/{self.config.mode}/{V1DocumentsApi.ENDPOINT}",
            view_func=V1DocumentsApi.as_view(f"plugin-{V1DocumentsApi.ENDPOINT}"),
        )
        self._add_endpoint(
            app=app,
            rule=f"/api/{self.config.mode}/{V1StatusApi.ENDPOINT}",
            view_func=V1StatusApi.as_view(f"plugin-{V1StatusApi.ENDPOINT}"),
        )
        if self.config.schema == "v1.5":
            self._add_endpoint(
                app=app,
                rule=f"/api/{self.config.mode}/{V1EventsApi.ENDPOINT}",
                view_func=V1EventsApi.as_view(f"plugin-{V1EventsApi.ENDPOINT}"),
            )

        # Add ISV supplied APIs
        for rule, view in self.plugin.externalViews.items():
            self._add_endpoint(
                app=app,
                rule=f"/api/{rule}",
                view_func=view.as_view(f"isv-external-{rule}"),
            )
        for rule, view in self.plugin.internalViews.items():
            self._add_endpoint(
                app=app,
                rule=f"/internal/{rule}",
                view_func=view.as_view(f"isv-internal-{rule}"),
            )

        # Finish initialization
        app.extensions[self.KEY]["self"] = self
        app.extensions[self.KEY]["plugin_config"] = self.config  # also save config

    def _add_endpoint(self, app: Flask, rule: str, view_func: View):
        """
        Add an endpoint to the Flask application.

        Args:
            app (Flask): The Flask application instance.
            rule (str): The URL rule for the endpoint.
            view_func (View): The view function for the endpoint.
        """
        app.add_url_rule(rule=rule, view_func=view_func)
        self.logger.debug(f"Added rule {rule}")


def current_oso_plugin() -> PluginExtension:
    """
    Return the current OSO plugin extension instance.

    Returns
    -------
        PluginExtension: The current plugin extension instance.
    """
    return current_app.extensions[PluginExtension.KEY]["self"]


def current_oso_plugin_app() -> PluginProtocol:
    """
    Return the current plugin instance.

    Returns
    -------
        PluginProtocol: The current plugin instance.
    """
    return current_app.extensions[PluginExtension.KEY]["self"].plugin


def current_oso_plugin_config() -> BaseModel:
    """
    Return the current plugin configuration.

    Returns
    -------
        BaseModel: The current plugin configuration.
    """
    return current_app.extensions[PluginExtension.KEY]["plugin_config"]
