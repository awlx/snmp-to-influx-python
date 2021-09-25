# snmp-to-influx-python

This scrapes all possible interfaces for a device and sends the data to the configured InfluxDB.

The idea was born, because Telegraf Docker container was too big to run on a Mikrotik CCR2004-1G-12S+2XS (it has only 128mb flash). Also the approach is to be able to cut off inbound internet access to the Mikrotik completely and just send metrics via HTTPS to InFluxDb.

Also the idea is to scrape multiple devices from the Mikrotik and just upload all this data without the need to install the container on every device.

Container size
```
REPOSITORY                           TAG               IMAGE ID       CREATED             SIZE
scraper                              latest            2861ced8e846   About an hour ago   55.8MB
```

Example Dashboard
<img width="1324" alt="Screenshot 2021-09-25 at 18 13 19" src="https://user-images.githubusercontent.com/6527744/134778264-cd808d63-4e8e-4366-bf01-e74f30d3a907.png">

Disk usage after install

<img width="511" alt="Screenshot 2021-09-25 at 18 36 00" src="https://user-images.githubusercontent.com/6527744/134778982-34540844-eee3-44d6-b319-587bcf8c8baa.png">

### Config

```
default_community: public
devices:
  - hostname: testhost01
    ip: 127.0.0.1
    community: public
    username:
    password:
influxdb:
  uri: testinflux
  username: testuser
  password: testpw
  database: nicedb
```

### RouterOS Setup

Select and export a corresponding docker image like this:
```
docker pull ghcr.io/awlx/snmp-to-influx-python:latest@sha256:f225b522613270f6b36fb22683e78ff466c47f5c052aa911b933f583b602ab51
docker save snmp-to-influx-python:latest > snmp.tar 
```

Requirements:
- Working container package and veth pairs on the Mikrotik device
- You uploaded the snmp.tar to the rootfs 
- You created a directory `config` on part0 and added a `scraper.yaml`

```
/container/mounts/add name=scraper src=config dst=/config
/container/envs/add list=snmp name=SNMP_TO_INFLUX_CONFIG_FILE value=/config/scraper.yaml
/container/add file=snmp.tar interface=veth1 root-dir=snmp mounts=scraper logging=yes envlist=snmp
/container/start <insert_container_number_here>
```

When everything works you should see an output like this
```
[admin@MikroTik] > /container/print 
 0 file=snmp.tar name="a1f6ef78-bdcb-4fc8-8bc4-4eac98743ff0" tag="scraper:latest" os="linux" arch="arm64" interface=veth1 envlist="snmp" root-dir=snmp mounts=scraper dns="" logging=yes status=running 
[admin@MikroTik] >
```

Logs can be found in `/log/print`

### Downloads

All pre-build containers can be downloaded [here](https://github.com/awlx/snmp-to-influx-python/pkgs/container/snmp-to-influx-python)

References:
- [Running Containers on RouterOS](https://forum.mikrotik.com/viewtopic.php?f=1&t=178342)
- [Dashboard](https://stats.ffmuc.net/d/V1sioJN7k/mikrotik-monitoring?orgId=1)
