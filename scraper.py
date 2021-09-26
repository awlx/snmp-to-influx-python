#!/usr/bin/python3
import dataclasses
import datetime
import os
import sys
import threading
import time
import requests

from ipaddress import IPv4Address, IPv6Address, ip_address
from functools import lru_cache
from typing import Dict, Union, Any, List, Optional
from easysnmp import Session
from influxdb import InfluxDBClient

import yaml


class Error(Exception):
    """Base Exception handling class."""


class ConfigFileNotFoundError(Error):
    """File could not be found on disk."""


requests.packages.urllib3.disable_warnings()

SNMP_TO_INFLUX_CONFIG_OS_ENV = "SNMP_TO_INFLUX_CONFIG_FILE"
SNMP_TO_INFLUX_CONFIG_DEFAULT_LOCATION = "./scraper.yaml"
_POLLING_FREQUENCY = datetime.timedelta(seconds=60)


@dataclasses.dataclass
class Device:
    """A representation of a Device in Configuration file.
    Attributes:
        hostname: str
        community: str
        ip: Union[IPv4Network, IPv6Network]
    """

    hostname: str
    community: str
    ip: Union[IPv4Address, IPv6Address]
    username: str
    password: str

    @classmethod
    def from_dict(cls, device_cfg: Dict[str, str]) -> "Device":
        return cls(
            hostname=device_cfg["hostname"],
            community=device_cfg["community"],
            username=device_cfg["username"],
            password=device_cfg["password"],
            ip=ip_address(device_cfg["ip"]),
        )


@dataclasses.dataclass
class Devices:
    """A representation of the configuration file.
    Attributes:
        devices: List of all devices
    """

    devices: List[Device]

    @classmethod
    def from_dict(cls, cfg: List[Device]) -> "Devices":
        """Creates a Config object from a configuration file.
        Arguments:
            cfg: The configuration file as a dict.
        Returns:
            A Config object.
        """
        devices = []
        for entry in cfg:
            devices.append(Device.from_dict(entry))
        return cls(devices=devices)


@dataclasses.dataclass
class Influxdb:
    """A representation of a Device in Configuration file.
    Attributes:
        hostname: str
        community: str
        ip: Union[IPv4Network, IPv6Network]
    """

    uri: str
    username: str
    password: str
    database: str

    @classmethod
    def from_dict(cls, influxdb_cfg: Dict[str, str]) -> "Influxdb":
        return cls(
            uri=influxdb_cfg["uri"],
            username=influxdb_cfg["username"],
            password=influxdb_cfg["password"],
            database=influxdb_cfg["database"],
        )


@dataclasses.dataclass
class Config:
    """A representation of the configuration file.
    Attributes:
        default_community: The default snmp community.
        device: The snmp device.
        influxdb: The Influxdb configuration.
    """

    default_community: str
    devices: List[Devices]
    influxdb: Influxdb

    @classmethod
    def from_dict(cls, cfg: Dict[str, str]) -> "Config":
        """Creates a Config object from a configuration file.
        Arguments:
            cfg: The configuration file as a dict.
        Returns:
            A Config object.
        """
        devices_cfg = Devices.from_dict(cfg["devices"])
        influxdb_cfg = Influxdb.from_dict(cfg["influxdb"])
        return cls(
            default_community=cfg["default_community"],
            devices=devices_cfg,
            influxdb=influxdb_cfg,
        )


@lru_cache(maxsize=10)
def fetch_from_config(key: str) -> Optional[Union[Dict[str, Any], List[str]]]:
    """Fetches a specific key from configuration.
    Arguments:
        key: The named key to fetch.
    Returns:
        The config value associated with the key
    """
    return load_config().get(key)


def load_config() -> Dict[str, str]:
    """Fetches and validates configuration file from disk.
    Returns:
        Linted configuration file.
    """
    cfg_contents = fetch_config_from_disk()
    try:
        config = yaml.safe_load(cfg_contents)
    except yaml.YAMLError as e:
        print("Failed to load YAML file: %s", e)
        sys.exit(1)
    try:
        _ = Config.from_dict(config)
        return config
    except (KeyError, TypeError) as e:
        print("Failed to lint file: %s", e)
        sys.exit(2)


def fetch_config_from_disk() -> str:
    """Fetches config file from disk and returns as string.
    Raises:
        ConfigFileNotFoundError: If we could not find the configuration file on disk.
    Returns:
        The file contents as string.
    """
    config_file = os.environ.get(
        SNMP_TO_INFLUX_CONFIG_OS_ENV, SNMP_TO_INFLUX_CONFIG_DEFAULT_LOCATION
    )
    try:
        with open(config_file, "r") as stream:
            return stream.read()
    except FileNotFoundError as e:
        raise ConfigFileNotFoundError(
            f"Could not locate configuration file in {config_file}"
        ) from e


def SNMPpollv2(device_cfg: Device) -> bool:
    """Polls a device via SNMPv2."""
    try:
        session = Session(
            hostname=str(device_cfg.ip), community=device_cfg.community, version=2
        )
        return pollDevice(session, device_cfg.hostname)
    except Exception as e:
        raise ValueError("ERROR - SNMPv2 error" + str(e)) from e


def SNMPpollv3(device_cfg: Device) -> bool:
    """Polls a device via SNMPv3."""
    try:
        session = Session(
            hostname=str(device_cfg.ip),
            version=3,
            security_level="auth_with_privacy",
            security_username=device_cfg.username,
            auth_protocol="SHA",
            auth_password=device_cfg.password,
            privacy_protocol="AES",
            privacy_password=device_cfg.password,
        )
        return pollDevice(session, hostname)
    except Exception as e:
        raise ValueError("ERROR - SNMPv3 error" + str(e)) from e


_ifXEntry = "1.3.6.1.2.1.31.1.1.1"
_ifHCInOctets = "6"
_ifHCOutOctets = "10"
_ifName = "1"

_ifTable = "1.3.6.1.2.1.2.2.1"
_ifInErrors = "14"
_ifOutErrors = "20"
_ifDescr = "2"

_OIDS = {
    "_ifHCInOctets": f"{_ifXEntry}.{_ifHCInOctets}",
    "_ifHCOutOctets": f"{_ifXEntry}.{_ifHCOutOctets}",
    "_ifInErrors": f"{_ifTable}.{_ifInErrors}",
    "_ifOutErrors": f"{_ifTable}.{_ifOutErrors}",
    "_ifDescr": f"{_ifTable}.{_ifDescr}",
}


def pollDevice(session: Session, hostname: str) -> bool:

    interfaces = dict()
    for interface in session.walk(f"{_ifXEntry}.{_ifName}"):
        interfaces[interface.value] = {
            "oid_index": interface.oid_index
            if interface.oid_index
            else interface.oid.split(".")[-1]
        }

    for oid_name, oid in _OIDS.items():
        for name, _ in interfaces.items():
            snmp_info = session.get(f"{oid}.{interfaces[name]['oid_index']}")
            interfaces[name].update({oid_name: snmp_info.value})

    for name, values in interfaces.items():
        dbpayload = [
            {
                "measurement": "interface_stats",
                "tags": {
                    "host": hostname,
                    "interface": name,
                    "interface_description": values["_ifDescr"],
                },
                "time": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "fields": {
                    "ifin": int(values["_ifHCInOctets"]),
                    "ifout": int(values["_ifHCOutOctets"]),
                    "ifinerr": int(values["_ifInErrors"]),
                    "ifouterr": int(values["_ifOutErrors"]),
                },
            }
        ]
        return upload_to_influx(dbpayload)


def upload_to_influx(payload: Any) -> bool:
    """Uploads a payload to influxDB."""
    influxdb_cfg = Config.from_dict(load_config()).influxdb
    client = InfluxDBClient(
        influxdb_cfg.uri,
        443,
        influxdb_cfg.username,
        influxdb_cfg.password,
        influxdb_cfg.database,
        ssl=True,
    )
    print(payload)
    try:
        client.write_points(payload)
        return True
    except InfluxDBClientError as e:
        print(e)
        return False


def StartPoll(device: Config) -> Dict[str, str]:
    """Polls a device via SNMPv2 or SNMPV3 depending on configuration."""
    if device.username:
        return SNMPpollv3(device)
    if device.community:
        return SNMPpollv2(device)
    raise ValueError(f"Invalid device configuration: {device}")


def main():
    """Starts the periodic scraper."""
    DeviceList = Config.from_dict(load_config()).devices

    while True:
        polling_threads = [
            threading.Thread(target=StartPoll, args=(device,))
            for device in DeviceList.devices
        ]
        _ = [thread.start() for thread in polling_threads]
        time.sleep(_POLLING_FREQUENCY.total_seconds())


if __name__ == "__main__":
    main()
