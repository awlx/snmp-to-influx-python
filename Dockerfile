FROM python:3.10.0-alpine3.14 as builder

COPY requirements.txt /requirements.txt
COPY scraper.py /scraper.py

RUN apk add -U alpine-sdk net-snmp net-snmp-dev &&\ 
    pip3 install `cat requirements.txt` &&\
    pip3 install nuitka

RUN python3 -m nuitka --standalone --follow-imports --show-memory --show-progress /scraper.py

FROM alpine:latest

COPY --from=builder /scraper.dist /scraper.dist

RUN chmod g+rwX /scraper.dist/scraper

USER 1001

ENTRYPOINT ["/scraper.dist/scraper"]
