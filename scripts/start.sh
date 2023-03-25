#!/bin/bash
#
# Start the lab controller application inside the Docker image.

set -eu

uvicorn --factory jupyterlabcontroller.main:create_app \
    --host 0.0.0.0 --port 8080
