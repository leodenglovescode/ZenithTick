"""Gunicorn process settings derived from validated deployment environment."""

from __future__ import annotations

import ipaddress
import os


def _deployment_address() -> str:
    value = os.environ.get("ZENITICK_BIND", "").strip()
    if not value:
        raise RuntimeError("ZENITICK_BIND is required for production")
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise RuntimeError("ZENITICK_BIND must be one explicit IPv4 address") from exc

    private_networks = (
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.168.0.0/16"),
    )
    if not any(address in network for network in private_networks):
        raise RuntimeError("ZENITICK_BIND must be a private RFC1918 LAN address")
    return str(address)


def _deployment_port() -> int:
    try:
        value = int(os.environ.get("ZENITICK_PORT", "8989"))
    except ValueError as exc:
        raise RuntimeError("ZENITICK_PORT must be an integer") from exc
    if not 1024 <= value <= 65535:
        raise RuntimeError("ZENITICK_PORT must be between 1024 and 65535")
    return value


bind = f"{_deployment_address()}:{_deployment_port()}"
workers = 1
threads = 4
timeout = 15
accesslog = "-"
errorlog = "-"
