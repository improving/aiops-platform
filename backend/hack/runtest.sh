#!/bin/bash
echo "Received arguments: $@"

# Run tests
if [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
    echo "Usage: ./hack/runtest.sh [--update-snapshots | -u] [--cleanup | -c]"
    echo -e "\nOptions:\n"
    echo "--update-snapshots: Update the snapshots when tests are run"
    echo -e "--cleanup: Cleanup all existing snapshots\n"
    exit 0
fi 

# If cleanup argument then cleanup all snapshots
if [ "$1" == "--cleanup" ] || [ "$1" == "-c" ]; then
    find . -type d -name "snapshots" -exec rm -r {} +
    exit 0
fi

# IF update snapshot argument is passed, then update the snapshots
if [ "$1" == "--update-snapshots" ] || [ "$1" == "-u" ]; then
    pytest --snapshot-update .
else
    pytest .
fi
