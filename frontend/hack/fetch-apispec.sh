#!/bin/bash

set -e

# Get the latest backend API spec and store in src/assests/backend-openapi.json and make it readable
curl -sSfL $NEXT_PUBLIC_AIOPS_BACKEND_URL/openapi.json -o /tmp/backend-openapi.json
cat /tmp/backend-openapi.json | jq . > src/assets/backend-openapi.json
