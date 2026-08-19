#!/bin/bash
# 大批量二进制文件分批推送 GitHub。
#
# 起因：1.5GB 一次性 push 必被掐断（SSL_ERROR_SYSCALL / curl 55），
# 且 git 没有断点续传——一次失败整包重传。所以按体积切批，逐批 commit+push，
# 每批独立成功即落地，失败只需重试当批。push 本身是单次串行的 ref 操作，无法并行。
#
#   ./push_batch.sh <目录> [每批MB，默认100]
#
# 幂等：只处理尚未 tracked 的文件，中断后重跑自动接着走。
set -uo pipefail
DIR="${1:?用法: ./push_batch.sh <目录> [每批MB]}"
LIMIT_MB="${2:-100}"
ROOT="$(git rev-parse --show-toplevel)" || exit 1
cd "$ROOT" || exit 1
LOG="${ROOT}/.git/push_batch.log"

python3 - "$DIR" > /tmp/pb_todo.txt <<'PY'
import subprocess, sys, os
d = sys.argv[1].rstrip('/')
tracked = set(subprocess.run(['git','ls-files',d], capture_output=True, text=True).stdout.split('\n'))
print('\n'.join(f'{d}/{f}' for f in sorted(os.listdir(d))
                if not f.startswith('.') and f'{d}/{f}' not in tracked))
PY

TOTAL=$(grep -c . /tmp/pb_todo.txt || echo 0)
[ "$TOTAL" -eq 0 ] && { echo "全部已提交，无待推文件"; exit 0; }
echo "待推 $TOTAL 个文件，每批约 ${LIMIT_MB}MB" | tee -a "$LOG"

BATCH=0
while [ -s /tmp/pb_todo.txt ]; do
  BATCH=$((BATCH+1))
  LIMIT_MB="$LIMIT_MB" python3 - > /tmp/pb_cur.txt <<'PY'
import os
lim = int(os.environ['LIMIT_MB']) * 1024 * 1024
tot, out = 0, []
for l in open('/tmp/pb_todo.txt'):
    f = l.strip()
    if not f: continue
    s = os.path.getsize(f)
    if out and tot + s > lim: break
    out.append(f); tot += s
print('\n'.join(out))
PY
  N=$(grep -c . /tmp/pb_cur.txt)
  MB=$(python3 -c "import os;print(f'{sum(os.path.getsize(l.strip()) for l in open(\"/tmp/pb_cur.txt\") if l.strip())/1048576:.0f}')")

  git add --pathspec-from-file=/tmp/pb_cur.txt || exit 1
  git commit -q -m "Add ${DIR##*/} files (part $BATCH)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>" || exit 1

  OK=0
  for TRY in 1 2 3 4 5; do
    S=$(date +%s)
    if git push 2>>"$LOG"; then
      echo "[$(date +%H:%M:%S)] 批$BATCH  $N 个 / ${MB}MB  用时 $(( $(date +%s) - S ))s  ✓" | tee -a "$LOG"
      OK=1; break
    fi
    echo "[$(date +%H:%M:%S)] 批$BATCH 第 ${TRY} 次失败，退避 $((TRY*10))s" | tee -a "$LOG"
    sleep $((TRY*10))
  done
  [ "$OK" -eq 0 ] && { echo "批$BATCH 连续失败 5 次，中止（commit 已保留，修好网络后重跑本脚本）" | tee -a "$LOG"; exit 1; }

  python3 - <<'PY'
done_ = {l.strip() for l in open('/tmp/pb_cur.txt') if l.strip()}
rest = [l for l in open('/tmp/pb_todo.txt') if l.strip() and l.strip() not in done_]
open('/tmp/pb_todo.txt','w').writelines(rest)
PY
  echo "            剩余 $(grep -c . /tmp/pb_todo.txt || echo 0) 个" | tee -a "$LOG"
done
echo "全部推送完成，共 $BATCH 批" | tee -a "$LOG"
