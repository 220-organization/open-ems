FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-21-jre-headless wget ca-certificates \
    && wget -qO- https://repo1.maven.org/maven2/org/flywaydb/flyway-commandline/9.22.3/flyway-commandline-9.22.3-linux-x64.tar.gz \
        | tar xz -C /opt \
    && ln -s /opt/flyway-9.22.3/flyway /usr/local/bin/flyway \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY db ./db
COPY scripts ./scripts

RUN chmod +x /app/scripts/docker-entrypoint.sh

EXPOSE 8090

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
