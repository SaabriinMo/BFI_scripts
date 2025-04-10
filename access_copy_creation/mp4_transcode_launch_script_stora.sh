#!/bin/bash -x

# ====================================================================
# STORA TS FILE Launcher script for access copy generation MP4 / JPEG
# ====================================================================

date_FULL=$(date +'%Y-%m-%d - %T')

# Local variables from environmental vars
path="$1"
transcode_path1="${path}${TRANS}"
job_num="$2"
path_insert="${1//['/']/_}"
dump_to="${LOG_PATH}mp4_transcode${path_insert}files.txt"
log_path="${LOG_PATH}mp4_transcode_make_jpeg.log"
python_script="${CODE}access_copy_creation/mp4_transcode_make_jpeg_2.py"

function control {
    boole=$(cat "${CONTROL_JSON}" | grep "power_off_all" | awk -F': ' '{print $2}')
    if [ "$boole" = false, ] ; then
      echo "Control json requests script exit immediately" >> "${LOG}"
      echo 'Control json requests script exit immediately'
      exit 0
    fi
}

# Control check inserted into code
control

# replace list to ensure clean data
echo "" > "${dump_to}"

echo " ========================= SHELL LAUNCH - QNAP04 STORA ========================== $date_FULL" >> "${log_path}"
echo " == Start MP4 transcode/JPEG creation in $transcode_path1 == " >> "${log_path}"
echo " == Shell script creating dump_text.txt output for parallel launch of Python scripts == " >> "${log_path}"

# Command to build file list to supply to Python
for entry in "${transcode_path1}"*; do
  echo -e "${entry}" >> "${dump_to}"
done

echo " == Launching GNU parallel to run muliple Python3 scripts for encoding == " >> "${log_path}"
grep '/mnt/' "${dump_to}" | parallel --jobs "$job_num" --timeout 86400 "$PYENV311 $python_script {}"

echo " ========================= SHELL END - QNAP04 STORA ========================== $date_FULL" >> "${log_path}"
