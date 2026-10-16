#!/usr/bin/env bash
# Run a command on the executor and push every output line starting with ">>>" to Telegram (phone sound),
# and speak the line on the executor's Bluetooth speaker (say.sh, offline espeak-ng), so nobody has to watch the terminal.   run_alerted.sh user@host 'cmd'
ssh -tt "$1" "$2" 2>&1 | while IFS= read -r l; do
  echo "$l"
  case "$l" in '>>>'*) ${NOTIFY_CMD:-claude-tg} notify -l warning -t "Snapmaker" "${l#>>> }" >/dev/null 2>&1; ssh -n "$1" "~/tagliatelle-exec/app/say.sh '${l#>>> }'" >/dev/null 2>&1 ;; esac
done
