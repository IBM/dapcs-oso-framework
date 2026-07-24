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
"""Events Endpoint."""

from flask import Response, request
from flask.views import MethodView

from oso.framework.auth.extension import RequireAuth
from oso.framework.data.types import V1_3
from oso.framework.plugin import current_oso_plugin_app


class Api(MethodView):
    """Plugin Events View."""

    ENDPOINT = "/".join(__name__.split(".")[-2:])

    @RequireAuth("mtls", "component")
    def post(self):
        """POST /v1alpha1/events endpoint.

        Returns
        -------
        body : str
            JSON-serialised `oso.framework.data.types.EventResponse` with a 200
            HTTP response code.  Either ``{}`` (no holds) or
            ``{"hold": [event_id, ...]}`` (event IDs to defer).
            To return an error, ``on_events()`` should raise the appropriate
            HTTPError.
        """
        events = V1_3.EventList.model_validate_json(request.get_data())
        response = current_oso_plugin_app().on_events(events)
        return Response(
            response.model_dump_json(exclude_defaults=True),
            content_type="application/json",
        )
