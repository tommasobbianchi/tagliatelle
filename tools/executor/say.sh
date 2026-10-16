#!/bin/sh
# Speak a phrase on the executor's speaker (offline, Italian): say.sh "text". Falls back to the beep if espeak-ng is missing.
if command -v espeak-ng >/dev/null; then espeak-ng -v it -s 150 -a 200 --stdout "$1" | pw-play -
else exec "$HOME/tagliatelle-exec/app/beep.sh"; fi
