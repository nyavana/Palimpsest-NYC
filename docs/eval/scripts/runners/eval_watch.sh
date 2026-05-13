#!/bin/bash
# Fail-loud monitoring tail for the parallel eval. Emits:
#   - every Python exit (crash detection within ~2s, not waiting for a milestone)
#   - every wrapper attempt
#   - every system completion
#   - errors (Traceback, 403, etc)
#   - every 10th question per system (progress visibility)
#
# Use this with the Claude Code Monitor tool, or in a terminal:
#   bash docs/eval/scripts/runners/eval_watch.sh

tail -F \
  /tmp/eval_vanilla.log \
  /tmp/eval_naive_rag.log \
  /tmp/eval_palimpsest-dense.log \
  2>/dev/null \
  | grep --line-buffered -E '(\[(vanilla|naive_rag|palimpsest-dense) (1|10|20|30|40|50|60|70|80|90|95)/95\]|attempt|exit=|complete|resuming|Traceback|Error: |403|all done)'
