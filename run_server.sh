#!/bin/bash
# Launch the Optimus-3 GUI server.
# - Uses the `myenv` conda environment.
# - Forces Java 8 onto PATH (Minecraft / MCP engine requires it; system default is Java 21).
# - Runs under xvfb so any GL code has a virtual display.
# - GPU rendering: with MINESTUDIO_GPU_RENDER=1 the Minecraft client renders on the
#   A100 via VirtualGL (vglrun), ~1.6x faster than CPU/software rendering (~27 vs ~17 fps).
#   Set MINESTUDIO_GPU_RENDER=0 to fall back to CPU rendering if GPU rendering misbehaves.
set -e

source /home/ubuntu/miniconda3/etc/profile.d/conda.sh
conda activate myenv

export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
export MINESTUDIO_GPU_RENDER="${MINESTUDIO_GPU_RENDER:-1}"

# VirtualGL needs read/write on the A100's DRI nodes. The `ubuntu` user is in the
# video/render groups (effective after re-login); if a node isn't accessible in
# this session, grant it directly (resets on reboot).
if [ "$MINESTUDIO_GPU_RENDER" = "1" ]; then
  for dev in /dev/dri/renderD128 /dev/dri/card1; do
    [ -r "$dev" ] && [ -w "$dev" ] || sudo chmod a+rw "$dev" 2>/dev/null || true
  done
fi

cd /ephemeral/Optimus-3

echo "java: $(java -version 2>&1 | head -1)"
echo "python: $(which python)"

exec xvfb-run -a python gui_server.py
