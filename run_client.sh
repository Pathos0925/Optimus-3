#!/bin/bash
# Launch the Optimus-3 web client (Flask). Single port, reverse-proxies the
# FastAPI gui_server. Forward CLIENT_PORT (default 7860) in VS Code to use it.
source /home/ubuntu/miniconda3/etc/profile.d/conda.sh
conda activate myenv
cd /ephemeral/Optimus-3
export SERVER_HOST="${SERVER_HOST:-127.0.0.1}"
export SERVER_PORT="${SERVER_PORT:-9500}"
export CLIENT_PORT="${CLIENT_PORT:-7860}"
exec python web_client.py
