#! /bin/bash

curl --request POST --header "Content-Type: application/atom+xml;type=entry" --header "In-Progress: true" --user $1:$2 --upload-file $3 $4/Members/$1/sword
