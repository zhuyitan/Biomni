#!/usr/bin/env bash
# Download open-access data for every TCGA project, excluding the two
# "elephant" modalities (Slide Image, Masked Intensities) that dominate
# disk usage. Per-project work is sequential; one project failing does NOT
# stop the loop.
#
# Per project the agent will:
#   1. enumerate every open-access modality (15-20 min first time, cached after)
#   2. download every file of each non-excluded modality (TCGA_MAX_FILES=0)
#   3. write schema_summary.md, file_manifest.tsv, patient_files.tsv,
#      and size_summary.md into have/data/tcga/data/<PROJECT>/
#
# Resume safe: GDCdownload skips files already on disk, and the modality
# cache makes re-listing instant. Re-running this script after an interrupt
# just picks up where it left off.
#
# Usage:
#   bash have/data/tcga/scripts/download_all_tcga.sh                  # default: all 33 projects
#   bash have/data/tcga/scripts/download_all_tcga.sh TCGA-BRCA TCGA-OV  # subset
#   TCGA_EXCLUDE_DATA_TYPES="Slide Image" bash have/data/tcga/scripts/download_all_tcga.sh
#                                                   # override exclusions

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Default exclusions for this bulk run — Slide Image is ~800 GB/cancer,
# Masked Intensities (IDAT) ~14 GB/cancer. Both still discoverable later
# by setting TCGA_EXCLUDE_DATA_TYPES="" or naming them in TCGA_PROJECT runs.
: "${TCGA_EXCLUDE_DATA_TYPES:=Slide Image,Masked Intensities}"
# Download every file in every (non-excluded) modality.
: "${TCGA_MAX_FILES:=0}"
export TCGA_EXCLUDE_DATA_TYPES TCGA_MAX_FILES

# All 33 TCGA projects (curated; stable list).
ALL_PROJECTS=(
  TCGA-ACC  TCGA-BLCA TCGA-BRCA TCGA-CESC TCGA-CHOL TCGA-COAD TCGA-DLBC
  TCGA-ESCA TCGA-GBM  TCGA-HNSC TCGA-KICH TCGA-KIRC TCGA-KIRP TCGA-LAML
  TCGA-LGG  TCGA-LIHC TCGA-LUAD TCGA-LUSC TCGA-MESO TCGA-OV   TCGA-PAAD
  TCGA-PCPG TCGA-PRAD TCGA-READ TCGA-SARC TCGA-SKCM TCGA-STAD TCGA-TGCT
  TCGA-THCA TCGA-THYM TCGA-UCEC TCGA-UCS  TCGA-UVM
)

if [[ $# -gt 0 ]]; then
  PROJECTS=("$@")
else
  PROJECTS=("${ALL_PROJECTS[@]}")
fi

echo "=================================================================="
echo "TCGA bulk downloader"
echo "  projects        : ${#PROJECTS[@]} (${PROJECTS[*]})"
echo "  exclude types   : $TCGA_EXCLUDE_DATA_TYPES"
echo "  max files/mod   : $TCGA_MAX_FILES (0 = unlimited)"
echo "  log dir         : $LOG_DIR"
echo "  output root     : $(cd "$SCRIPT_DIR/.." && pwd)/data"
echo "=================================================================="

declare -a OK FAIL
START_ALL=$(date +%s)

for project in "${PROJECTS[@]}"; do
  log_file="$LOG_DIR/${project}.log"
  echo ""
  echo "----- $project ----- (log: $log_file)"
  start=$(date +%s)
  TCGA_PROJECT="$project" \
    conda run -n biomni_e1 --no-capture-output \
    python -u "$SCRIPT_DIR/tcga_extractor_agent.py" \
    > "$log_file" 2>&1
  rc=$?
  elapsed=$(( $(date +%s) - start ))
  if [[ $rc -eq 0 ]]; then
    OK+=("$project")
    echo "  OK    ($(printf '%dm %02ds' $((elapsed/60)) $((elapsed%60))))"
  else
    FAIL+=("$project (rc=$rc)")
    echo "  FAIL  rc=$rc, see $log_file"
  fi
done

total_elapsed=$(( $(date +%s) - START_ALL ))
echo ""
echo "=================================================================="
echo "Done in $(printf '%dh %02dm' $((total_elapsed/3600)) $(((total_elapsed%3600)/60)))"
echo "  OK   (${#OK[@]}): ${OK[*]:-none}"
echo "  FAIL (${#FAIL[@]}): ${FAIL[*]:-none}"
echo "=================================================================="

# Exit non-zero if anything failed, so callers (CI, cron) notice.
[[ ${#FAIL[@]} -eq 0 ]]
