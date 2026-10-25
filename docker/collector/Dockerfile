# Image for `oasees-sdk telemetry deploy-collector --image <this image>`.
# The collector script itself comes from a ConfigMap; this only holds its packages.
# Keep the versions in line with COLLECTOR_REQUIREMENTS in cli/commands/telemetry.py.
#
#   docker build -t <registry>/oasees-collector:latest docker/collector
#   docker push <registry>/oasees-collector:latest
FROM python:3.9-slim
RUN pip install --no-cache-dir python-socketio==5.17.0 requests==2.32.5
