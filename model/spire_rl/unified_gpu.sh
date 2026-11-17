#!/usr/bin/env bash
# Unified network on the GPU machine (docs/claude-unified-net-design-20261116.md, steps 3-5;
# model/spire_rl/README.md section 2.6). Run from the repository root:
#   bash model/spire_rl/unified_gpu.sh 2>&1 | tee -a runs/unified/all.log
# Every step skips itself when its output exists, so the same command continues after a stop
# (Ctrl+C or a closed window; a data-generation step resumes from <dir>/progress.json).
#
# Settings (environment variables, defaults in brackets):
#   U            output directory                                        [runs/unified]
#   MACRO        macro checkpoint that makes the out-of-combat choices   [runs/small-b-d1/last.pt]
#   PRETRAIN     value pretraining from the Mac (copied over)            [$U/value_pretrain.pt]
#   EVALSET      the 188 fixed combat snapshots (copied over)            [$U/evalset.pkl.gz]
#   MACRO_RUNS   archives that keep the out-of-combat value trained ("" = none)
#                                            [small-b-d1,small-a0-d1,small-a0-d2,small-a0-d3]
#   ENVS         parallel runs for the MCTS teacher                      [number of CPU threads]
#   TEACHER_RUNS runs of MCTS teacher data                               [2000]
#   SP_RUNS      runs of self-play per generation                        [1000]
#   SP_MODE      self-play value scale: norm or rate                     [norm]
#   GENS         self-play generations after gen0 (0 = stop after the gen0 evaluation)  [0]
#   MAX_HOURS    a long step stops after this long (exit code 3; rerun to continue)     [unset]
#   DEVICE [cuda]  BUDGETS [256,512,1024]  EPOCHS [4]  PLAYERS [mcts128,mcts256,net,norm256,rate256]
set -euo pipefail
ROOT=$(pwd)
absp() { case "$1" in /*) echo "$1" ;; *) echo "$ROOT/$1" ;; esac; }
U=$(absp "${U:-runs/unified}")
MACRO=$(absp "${MACRO:-runs/small-b-d1/last.pt}")
PRETRAIN=$(absp "${PRETRAIN:-$U/value_pretrain.pt}")
EVALSET=$(absp "${EVALSET:-$U/evalset.pkl.gz}")
MACRO_RUNS=${MACRO_RUNS-small-b-d1,small-a0-d1,small-a0-d2,small-a0-d3}
CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 8)
ENVS=${ENVS:-$CORES}
TEACHER_RUNS=${TEACHER_RUNS:-2000}
SP_RUNS=${SP_RUNS:-1000}
SP_MODE=${SP_MODE:-norm}
GENS=${GENS:-0}
DEVICE=${DEVICE:-cuda}
BUDGETS=${BUDGETS:-256,512,1024}
EPOCHS=${EPOCHS:-4}
PLAYERS=${PLAYERS:-mcts128,mcts256,net,norm256,rate256}
HOURS=${MAX_HOURS:+--max-hours $MAX_HOURS}
LIMIT=${EVAL_LIMIT:+--limit $EVAL_LIMIT}          # only for a dry run: evaluate the first N snapshots
log() { echo "[$(date '+%F %T')] $*"; }
for f in "$MACRO" "$PRETRAIN" "$EVALSET"; do
  [ -e "$f" ] || { echo "missing $f"; exit 1; }
done
mkdir -p "$U"
cd "$ROOT/model/spire_rl"
py() { python -u "$@"; }

# 1) MCTS teacher data (CPU; the macro checkpoint on the GPU)
log "teacher data -> $U/teacher ($TEACHER_RUNS runs, $ENVS envs, budgets $BUDGETS)"
py -m spire_rl.unified_run gen --macro-ckpt "$MACRO" --out "$U/teacher" --episodes "$TEACHER_RUNS" --envs "$ENVS" \
   --budgets "$BUDGETS" --device "$DEVICE" --first-seed-default 7200000 $HOURS 2>&1 | tee -a "$U/teacher.log"

# 2) gen0 = pretrained value head + imitation of the teacher (GPU)
if [ ! -e "$U/gen0.pt" ]; then
  log "train gen0"
  py -m spire_rl.unified_train --init "$PRETRAIN" --data "$U/teacher" --out "$U/gen0.pt.tmp" --device "$DEVICE" \
     --epochs "$EPOCHS" --batch 256 --macro-runs "$MACRO_RUNS" --root "$ROOT" $HOURS 2>&1 | tee -a "$U/gen0.log"
  mv "$U/gen0.pt.tmp.json" "$U/gen0.pt.json"; mv "$U/gen0.pt.tmp" "$U/gen0.pt"
fi

# 3) paired evaluation on the 188 snapshots: MCTS vs network alone vs network + search (both scales)
log "evaluate gen0"
py -m spire_rl.unified_run eval --evalset "$EVALSET" --out "$U/eval" --net "$U/gen0.pt" --players "$PLAYERS" \
   --tag _gen0 --device "$DEVICE" --cpp-threads "$CORES" $LIMIT 2>&1 | tee -a "$U/eval_gen0.log"

# 4) self-play generations: the previous generation + search plays whole runs; the next one is
#    trained on its data plus the earlier data, starting from the previous weights
prev=gen0
for g in $(seq 1 "$GENS"); do
  log "self-play $g ($SP_MODE) with $prev"
  py -m spire_rl.unified_run gen --macro-ckpt "$MACRO" --out "$U/sp$g" --episodes "$SP_RUNS" --envs $((ENVS * 4)) \
     --budgets "$BUDGETS" --net "$U/$prev.pt" --mode "$SP_MODE" --device "$DEVICE" --cpp-threads "$CORES" \
     --first-seed-default $((7300000 + 100000 * g)) $HOURS 2>&1 | tee -a "$U/sp$g.log"
  if [ ! -e "$U/gen$g.pt" ]; then
    data="$U/teacher"; for k in $(seq 1 "$g"); do data="$data,$U/sp$k"; done
    py -m spire_rl.unified_train --init "$U/$prev.pt" --data "$data" --out "$U/gen$g.pt.tmp" --device "$DEVICE" \
       --epochs 2 --batch 256 --macro-runs "$MACRO_RUNS" --root "$ROOT" $HOURS 2>&1 | tee -a "$U/gen$g.log"
    mv "$U/gen$g.pt.tmp.json" "$U/gen$g.pt.json"; mv "$U/gen$g.pt.tmp" "$U/gen$g.pt"
  fi
  py -m spire_rl.unified_run eval --evalset "$EVALSET" --out "$U/eval" --net "$U/gen$g.pt" --players "$PLAYERS" \
     --tag "_gen$g" --device "$DEVICE" --cpp-threads "$CORES" $LIMIT 2>&1 | tee -a "$U/eval_gen$g.log"
  prev=gen$g
done
log "done"
