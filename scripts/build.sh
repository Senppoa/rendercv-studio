#!/usr/bin/env bash
# 渲染 examples/ 下所有 YAML 为 PDF（输出到 output/）
set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
mkdir -p "$PROJECT_ROOT/output"
for yaml in examples/*.yaml; do
  name=$(basename "$yaml" .yaml)
  echo "==> Rendering $name"
  rendercv render "$yaml" --output-folder "$PROJECT_ROOT/output/$name" --dont-generate-html --dont-generate-markdown
done
echo "Done. PDFs are in output/"
