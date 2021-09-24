FROM arm64v8/python:3.9-alpine3.14 as builder

COPY requirements.txt /requirements.txt
COPY scrapper.py /scrapper.py

RUN apk add -U alpine-sdk net-snmp net-snmp-dev &&\ 
    pip3 install `cat requirements.txt` &&\
    pip3 install nuitka

RUN python3 -m nuitka --standalone --follow-imports --show-memory --show-progress /scrapper.py

FROM arm64v8/alpine:latest

COPY --from=builder /scrapper.dist /scrapper.dist

RUN chmod 0755 /scrapper.dist/scrapper

ENTRYPOINT ["/scrapper.dist/scrapper"]