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
"""Documents Endpoints."""

from flask import jsonify, request
from flask.views import MethodView

from oso.framework.auth.extension import RequireAuth
from oso.framework.data.types import V1_3
from oso.framework.plugin import current_oso_plugin_app


class Api(MethodView):
    """Plugin Documents View."""

    ENDPOINT = "/".join(__name__.split(".")[-2:])

#    @RequireAuth("mtls", "component")
    def get(self):
        """GET /v1alpha/documents endpoint.

        Returns
        -------
        body : dict
            jsonify'd return from `oso.framework.plugin.base.ISVBase.to_oso()` with
            a 200 HTTP response code. To return an error, `ISVBase.to_oso()` should
            raise the appropriate HTTPError.
        """
        return current_oso_plugin_app().to_oso().model_dump_json()

#    @RequireAuth("mtls", "component")
    def post(self):
        """POST /v1alpha/documents endpoint.

        Returns
        -------
        body : dict
            jsonify'd return from `oso.framework.plugin.base.ISVBase.to_isv()` with
            a 200 HTTP response code. To return an error, `ISVBase.to_isv()` should
            raise the appropriate HTTPError.
        """
        docs = V1_3.DocumentList.model_validate_json(request.get_data())
        return jsonify(current_oso_plugin_app().to_isv(docs))
