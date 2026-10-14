#!/bin/bash
# on the workstation: generate both solids, then FEM each. cwd = this folder.
set -u
W=$HOME/projects/_scratch_camera_arm
cd "$W"
rm -rf gen fem_uniform8 fem_sized
CAM_ARM_OUT=$W/gen /snap/bin/freecad.cmd camera_arm.py > gen.log 2>&1
for v in uniform8 sized; do
  [ -f gen/camera_arm_$v.FCStd ] || { echo "no solid for $v"; continue; }
  CAM_ARM_IN=$W/gen/camera_arm_$v.FCStd CAM_ARM_OUT=$W/fem_$v timeout 1500 /snap/bin/freecad.cmd fem_arm.py > fem_$v.log 2>&1
done
grep -h "RESULT" gen.log
for v in uniform8 sized; do echo "== $v"; grep -E "FEM (case|mesh|High|done)|nonpositive jacobian elements|exit code" fem_$v.log | sort -u; done
