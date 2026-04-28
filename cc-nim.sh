#!/bin/bash

# Default log level
LOG_LEVEL="info"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--debug)
            LOG_LEVEL="debug"
            shift
            ;;
        -v|--verbose)
            LOG_LEVEL="debug"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Set log level and run
export LOG_LEVEL
uv run uvicorn server:app --host 0.0.0.0 --port 3001 --log-level "$LOG_LEVEL"
