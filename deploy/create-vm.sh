#!/usr/bin/env bash
#
# Create the Always-Free-eligible Compute Engine VM for the Bob Harness.
#
# Run from your laptop (with the gcloud CLI installed and authenticated) or from
# Google Cloud Shell. Override any value with an env var, e.g.:
#
#   PROJECT=my-project ZONE=us-central1-a NAME=bob ./deploy/create-vm.sh
#
# Always-Free eligibility (as of 2026): exactly one e2-micro in one of the zones
# us-west1, us-central1 or us-east1, with a <=30 GB standard persistent disk.
set -euo pipefail

PROJECT="${PROJECT:-brun3y-d3d2a}"
ZONE="${ZONE:-us-west1-b}"
NAME="${NAME:-ibm-bob}"

gcloud compute instances create "$NAME" \
  --project="$PROJECT" \
  --zone="$ZONE" \
  --machine-type=e2-micro \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-standard \
  --maintenance-policy=MIGRATE

cat <<EOF

VM "$NAME" created in $ZONE.

Next:
  gcloud compute ssh $NAME --zone $ZONE --project $PROJECT
  git clone https://github.com/BrUn3y/IBM_Bob_Harness.git
  cd IBM_Bob_Harness
  ./deploy/setup-vm.sh
EOF
