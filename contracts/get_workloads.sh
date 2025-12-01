#!/bin/bash
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


FRONTEND_PLUGIN_FILE="./output/frontend/frontend.yml"
if [ ! -f $FRONTEND_PLUGIN_FILE ]; then
  echo "frontend plugin file does not exist: $FRONTEND_PLUGIN_FILE"
  exit 1
fi
FRONTEND_PLUGIN=$(cat "$FRONTEND_PLUGIN_FILE")

BACKEND_FILE="./output/backend/user-data"
if [ ! -f $BACKEND_FILE ]; then
  echo "backend file does not exist: $BACKEND_FILE"
  exit 1
fi
BACKEND=$(cat "$BACKEND_FILE")

GREP11_FILE="./output/grep11/user-data"
if [ ! -f $GREP11_FILE ]; then
  echo "backend file does not exist: $GREP11_FILE"
#  exit 1
fi
GREP11=$(cat "$GREP11_FILE")

cat <<-EOT
# Hyper Protect Encrypted Workloads
FRONTEND_WORKLOADS=[
  {
    persistent_vol: null,
    name: "frontend-plugin",
    workload: "$FRONTEND_PLUGIN"
  }
]

BACKEND_WORKLOADS=[
  {
    name: "backend-plugin",
    hipersocket34: false,
    workload: "$BACKEND",
    persistent_vol: {
      volume_name = "vault_vol",
      env_seed = "vaultseed2",
      prev_seed = "",
      volume_path = "/var/lib/libvirt/images/oso/helloworld-data.qcow2"
    }
  }
]
EOT
