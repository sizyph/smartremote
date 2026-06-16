#!/usr/bin/env bash
# Submit a job file to a remote SmartRemote inbox over SFTP, atomically.
# Upload to a hidden .part then rename on the server (atomic on one FS) so the
# dispatcher never reads a half-transferred file.
#
# Usage: scripts/submit.sh user@host:/path/to/SmartRemote/inbox path/to/job.md
set -euo pipefail

DEST="${1:?usage: submit.sh user@host:/remote/inbox local-job.md}"
FILE="${2:?usage: submit.sh user@host:/remote/inbox local-job.md}"
[ -f "$FILE" ] || { echo "no such file: $FILE" >&2; exit 1; }

host="${DEST%%:*}"      # user@host
dir="${DEST#*:}"        # /remote/inbox
base="$(basename "$FILE")"

sftp -b - "$host" >/dev/null <<EOF
-mkdir $dir
put "$FILE" "$dir/.$base.part"
rename "$dir/.$base.part" "$dir/$base"
EOF

echo "submitted $base -> $DEST"
