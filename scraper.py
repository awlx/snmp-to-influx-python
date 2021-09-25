#!/usr/bin/python3
import datetime
import yaml
import dataclasses
from influxdb import InfluxDBClient
from influxdb import SeriesHelper
import os
import sys
import math
from multiprocessing import Pool
from functools import lru_cache
from easysnmp import Session
from requests.auth import HTTPDigestAuth
from typing import Dict, Union, Any, List, Optional
from ipaddress import IPv4Network, IPv6Network


class Error(Exception):
    """Base Exception handling class."""


class ConfigFileNotFoundError(Error):
    """File could not be found on disk."""


SNMP_TO_INFLUX_CONFIG_OS_ENV = "SNMP_TO_INFLUX_CONFIG_FILE"
SNMP_TO_INFLUX_CONFIG_DEFAULT_LOCATION = "./scraper.yaml"


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
    ip: Union[IPv4Network, IPv6Network]
    username: str
    password: str

    @classmethod
    def from_dict(cls, device_cfg: Dict[str, str]) -> "Device":
        return cls(
            hostname=device_cfg["hostname"],
            community=device_cfg["community"],
            username=device_cfg["username"],
            password=device_cfg["password"],
            ip=device_cfg["ip"],
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


DeviceList = Config.from_dict(load_config()).devices
influxdb_cfg = Config.from_dict(load_config()).influxdb

# To convert readings in MBits
_TO_MBIT = math.pow(10, 6)


def SNMPpollv2(Device):
    try:
        session = Session(hostname=Device.ip, community=Device.community, version=2)
        return pollDevice(session, Device.hostname)
    except Exception as e:
        return "ERROR - SNMPv2 error" + str(e)


def SNMPpollv3(Device):
    try:
        session = Session(
            hostname=Device.ip,
            version=3,
            security_level="auth_with_privacy",
            security_username=Device.username,
            auth_protocol="SHA",
            auth_password=Device.password,
            privacy_protocol="AES",
            privacy_password=Device.password,
        )
        return pollDevice(session, hostname)
    except Exception as e:
        return "ERROR - SNMPv3 error" + str(e)


_ifXEntry = "1.3.6.1.2.1.31.1.1.1"
_ifHCInOctets = "6"
_ifHCOutOctets = "7"
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


def pollDevice(session: Session, hostname: str) -> Dict[str, str]:
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
                    "ifout": int(values["_ifHCInOctets"]),
                    "ifin": int(values["_ifHCOutOctets"]),
                    "ifinerr": int(values["_ifInErrors"]),
                    "ifouterr": int(values["_ifOutErrors"]),
                },
            }
        ]

        client = InfluxDBClient(
            influxdb_cfg.uri,
            443,
            influxdb_cfg.username,
            influxdb_cfg.password,
            influxdb_cfg.database,
            ssl=True,
        )
        print(dbpayload)
        try:
            client.write_points(dbpayload)
        except Exception as e:
            print(e)

    return 0


def StartPoll(device):
    if device.username:
        return SNMPpollv3(device)
    elif device.community:
        return SNMPpollv2(device)
    else:
        return "Invalid device entity"


for device in DeviceList.devices:
    StartPoll(device)
