# Bob Shell harness container.
# Ubuntu is the friendliest base for a `curl | bash` installer: it ships the
# certs + glibc that most IBM tooling expects, and apt makes deps trivial.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    # Candidate install locations for the `bob` binary + a place for our API.
    PATH="/root/.local/bin:/root/.bob/bin:/usr/local/bin:/usr/bin:${PATH}" \
    BOB_MODE=unrestricted-dev \
    # Bob runs from the container root so it governs the WHOLE container.
    BOB_WORKDIR=/

# System deps: curl + certs for the installer, bash for the install script,
# git for repo work inside the container, python for the REST wrapper.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        bash \
        git \
        cron \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Bob Shell requires Node.js >= 22. Use an exact Node 24 package release so
# rebuilding this commit does not silently change the runtime.
ARG NODE_VERSION=24.21.0-1nodesource1
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends "nodejs=${NODE_VERSION}" \
    && rm -rf /var/lib/apt/lists/* \
    && node --version

# Install a PINNED Bob Shell version for reproducible builds. The official
# `curl | bash` installer always grabs "latest"; instead we install the exact
# release tarball via npm (which is what the installer does under the hood).
# Bump BOB_VERSION to upgrade. Verify releases at:
#   https://bob.ibm.com/releases/?bob=shell
ARG BOB_VERSION=2.0.5
ARG BOB_SHA256=eff232eb1b69f34f984ddd295e6960470058ca922b1c751879c5a8d06199f566
RUN curl -fsSL \
        "https://s3.us-south.cloud-object-storage.appdomain.cloud/bob-shell/bobshell-${BOB_VERSION}.tgz" \
        -o /tmp/bobshell.tgz \
    && echo "${BOB_SHA256}  /tmp/bobshell.tgz" | sha256sum -c - \
    && npm install -g --loglevel=error /tmp/bobshell.tgz \
    && rm -f /tmp/bobshell.tgz \
    && bob --version

# Bob's project config lives at the container root /.bob so it applies to the
# whole container when Bob runs with cwd=/. It holds custom_modes.yaml and the
# rules-unrestricted-dev/ AGENT.md.
# Seed Bob's user settings separately. Disabling auto-update preserves the
# version pin for the lifetime of the container.
COPY .bob/ /.bob/
COPY .bob/settings/settings.json /root/.bob/settings/settings.json

# REST API wrapper around `bob run`.
WORKDIR /app
COPY api/requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt
COPY api/ /app/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Bob edits are scoped to the starting dir (--yolo). We run from / so Bob can
# reach the whole container; /workspace remains as the compose volume mount.
RUN mkdir -p /workspace
WORKDIR /

EXPOSE 8080

# Report container readiness via the API's own liveness endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["serve"]
