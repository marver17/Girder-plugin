######### Dockerfile for Girder 5 #########
# using fork suggest by Paul

FROM ubuntu:22.04

LABEL maintainer="Kitware, Inc. <kitware@kitware.com>"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LC_ALL=C.UTF-8


RUN apt-get update 
RUN apt-get install -qy \
    gcc \
    libpython3-dev \
    git \
    libldap2-dev \
    libsasl2-dev \
    python3-pip \
    curl \
    locales \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --upgrade --no-cache-dir  \
    setuptools \
    setuptools_scm \
    wheel \
    pip

# Creare utente non-root
RUN groupadd -g 1000 girder && \
    useradd -m -u 1000 -g girder -s /bin/bash girder

RUN curl -LJ https://github.com/krallin/tini/releases/download/v0.19.0/tini -o /sbin/tini && \
    chmod +x /sbin/tini

RUN curl -sL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -qy nodejs

ENV PATH="/usr/local/node:$PATH"

RUN mkdir /girder
WORKDIR /girder

# Configurare ownership per girder e workspace
RUN mkdir -p /home/girder/.local/share/girder /workspace && \
    chown -R girder:girder /girder /home/girder /workspace

RUN git clone --branch v4-integration --single-branch https://github.com/girder/girder.git /girder

RUN cd /girder/girder/web && npm i && npm run build

RUN pip install --break-system-packages -e /girder

# COPY plugins.txt /girder/plugins.txt
# RUN pip3 install -r /girder/plugins.txt



COPY ./oauth2 /girder/oauth2
RUN pip install --break-system-packages -e /girder/oauth2

# RUN girder build && \
#     rm --recursive --force \
#     /root/.npm \
#     /usr/local/lib/python*/site-packages/girder/web_client/node_modules


EXPOSE 8080

# Create startup script for Girder
RUN echo '#!/bin/bash\nexec girder serve "$@"' > /usr/local/bin/start-girder.sh && \
    chmod +x /usr/local/bin/start-girder.sh

# Switch a utente non-root
USER girder

ENTRYPOINT ["/bin/bash"]
