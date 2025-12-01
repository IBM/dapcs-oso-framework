#!/bin/bash

PORT=8000
TX_FILE="./tx.json"             # File to serve on GET
SAVE_FILE="/tmp/received.json"  # File to save POST body

# Start socat and run handler.sh for each connection
socat TCP-LISTEN:$PORT,reuseaddr,fork EXEC:./handler.sh

