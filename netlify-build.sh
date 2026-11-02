#!/bin/sh
set -eu

# Generate a tiny runtime config without committing deployment-specific URLs.
# Netlify exposes CIVICLENS_API_BASE from Site configuration during the build.
api_base="${CIVICLENS_API_BASE:-}"
escaped_base=$(printf '%s' "$api_base" | sed 's/\\/\\\\/g; s/"/\\"/g')
printf 'window.CIVICLENS_API_BASE = "%s";\n' "$escaped_base" > assets/js/deployment-config.js

# The public pages use a smaller standalone client, so inject the same config
# before its script at build time.
for page in public.html incident.html; do
  sed -i 's#<script src="/assets/nagarsetu.js"></script>#<script src="/assets/js/deployment-config.js"></script><script src="/assets/nagarsetu.js"></script>#' "$page"
done
sed -i 's#<script src="../assets/js/api.js"></script>#<script src="../assets/js/deployment-config.js"></script><script src="../assets/js/api.js"></script>#' admin/escalations.html
