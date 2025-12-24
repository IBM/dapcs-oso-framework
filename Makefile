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


LOCAL_PLAY := deploy/local

SRCS = $(shell find src/ -name '*.py')

ifdef PRIVATE_PYPI_NETRC
ifeq (,$(wildcard $(PRIVATE_PYPI_NETRC)))
$(error $(PRIVATE_PYPI_NETRC) file does not exist!)
endif
PYPI_OPTIONS += --secret id=netrc,src=$(PRIVATE_PYPI_NETRC)
endif

$(LOCAL_PLAY)/runtime: Containerfile
	docker build -f $< -t oso-runtime --target runtime --iidfile $@ .

$(LOCAL_PLAY)/builder: Containerfile $(SRCS)
	docker build $(PYPI_OPTIONS) -f $< -t oso-builder --target builder --iidfile $@ .

$(LOCAL_PLAY)/plugin: Containerfile $(LOCAL_PLAY)/builder
	docker build -f $< -t oso-plugin --target plugin --iidfile $@ .

containerize: $(addprefix $(LOCAL_PLAY)/,runtime builder plugin)

$(LOCAL_PLAY)/oso-runtime.tar: $(LOCAL_PLAY)/runtime
	docker save --output $@ oso-runtime

$(LOCAL_PLAY)/oso-builder.tar: $(LOCAL_PLAY)/builder
	docker save --output $@ oso-builder

$(LOCAL_PLAY)/oso-plugin.tar: $(LOCAL_PLAY)/plugin
	docker save --output $@ oso-plugin

$(addsuffix .key,$(addprefix $(LOCAL_PLAY)/,oso-ca app user)): $(LOCAL_PLAY)/%.key:
	openssl genrsa -out $@ 4096
	chmod 0600 $@

$(LOCAL_PLAY)/%.csr: $(LOCAL_PLAY)/%.key
	openssl req -key $< -new -out $@ -nodes -subj '/C=US/O=IBM OSO/CN=$*/'

$(LOCAL_PLAY)/%.crt: $(LOCAL_PLAY)/%.csr $(LOCAL_PLAY)/ext
	openssl x509 -req -in $< \
		$(if $(findstring oso-ca,$*),-signkey $(LOCAL_PLAY)/oso-ca.key,-CAkey $(LOCAL_PLAY)/oso-ca.key -CA $(LOCAL_PLAY)/oso-ca.crt) \
		-CAcreateserial -out $@ -days 365 \
		-extensions v3_$(if $(findstring oso-ca,$*),ca,crt) -extfile $(word 2,$^)

APP_NAME ?= test
APP_ENTRY ?= oso.framework.plugin:create_app
PLUGIN_APP ?= oso.framework.plugin.test.isv_cls:TestISVApp
PLUGIN_MODE ?= frontend

REGEN_CM ?= n
ifneq ($(REGEN_CM),n)
.PHONY: $(LOCAL_PLAY)/cm.yaml
endif

$(LOCAL_PLAY)/cm.yaml: SHELL := /bin/bash
$(LOCAL_PLAY)/cm.yaml: $(addprefix $(LOCAL_PLAY)/,oso-ca.crt app.key app.crt user.key)
	printf "%s\n" \
		'apiVersion: v1' \
		'kind: ConfigMap' \
		'metadata:' \
		'  name: local' \
		'data:' \
		'  app__name: $(APP_NAME)' \
		'  app__entry: $(APP_ENTRY)' \
		'  app__root: /app-root' \
		'  auth__parsers__0__type: "oso.framework.auth.mtls"' \
		'  auth__parsers__0__allowlist: |' \
		'    { "component": [' \
		'      "'"$$(awk '{ print $$2 }' <(ssh-keygen -lf $(word 2,$^)))"'", ' \
		'      "'"$$(awk '{ print $$2 }' <(ssh-keygen -lf $(word 4,$^)))"'"' \
		'    ]}' \
		'  plugin__application: $(PLUGIN_APP)' \
		'  plugin__mode: $(PLUGIN_MODE)' \
		'  logging__level: debug' \
		'  certs__ca: |' \
		"$$(awk '{ print "    "$$0 }' $<)" \
		'  certs__app_key: |' \
		"$$(awk '{ print "    "$$0 }' $(word 2,$^))" \
		'  certs__app_crt: |' \
		"$$(awk '{ print "    "$$0 }' $(word 3,$^) $<)" \
	> $@

.PHONY: play-local-up play-local-down play-local-reload

TMP_DIR := /tmp/podman-tmp
USER_ID := $(shell id -u)
GROUP_ID := $(shell id -g)

play-local-down: $(LOCAL_PLAY)/play.yaml
	set -e; \
	podman kube down $< 2> /dev/null || true; \
	podman pod rm local 2> /dev/null || true; \
	podman volume rm local 2> /dev/null || true

play-local-up: $(LOCAL_PLAY)/play.yaml $(LOCAL_PLAY)/cm.yaml \
              $(LOCAL_PLAY)/oso-runtime.tar $(LOCAL_PLAY)/oso-plugin.tar $(LOCAL_PLAY)/oso-builder.tar
	set -e; \
	mkdir -p $(TMP_DIR); \
	sudo chown -R $(USER_ID):$(GROUP_ID) $(TMP_DIR); \
	export TMPDIR=$(TMP_DIR); \
	podman kube down $(LOCAL_PLAY)/play.yaml 2> /dev/null || true; \
	podman volume rm local 2> /dev/null || true; \
	podman load -i $(LOCAL_PLAY)/oso-runtime.tar; \
	podman tag $$(podman images -q localhost/oso-runtime:latest) localhost/oso-runtime:latest; \
	podman load -i $(LOCAL_PLAY)/oso-plugin.tar; \
	podman tag $$(podman images -q localhost/oso-plugin:latest) localhost/oso-plugin:latest; \
	podman load -i $(LOCAL_PLAY)/oso-builder.tar; \
	podman tag $$(podman images -q localhost/oso-builder:latest) localhost/oso-builder:latest; \
	podman play kube --configmap $(LOCAL_PLAY)/cm.yaml $(LOCAL_PLAY)/play.yaml

play-local-reload: play-local-down play-local-up

.PHONY: play-mock-up play-mock-down

play-mock-up: containerize
	make -C deploy/mock up

play-mock-down: containerize
	make -C deploy/mock down

.PHONY: unit-test cov-test
unit-test:
	uv run pytest

cov-test:
	@if [ -z "$(TEST_RESULTS)" ]; then \
		echo "TEST_RESULTS not set"; \
		exit 1; \
	fi

	uv run pytest \
		--verbose \
		--import-mode=importlib \
		--cov=oso \
		--cov-report=xml:$(TEST_RESULTS)/coverage.xml \
		--junit-xml=$(TEST_RESULTS)/junit.xml

.PHONY: generate-apidoc
generate-apidoc:
	:; \
	SPHINX_APIDOC_OPTIONS=members,show-inheritance \
		uv run sphinx-apidoc \
			--implicit-namespaces \
			--force \
			--output docs/generated \
			src/oso

.PHONY: gh-pages
gh-pages:
	make -C docs html

.PHONY: generate-protobufs
generate-protobufs:
	uv run python -m grpc_tools.protoc \
		--proto_path=src/oso/framework/plugin/addons/signing_server/protos/ \
		--python_out=src/oso/framework/plugin/addons/signing_server/generated/ \
		--grpc_python_out=src/oso/framework/plugin/addons/signing_server/generated/ \
		--pyi_out=src/oso/framework/plugin/addons/signing_server/generated/ \
		server.proto
	sed -i -e "s/import server_pb2 as server__pb2/from . import server_pb2 as server__pb2/" \
		src/oso/framework/plugin/addons/signing_server/generated/server_pb2_grpc.py

clean:
	rm -f $(LOCAL_PLAY)/runtime $(LOCAL_PLAY)/builder $(LOCAL_PLAY)/plugin
