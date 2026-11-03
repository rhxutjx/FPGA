#!/bin/sh
set -u
DIR=/home/kvdev/work_pc2_pcie/batch_probe_20261030
runuser -u kvdev -g kvdev -G users -G render -G video -- \
  env PYTHONPATH="$DIR" python3 "$DIR/probe_shapes_noc.py"
code=$?
echo "===PROBE_DONE=== code=$code"
