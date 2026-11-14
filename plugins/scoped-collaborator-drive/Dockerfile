# Build the reviewed Hermes fork separately using its own Dockerfile.
# Pass its immutable local image ID or registry digest, not a floating release tag.
ARG HERMES_BASE
FROM ${HERMES_BASE}
USER root
COPY plugins/scoped-collaborator-drive /opt/collaborator-plugin
# Keep worker dependencies out of Hermes's managed runtime. Preserve the base
# entrypoint and final root user required by its s6 privilege-drop supervision.
RUN python3 -m venv /opt/collaborator-worker && \
    /opt/collaborator-worker/bin/pip install --no-cache-dir /opt/collaborator-plugin && \
    chmod -R a-w /opt/collaborator-plugin /opt/collaborator-worker
# Registry/config/state/ADC are runtime operator mounts, never image layers.
