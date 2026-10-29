#!/usr/bin/env bash
# ported from din-relay-8ch/tools/pfr2/drive2.sh, 2026-10-27 (SBC-1: reference only - tools/pfr2/drive_sbc.py is the SBC-1 driver)
# Overnight driver (lead 2026-10-05; drive2: + pour_stitch after every stage): ONE stage (<= 25 min, st2-base flags without the consumed PS1 keep-in) -> prune
# (draft_native prune) -> copper_cleanup (tools/copper_cleanup.py; again after pour_stitch) -> dump -> open-join count, repeated from the pruned result; stops after 2 stages without a new
# best (diagnose, fix, restart) or MAX stages. One summary line per stage in $OUT/drive.log.
#   bash drive.sh START_BOARD_DIR START_GEOM TAG MAX
# PFR2_ARGS="..." passes pfr2 flags to every router variant (production 2026-10-05: "--exact-clock --rescue --via-policy --det --tidy")
# BASE_GJ / RIP_OLD / RESERVE override the M1-lineage inputs (M5 clean slate: its own geom as base and rip-island old base,
# reservations re-validated with tools/filter_reservations.py)
set -u
M=${M:?M = this routing task folder, e.g. C:/work/din-relay-8ch/.runtime/tasks/<task>}
K="/c/Program Files/KiCad/10.0/bin/python.exe"
S=/c/work/din-relay-8ch/scripts
DN=C:/work/din-relay-8ch/tools/pfr2/draft_native.py
B=$1; GJ=$2; TAG=$3; MAX=${4:-6}
OUT=$M/drive-$TAG; mkdir -p $OUT
best=$(cd $M && python -c "import sys;sys.path.insert(0,'C:/work/din-relay-8ch/tools/pfr2');import cugraph;from open_joins import open_joins;print(len(open_joins(cugraph.load('$GJ'))))")
echo "start $B open $best $(date +%H:%M)" >> $OUT/drive.log
stall=0
# copper_cleanup.py after prune and after pour_stitch; CLEAN_RESERVE="x0,y0,x1,y1:NET,NET[;...]" leaves another agent's
# copper alone (e.g. the hold-up bank "201,29,238,46:+15V,GND,+V_PULL" while holdup-copper owns it)
clean() {
  local R=(); [ -n "${CLEAN_RESERVE:-}" ] && R=(--reserve "$CLEAN_RESERVE")
  # v2 (cleanup2, 2026-10-05): --scope new = only this stage's own copper (not in the stage input geom $3) is edited
  (cd $S && "$K" local_run.py C:/work/din-relay-8ch/tools/pfr2/copper_cleanup.py $1 $3 $2.json --scope new "${R[@]}" > $2.log 2>&1)
  echo "  copper_cleanup $(basename $2): $(grep -E '^after|^drc before' $2.log | tr '\n' ' ')" >> $OUT/drive.log
}
for i in $(seq 1 $MAX); do
  T=$TAG$i
  (cd $M && python C:/work/din-relay-8ch/tools/pfr2/stage_loop.py $B $GJ $M/M1n-s1.json ${BASE_GJ:-$M/base-M1m.json} $T --stages 1 --variants 2 \
     --rip-island ${RIP_OLD:-$M/geom-start.json} --cage-selv --cage-rails --cage-coil --reserve ${RESERVE:-$M/start/escape-reservations.json} \
     --budget 1100 --variant-timeout 1300 --pfr2-args "${PFR2_ARGS:-}" --out $OUT/st$i > $OUT/st$i.log 2>&1)
  NB=$OUT/st$i/boards/revC-$T-s1
  [ -d $NB ] || { echo "stage $i: no board ($(tail -1 $OUT/st$i.log))" >> $OUT/drive.log; break; }
  P=$OUT/p$i; rm -rf $P; cp -r $NB $P
  (cd $S && "$K" local_run.py $DN prune $P/din8r-main-repaired.kicad_pcb $OUT/p$i-prune.json > $OUT/p$i-prune.log 2>&1)
  rm -f $P/*.prune-geom.json
  # copper cleanup (cruft-fix 2026-10-05): DRC shorts / Y600 rips, dups, orphans, pad-edge vias, smoothing, pad centres,
  # widths, redundant bare vias -> fixpoint, full qa_copper_landing gate + kicad DRC before / after in p$i-clean.json
  clean $P/din8r-main-repaired.kicad_pcb $OUT/p$i-clean $GJ
  (cd $S && "$K" local_run.py C:/work/din-relay-8ch/tools/pfr2/dump_geom.py $P/din8r-main-repaired.kicad_pcb $OUT/p$i.json > /dev/null 2>&1)
  n=$(cd $M && python C:/work/din-relay-8ch/tools/pfr2/compare_joins.py "p$i=$OUT/p$i.json" | sed -n 2p)
  o=$(echo "$n" | awk '{print $2}')
  echo "stage $i $(date +%H:%M): $n | prune $(grep -o '"kicad_unconnected": \[[0-9, ]*\]' $OUT/p$i-prune.log | tail -1)" >> $OUT/drive.log
  if [ "$o" -lt "$best" ]; then best=$o; stall=0; echo "best $P $o" >> $OUT/drive.log; bestB=$P; bestG=$OUT/p$i.json; else stall=$((stall+1)); fi
  # pour stitching between stages (owner doctrine (d)): GND fragments cut off from In1 get a via
  (cd $M && python C:/work/din-relay-8ch/tools/pfr2/pour_stitch.py $OUT/p$i.json $OUT/p$i-stitch.json > $OUT/p$i-stitch.log 2>&1)
  if [ "$(python -c "import json;d=json.load(open('$OUT/p$i-stitch.json'));print(len(d['add']['vias'])+len(d['delete']))")" -gt 0 ]; then
    (cd $M && python C:/work/din-relay-8ch/tools/pfr2/delta_merge.py $P $OUT/p$i.json ${BASE_GJ:-$M/base-M1m.json} $OUT/p$i-stitch.json $OUT/q$i $OUT/q$i.json --neck-from $M/M1n-s1.json > $OUT/q$i.log 2>&1) && { P=$OUT/q$i; echo "  pour_stitch: $(head -1 $OUT/p$i-stitch.log)" >> $OUT/drive.log;
      clean $P/din8r-main-repaired.kicad_pcb $OUT/q$i-clean $GJ
      (cd $S && "$K" local_run.py C:/work/din-relay-8ch/tools/pfr2/dump_geom.py $P/din8r-main-repaired.kicad_pcb $OUT/q$i.json > /dev/null 2>&1); }
    [ "$P" = "$OUT/q$i" ] && GJN=$OUT/q$i.json || GJN=$OUT/p$i.json
  else GJN=$OUT/p$i.json; fi
  B=$P; GJ=$GJN
  if [ "$o" -ge "$best" ] && [ -n "${bestB:-}" ]; then B=$bestB; GJ=$bestG; fi     # a worse stage: continue from the best
  [ $stall -ge 2 ] && { echo "plateau after stage $i (best $best)" >> $OUT/drive.log; break; }
done
echo "DONE" >> $OUT/drive.log
