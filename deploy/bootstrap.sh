#!/bin/bash
set -euo pipefail
shopt -s nullglob
interpreters=(/var/app/venv/staging-*/bin/python /var/app/venv/*/bin/python)
for interpreter in "${interpreters[@]}"; do
  if "$interpreter" -c 'import boto3' >/dev/null 2>&1; then
    "$interpreter" deploy/bootstrap.py
    exit 0
  fi
done
echo 'Beanstalk Python environment with boto3 was not found.' >&2
exit 1
