#!/usr/bin/env bash
# Downloads the public Olist Brazilian e-commerce CSVs (CC BY-NC-SA 4.0) into data/.
set -euo pipefail
mkdir -p data && cd data
base=https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets
for f in orders order_items customers products order_payments order_reviews sellers; do
  curl -sSL -O "$base/olist_${f}_dataset.csv"
done
curl -sSL -O "$base/product_category_name_translation.csv"
