from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from .urls import is_http_url


def is_public_host(hostname: str) -> bool:
    try:
        addresses = socket.getaddrinfo(
            hostname,
            None,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror:
        return False

    if not addresses:
        return False

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except ValueError:
            return False

        if not ip.is_global:
            return False

    return True


def is_public_url(url: str) -> bool:
    if not is_http_url(url):
        return False
    hostname = urlparse(url).hostname
    return bool(hostname and is_public_host(hostname))
