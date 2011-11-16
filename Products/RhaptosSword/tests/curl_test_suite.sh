#! /bin/bash

# Create a module with a simple atom entry post
./curl_atom_post_create.sh roche brightred ./data/atomentry.xml http://localhost:8080/site

# Add an existing module to an existing lens
curl --request POST --header "Content-Type: application/atom+xml;type=entry" --header "In-Progress: true" --user [username]:[password] --upload-file [path to xml file] http://[Lens URL]/sword

# example
# curl --request POST --header "Content-Type: application/atom+xml;type=entry" --header "In-Progress: true" --user rijk:12345 --upload-file ./entry_add_to_lens.xml http://localhost:8080/site/lenses/rijk/rijk-stofbergs-lens/sword
