#!/bin/sh
#
# Start the lab controller application inside the Docker image.

set -eu

uvicorn --factory controller.main:create_app --host 0.0.0.0 --port 8080
