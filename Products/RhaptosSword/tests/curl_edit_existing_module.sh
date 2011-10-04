#! /bin/bash

echo 'curl --request PUT --header "Content-Type: application/atom+xml;type=entry" --header "In-Progress: True" --user '$1':'$2' --upload-file '$3' '$4'/Members/'$1'/'$5'/sword'

# Edit existing module with atom entry
curl --request PUT --header "Content-Type: application/atom+xml;type=entry" --header "In-Progress: True" --user $1:$2 --upload-file $3 $4/$1/$5/sword

