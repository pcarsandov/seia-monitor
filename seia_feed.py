name: SEIA daily feed

on:
  schedule:
    - cron: '30 11 * * *'   # 08:30 Chile aprox (UTC-3)
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run scraper
        run: python seia_feed.py

      - name: Publish to gh-pages
        run: |
          set -e
          git fetch origin
          git checkout -B gh-pages

          # Copiar artefactos desde /out a la raíz de gh-pages
          cp -f out/feed.xml feed.xml
          cp -f out/data.json data.json
          if [ -f out/debug_sample.html ]; then cp -f out/debug_sample.html debug_sample.html; fi

          git add feed.xml data.json debug_sample.html 2>/dev/null || true
          git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
            commit -m "Update feed $(date -u +'%Y-%m-%d %H:%M:%S')" || echo "Nothing to commit"

          git push -f origin gh-pages
