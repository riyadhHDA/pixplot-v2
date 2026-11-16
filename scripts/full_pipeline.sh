#!/usr/bin/env bash
# Enchaîne tout le pipeline PixPlot v2 sur un corpus Hugging Face au format Parquet,
# avec un chronométrage par étape (journal : <données>/pipeline.log).
#
# Usage (depuis la racine du projet) :
#   bash scripts/full_pipeline.sh data/wikiart81k
# Le dossier doit contenir corpus/raw/*.parquet et corpus/labels.json.
# Chaque étape peut être relancée : ingestion et extraction des vecteurs reprennent
# là où elles s'étaient arrêtées.
set -euo pipefail

DATA="${1:?dossier de données, ex. data/wikiart81k}"
PY=".venv/Scripts/python"
PIX=".venv/Scripts/pixplot"
LOG="$DATA/pipeline.log"
mkdir -p "$DATA"

step() {
  local name="$1"; shift
  echo "=== $(date '+%H:%M:%S') $name" | tee -a "$LOG"
  local t0=$(date +%s)
  "$@" 2>&1 | grep -v -E "it/s\]|img/s\]|MIOpen|Loading weights|^\s*$" | tee -a "$LOG"
  local t=$(( $(date +%s) - t0 ))
  echo "--- $name : $((t / 60)) min $((t % 60)) s" | tee -a "$LOG"
}

if [ ! -f "$DATA/corpus/metadata.csv" ]; then
  step "extraction des images" $PY -X utf8 scripts/extract_hf_parquet.py "$DATA/corpus/raw" "$DATA/corpus"
fi
step "ingestion"            $PIX --data "$DATA" ingest "$DATA/corpus/images"
step "métadonnées"          $PIX --data "$DATA" import-metadata "$DATA/corpus/metadata.csv" --source "huggan/wikiart (Hugging Face)"
step "DINOv3 B/16 @448"     $PIX --data "$DATA" embed --encoder dinov3_vitb16 --batch-size 32
step "SigLIP 2 So400m"      $PIX --data "$DATA" embed --encoder siglip2_so400m --batch-size 32
step "index DINOv3"         $PIX --data "$DATA" index --encoder dinov3_vitb16
step "index SigLIP 2"       $PIX --data "$DATA" index --encoder siglip2_so400m
step "index des zones"      $PIX --data "$DATA" index --regions --encoder dinov3_vitb16
step "analyse (groupes, carte, HDBSCAN, planches)" $PIX --data "$DATA" analyze --encoder dinov3_vitb16 --hdbscan --show 30
step "audit à l'aveugle"    $PIX --data "$DATA" audit
step "banc d'essai"         $PIX --data "$DATA" bench
step "état final"           $PIX --data "$DATA" status
echo "=== terminé $(date '+%H:%M:%S')" | tee -a "$LOG"
