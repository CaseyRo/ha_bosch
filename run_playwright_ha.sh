#!/bin/bash
# Capture the OAuth callback URL for pasting into Home Assistant.
# Does NOT consume the code — safe to paste into HA afterwards.
set -e
cd "$(dirname "$0")"
op run --env-file=.env -- uv run --with playwright --with playwright-stealth --with aiohttp python test_pointtapi_playwright.py --ha
