#!/usr/bin/env bash
# Assemble le site de présentation dans _site/ : pages de site/ + captures de docs/images/.
# Utilisé par la GitHub Action (.github/workflows/pages.yml) et pour un aperçu local :
#   bash scripts/build_site.sh && python -m http.server -d _site 8800
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf _site
mkdir -p _site
cp -r site/. _site/
cp -r docs/images _site/images
touch _site/.nojekyll
echo "Site assemblé dans _site/ ($(find _site -type f | wc -l) fichiers)"
