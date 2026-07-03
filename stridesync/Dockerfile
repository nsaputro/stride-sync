ARG BUILD_FROM=ghcr.io/hassio-addons/base:18.0.1
FROM ${BUILD_FROM}

# Python 3.12 runtime (ghcr.io/hassio-addons/base is Alpine but not python-preinstalled)
RUN apk add --no-cache python3 py3-pip

WORKDIR /app

# Install Python dependencies
COPY app/requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy application code
COPY app/ .

# s6-overlay services + init scripts
COPY rootfs /

RUN chmod a+x /etc/services.d/*/run /etc/cont-init.d/* 2>/dev/null || true

# No CMD/EXPOSE needed beyond the port declared in config.yaml — s6-overlay (the base image's
# entrypoint) starts everything under /etc/services.d/ automatically.
