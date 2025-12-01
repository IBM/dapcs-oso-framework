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


resource "local_file" "backend_podman_play" {
  content = templatefile(
    "${path.module}/backend.yml.tftpl",
    { tpl = {
      plugin_image = var.BACKEND_PLUGIN_IMAGE,
      grep11_endpoint = local.grep11_endpoint,
      grep11_port = var.GREP11_PORT,
      grep11_client_cert = var.GREP11_CLIENT_CERT,
      grep11_client_key = var.GREP11_CLIENT_KEY,
      grep11_ca = var.GREP11_CA,
    } },
  )
  filename = "backend/podman-play.yml"
  file_permission = "0664"
}


# archive of the folder containing podman play file. This folder could create additional resources such as files
# to be mounted into containers, environment files etc. This is why all of these files get bundled in a tgz file (base64 encoded)
resource "hpcr_tgz" "backend_workload" {
  depends_on = [ local_file.backend_podman_play ]
  folder = "${path.module}/backend"
}

locals {
  grep11_endpoint = "${var.GREP11_HOST}:${var.GREP11_PORT}"
  backend_play = {
    "play" : {
      "archive" : hpcr_tgz.backend_workload.rendered
    }
  }
  backend_workload = merge(local.workload_template, local.backend_play)
}

# In this step we encrypt the fields of the contract and sign the env and workload field. The certificate to execute the
# encryption it built into the provider and matches the latest HPCR image. If required it can be overridden.
# We use a temporary, random keypair to execute the signature. This could also be overriden.
resource "hpcr_text_encrypted" "backend_contract" {
  text      = yamlencode(local.backend_workload)
  cert      = var.HPCR_CERT == "" ? null : var.HPCR_CERT
}

resource "local_file" "backend_contract" {
  count    = var.DEBUG ? 1 : 0
  content  = yamlencode(local.backend_workload)
  filename = "backend_plain.yml"
  file_permission = "0664"
}

resource "local_file" "backend_contract_encrypted" {
  content  = hpcr_text_encrypted.backend_contract.rendered
  filename = "backend.yml"
  file_permission = "0664"
}
