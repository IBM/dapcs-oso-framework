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
"""Nginx Entrypoint."""

import contextlib
import logging
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import timedelta
from pathlib import PosixPath

from pydantic import ValidationError

from oso.framework.config import AutoLoadConfig, ConfigManager
from oso.framework.core.logging import LoggingFactory, get_logger
from oso.framework.exceptions import StartupException

template = """
daemon off;
pid {home}/nginx.pid;

events {{
    worker_connections 1024;
}}

http {{
    map $http_x_trace_id $trace_id {{
        ""      $request_id;
        default $http_x_trace_id;
    }}

    log_format basic    'trace=$trace_id\tclient=$remote_addr\t'
                        'verify=$ssl_client_verify\tuser=$ssl_client_s_dn\t'
                        'request=$request\ttime=$request_time\tstatus=$status\t';
    access_log {home}/nginx.log.d/access.log basic;
    error_log {home}/nginx.log.d/nginx.log {log_level};

    proxy_connect_timeout {nginx_timeout};
    proxy_read_timeout {nginx_timeout};
    proxy_send_timeout {nginx_timeout};

    server_tokens off;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header Cache-Control "no-cache, no-store, must-revalidate" always;
    add_header Content-Security-Policy \
"default-src 'self'; frame-ancestors 'none';" always;
    add_header X-Content-Type-Options "nosniff";
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-XSS-Protection "1; mode=block";
    add_header Connection "close";
    add_header Content-Type "application/json";
    add_header Access-Control-Allow-Origin $http_origin always;
    add_header Access-Control-Allow-Methods 'GET, POST' always;
    add_header Access-Control-Allow-Credentials 'true' always;
    add_header Access-Control-Allow-Headers
        'Origin, Content-Type, Accept, Authorization' always;

    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;

    ssl_certificate {home}/certificates/server.crt;
    ssl_certificate_key {home}/certificates/server.key;

    proxy_set_header X-SSL-Cert $ssl_client_escaped_cert;
    proxy_set_header X-Trace-ID $trace_id;
    proxy_set_header X-SSL-Client-Verify $ssl_client_verify;

    server {{
        listen 4000 ssl;
        server_name _;

        ssl_client_certificate {home}/certificates/oso-ca.crt;
        ssl_verify_client optional;
        ssl_verify_depth 3;

        location / {{
            location /api/ {{
                proxy_pass http://127.0.0.1:8080;
            }}
            proxy_pass http://127.0.0.1:8080/_/;
        }}
    }}
}}
""".strip()


class NginxConfig(AutoLoadConfig, _config_prefix="nginx"):
    """Exposed Nginx Configuration.

    Attributes
    ----------
    timeout : `datetime.timedelta`, default=60s, envvar=NGINX__TIMEOUT
        Controls Nginx timeout.
    """

    timeout: timedelta = timedelta(seconds=60)


def access_logs(fifo: PosixPath) -> None:
    """Nginx Access Logs.

    Convert access logs into structured logs. The format is set by the generated nginx
    configuration in the format of `KEY=VALUE` pairs, separated by tablines.
    """
    logger = get_logger("proxy.access")

    os.mkfifo(fifo)
    logger.info(f"FIFO {str(fifo)} created for logging")
    with open(fifo, "r") as pipe:
        for line in pipe:
            access = {
                "nginx": {
                    k: v
                    for k, _, v in [
                        kv.partition("=") for kv in line.strip().split("\t")
                    ]
                },
            }
            # Reformat uuid with dashes if valid
            with contextlib.suppress(KeyError, ValueError):
                access["nginx"]["trace"] = str(uuid.UUID(access["nginx"]["trace"]))
            logger.info("nginx access", **access)


def nginx_logs(fifo: PosixPath) -> None:
    """Nginx Logs.

    Routine to parse nginx logs into structured logs. Nginx logs are in the format of::

        DATE TIME [LEVEL] THREAD: EVENT, META_KEY: META_VALUE, ...
    """
    logger = get_logger("proxy.log")

    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "notice": logging.INFO,
        "warn": logging.WARNING,
        "error": logging.ERROR,
        "crit": logging.CRITICAL,
        "alert": logging.WARNING,
        "emerg": logging.CRITICAL,
    }

    os.mkfifo(fifo)
    logger.info(f"FIFO {str(fifo)} created for logging")
    with open(fifo, "r") as pipe:
        for line in pipe:
            values = line.strip().split(", ")
            header, _, event = values[0].partition(": ")
            level = level_map[header[header.find("[") + 1 : header.find("]")]]
            metadata = {
                "nginx": {
                    k.strip(): v.strip(' "')
                    for k, _, v in [log.partition(": ") for log in values[1:]]
                }
            }
            logger.log(level=level, event=event, **metadata)


def main() -> None:
    """Entrypoint."""
    from oso.framework.config.models import app, certs, logging  # noqa: F401

    try:
        config = ConfigManager.reload()
    except ValidationError as e:
        get_logger("failover").error(e)
        raise StartupException("Configuration Error")

    LoggingFactory(config.app.name, config.logging.level_as_int)
    logger = get_logger("proxy.main")

    nginx_conf = config.app.root / "nginx.conf"
    nginx_log_dir = config.app.root / "nginx.log.d"
    nginx_acc = nginx_log_dir / "access.log"
    nginx_log = nginx_log_dir / "nginx.log"

    if not nginx_conf.is_file():
        logger.info("Generating files")

        config.certs.export(config.app.root)
        logger.info("Wrote certificates to file")

        render = template.format(
            log_level="debug" if config.app.debug else "info",
            home=str(config.app.root),
            nginx_timeout=str(int(config.nginx.timeout.total_seconds())) + "s",
        )
        nginx_conf.write_text(render)
        logger.info("Rendered config to file")

    nginx = shutil.which("nginx")
    if nginx:
        logger.info(f"Nginx at: {nginx}")

        nginx_log_dir.mkdir(mode=0o700, exist_ok=True)

        returncode = 0
        try:
            l1 = multiprocessing.Process(
                target=access_logs,
                args=[nginx_acc],
            ).start()
            l2 = multiprocessing.Process(
                target=nginx_logs,
                args=[nginx_log],
            ).start()
            logger.info("Log forwarding started")

            time.sleep(1)

            nginx_proc = subprocess.Popen(
                [
                    nginx,
                    "-c",
                    str(nginx_conf),
                    "-e",
                    nginx_log,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Nginx started")
            returncode = nginx_proc.wait()
        except Exception:
            logger.error("Unexpected proxy startup exception.")
            returncode = -255
        finally:
            logger.info(f"Exited with {returncode}")
            with contextlib.suppress(Exception):
                l1.kill()  # type: ignore
            with contextlib.suppress(FileNotFoundError):
                os.unlink(nginx_acc)
            with contextlib.suppress(Exception):
                l2.kill()  # type: ignore
            with contextlib.suppress(FileNotFoundError):
                os.unlink(nginx_log)
            sys.exit(returncode)

    raise StartupException("Could not find nginx executable.")
