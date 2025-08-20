#!/usr/bin/env bash
# exit on error
set -e

pip install -r requirements.txt
python -m spacy download en_core_web_md
