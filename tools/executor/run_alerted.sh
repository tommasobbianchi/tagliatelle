#!/usr/bin/env bash
# Run a command on the executor and push every output line starting with ">>>" to Telegram (phone sound),
# and speak the line on the executor's Bluetooth speaker (say.sh, offline espeak-ng), so nobody has to watch the terminal.   run_alerted.sh user@host 'cmd'   (set RING_CMD to also ring a phone, NOTIFY_CMD for the chat)
RING_CMD="${RING_CMD-$HOME/.claude/scripts/ring-phone}"; [ -x "$RING_CMD" ] || RING_CMD=
ssh -tt "$1" "$2" 2>&1 | while IFS= read -r l; do
  echo "$l"
  case "$l" in '>>>'*) ${NOTIFY_CMD:-claude-tg} notify -l warning -t "Snapmaker" "${l#>>> }" >/dev/null 2>&1; [ -n "$RING_CMD" ] && $RING_CMD "${l#>>> }" >/dev/null 2>&1; ssh -n "$1" "~/tagliatelle-exec/app/say.sh '${l#>>> }'" >/dev/null 2>&1 ;; esac
done
