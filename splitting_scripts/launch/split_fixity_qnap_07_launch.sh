#!/bin/bash

# Launcher for split.py script which models carriers
# for in-scope whole-tape digitisation files and then
# creates item-level files and documents them in CID

TARGET="${QNAP_VID}/processing/source/7"
LOG="${QNAP_VID}/processing/log/split_7.log"
SCRIPT="${CODE}splitting_scripts/split_fixity.py"

# Log script start
echo "" >> "$LOG"
echo "Start Python 3 split_fixity.py: $(date)" >> "$LOG"

# Perform splitting twice: once-through for single-item
# carriers and then once-through for multi-item tapes
"$PY3_ENV" "$SCRIPT" "${TARGET}"
"$PY3_ENV" "$SCRIPT" "${TARGET}" multi

# Log script end
echo "Finish split_fixity.py: $(date)" >> "$LOG"