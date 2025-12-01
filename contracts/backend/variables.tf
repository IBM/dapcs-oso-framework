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



variable "DEBUG" {
  type        = bool
  description = "Create debug contracts, plaintext"
  default     = false
}

variable "BACKEND_PLUGIN_IMAGE" {
  type = string
  description = "Backend plugin image containing registry"
}

variable "HPCR_CERT" {
  type        = string
  description = "Public HPCR certificate for contract encryption"
  nullable    = true
  default     = null
}

variable "GREP11_HOST" {
  type = string
  description = "GREP11 backend endpoint"
  default = "192.168.96.21"
} 

variable "GREP11_PORT" {
  type = string
  description = "GREP11 backend endpoint port"
  default = "9876"
}

variable "GREP11_CA" {
  type = string
  description = "GREP11 CA certificate (in base64)"
}

variable "GREP11_CLIENT_KEY" {
  type = string
  description = "GREP11 client key PKCS8 (in base64)"
}

variable "GREP11_CLIENT_CERT" {
  type = string
  description = "GREP11 client certificate (in base64)"
}

variable "WORKLOAD_VOL_SEED" {
  type = string
  description = "Workload volume encryption seed"
}

variable "PORT" {
  type        = string
  description = "External port number for api"
  default     = "4000"
}

# Add aditional ISV variables here #
