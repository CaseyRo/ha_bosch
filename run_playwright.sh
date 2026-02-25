#!/bin/bash
set -e
cd "$(dirname "$0")"
op run --env-file=.env -- uv run --with playwright --with playwright-stealth --with aiohttp python test_pointtapi_playwright.py
