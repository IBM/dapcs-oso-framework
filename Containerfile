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


FROM registry.access.redhat.com/ubi9/ubi-minimal as runtime
ENV HOME=/app-root VIRTUAL_ENV=/opt/oso/venv
RUN rpm -i https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm \
    && microdnf module enable --assumeyes nginx:1.24 \
    && microdnf install --assumeyes --setopt=install_weak_deps=0 \
        libsodium openssl \
        nginx \
    && microdnf clean all \
    && install --owner=1001 --group=0 --directory \
        $HOME \
    && true

ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR $HOME
USER 1001:0

FROM registry.access.redhat.com/ubi9/ubi as builder
RUN dnf install \
        --assumeyes \
            https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm
RUN dnf install \
        --assumeyes \
            rust cargo gcc-c++ \
            libsodium-devel openssl-devel \
            python3.12-devel gcc
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /build
ARG UV_PYTHON=3.12
ARG UV_PROJECT_ENVIRONMENT=/opt/oso/venv
ARG UV_PYTHON_INSTALL_DIR=/opt/oso/python
ARG UV_REQUIRE_HASHES=true
COPY pyproject.toml uv.lock ./
ENV GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1
RUN uv sync --no-install-project --frozen --compile-bytecode --extra mock
COPY src src
RUN uv sync --no-editable --frozen --compile-bytecode --extra mock

# Example of plugin
FROM runtime as plugin
COPY --from=builder --chown=1001:0 /opt/oso /opt/oso
