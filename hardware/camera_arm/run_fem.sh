#!/bin/bash
W=$HOME/projects/_scratch_camera_arm; cd "$W"; rm -rf fem_beam fem_root
CAM_ARM_OUT=$W/fem_beam timeout 900 /snap/bin/freecad.cmd fem_beam.py > beam.log 2>&1
CAM_ARM_OUT=$W/fem_root timeout 1500 /snap/bin/freecad.cmd fem_root.py > root.log 2>&1
grep -hE "^BEAM case|^BEAM geometry" beam.log | cut -c1-200
grep -hE "^ROOT .* (acc|block)" root.log | cut -c1-230 | sort -u
