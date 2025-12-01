#!/bin/bash
# handler.sh

# Read request line
read REQUEST
METHOD=$(echo "$REQUEST" | cut -d" " -f1)
PATH=$(echo "$REQUEST" | cut -d" " -f2)

# Read headers and capture Content-Length
CONTENT_LENGTH=0
while read line; do
  [ "$line" = $'\r' ] && break
  if [[ "$line" =~ ^Content-Length:\ ([0-9]+) ]]; then
    CONTENT_LENGTH=${BASH_REMATCH[1]}
  fi
done

# Exit early if Content-Length too small (for POST)
if [ "$CONTENT_LENGTH" -lt 10 ] && [ "$METHOD" = "POST" ]; then
  BODY="Body too small (<10)"
  LEN=${#BODY}
  printf "HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nContent-Length: $LEN\r\n"
  printf "\r\n"
  echo "$BODY"
  exit 0
fi

if [ "$METHOD" = "GET" ]; then
  if [ -f "./tx.json" ]; then
    FILESIZE=$(/usr/bin/stat -c%s "./tx.json")
    printf "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: $FILESIZE\r\n"
    printf "\r\n"
    /usr/bin/cat "./tx.json"
  else
    BODY="File not found"
    LEN=${#BODY}
    printf "HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nContent-Length: $LEN\r\n"
    printf "\r\n"
    echo "$BODY"
  fi

elif [ "$METHOD" = "POST" ]; then
  BODY=$(dd bs=1 count=$CONTENT_LENGTH 2>/dev/null)   # read POST body from stdin
  echo "$BODY" >> /tmp/received.json

  RESP='{"status":"saved","file":"/tmp/received.json"}'
  LEN=${#RESP}
  printf "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: $LEN\r\n"
  printf "\r\n"
  echo "$RESP"

else
  BODY="Method not allowed"
  LEN=${#BODY}
  printf "HTTP/1.1 405 Method Not Allowed\r\nContent-Type: text/plain\r\nContent-Length: $LEN\r\n"
  printf "\r\n"
  echo "$BODY"
fi

