# CoBuild Demo Test Guide

## Test A — Real evidence
Use a photo taken on your phone of a real civic issue (pothole, garbage, broken streetlight, damaged footpath, etc.).

Expected purpose: establish the normal evidence path and confirm the upload works.

## Test B — AI-generated evidence
Upload `test_assets/AI_generated_pothole_test.png`.

Expected purpose: confirm the Sightengine `genai` integration is reached and returns an AI-generation probability. The exact score can vary; do not require exactly 0 or 1.

## What to show judges
Citizen report → evidence upload → authenticity/provenance signals → admin review → resolution → citizen verification.

Never expose your Sightengine API secret in screenshots, source code, or the final presentation.
