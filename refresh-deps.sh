#!/bin/bash
echo "Pull back GH PR changes ..."
git pull
echo "Upgrading uv ..."
uv self update
echo "Upgrading uv deps ..."
uv lock --upgrade
echo "Pre-commit autoupdate ..."
pre-commit autoupdate
