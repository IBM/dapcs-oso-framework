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


FROM registry.access.redhat.com/ubi9/ubi-micro AS micro

# Assemble the runtime filesystem in a full UBI image; ubi-micro itself has no
# package manager, so packages are installed into a seeded rootfs and the
# result is copied onto ubi-micro below. dnf --installroot reads repo config
# from the installroot, so epel-release goes into both the host (for the GPG
# key path) and the rootfs (for the repo definitions). No python RPM: the
# interpreter is a uv-managed build shipped inside /opt/oso by the builder.
FROM registry.access.redhat.com/ubi9/ubi AS rootfs
COPY --from=micro / /mnt/rootfs
RUN rpm --install https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm \
    && rpm --root=/mnt/rootfs --install https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm \
    && dnf --installroot=/mnt/rootfs --releasever=9 --assumeyes \
        --setopt=install_weak_deps=0 --nodocs \
        upgrade \
    && dnf --installroot=/mnt/rootfs --releasever=9 --assumeyes \
        module enable nginx:1.26 \
    && dnf --installroot=/mnt/rootfs --releasever=9 --assumeyes \
        --setopt=install_weak_deps=0 --nodocs \
        install \
            libsodium libstdc++ openssl \
            nginx-core \
    && dnf --installroot=/mnt/rootfs clean all \
    && rm -rf /mnt/rootfs/var/cache/* /mnt/rootfs/var/log/dnf* /mnt/rootfs/var/log/yum.* \
    && install --owner=1001 --group=0 --directory /mnt/rootfs/app-root \
    && chown -R 1001:0 /mnt/rootfs/var/lib/nginx /mnt/rootfs/var/log/nginx \
    && chmod -R ug+rwX /mnt/rootfs/var/lib/nginx /mnt/rootfs/var/log/nginx \
    && true

FROM registry.access.redhat.com/ubi9/ubi-micro AS runtime
COPY --from=rootfs /mnt/rootfs /
ENV HOME=/app-root VIRTUAL_ENV=/opt/oso/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR $HOME
USER 1001:0

FROM registry.access.redhat.com/ubi9/ubi AS builder
RUN dnf upgrade --assumeyes
RUN dnf install \
        --assumeyes \
            https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm
RUN dnf install \
        --assumeyes \
            rust cargo gcc-c++ \
            libsodium-devel openssl-devel \
            gcc
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /build
# The interpreter is a uv-managed CPython installed under /opt/oso so the
# runtime image needs no OS python package; /opt/oso is copied wholesale into
# plugin images.
ARG UV_PYTHON=3.13
ARG UV_PYTHON_PREFERENCE=only-managed
ARG UV_PROJECT_ENVIRONMENT=/opt/oso/venv
ARG UV_PYTHON_INSTALL_DIR=/opt/oso/python
ARG UV_REQUIRE_HASHES=true
COPY pyproject.toml uv.lock ./
ENV GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1
RUN uv sync --no-install-project --frozen --compile-bytecode --extra mock
COPY src src
RUN uv sync --no-editable --frozen --compile-bytecode --extra mock

# Example of plugin
FROM runtime AS plugin
COPY --from=builder --chown=1001:0 /opt/oso /opt/oso
