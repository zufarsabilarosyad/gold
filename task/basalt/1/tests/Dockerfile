# Verifier image: the pinned task image with the held-back tests baked in.
# tests/ is the build context; the agent never sees this container.
FROM us-docker.pkg.dev/afterquery-compute/compute-images/gold-repo-basalt-dnzdhf:v2

# Build the verifier as root. The environment image is the expert's own and may
# end on a non-root USER (nothing forbids it, and node/python images commonly
# ship one), which this stage would otherwise inherit — every package-manager
# install below would fail, and so would the chmod, which is why this applies
# to the pre-existing steps too, not just the install.
#
# Not restored afterwards: a Dockerfile cannot read the inherited USER, so
# there is nothing to restore it to, and guessing would be worse. Root is also
# the right posture here — the verifier is a separate container the agent never
# sees, and it has to apply the held-back test patch and write /logs.
USER root

# The grader is Python (tests/grader.py, invoked by tests/test.sh), but the
# base image is the expert's own environment — chosen for THEIR project, and
# for a TypeScript/Go/Rust repo it has no interpreter. Requiring one of them
# would be requiring a dependency for our tooling that has nothing to do with
# their task, and it is not something we ask for anywhere. So the verifier
# image installs it. This layer is never in the agent's container: the agent
# runs the environment image, and only the verifier is built from this file.
RUN command -v python3 >/dev/null 2>&1 ||     { { apt-get update && apt-get install -y --no-install-recommends python3         && rm -rf /var/lib/apt/lists/*; }       || apk add --no-cache python3       || microdnf -y install python3 || dnf -y install python3 || yum -y install python3       || { echo "PLATFORM ERROR: no python3 and no apt-get/apk/dnf/yum to install it. The grader cannot run in this image."; exit 1; }; }

COPY test.sh /tests/test.sh
COPY test.patch /tests/test.patch
COPY grader.py /tests/grader.py
COPY config.json /tests/config.json
RUN chmod +x /tests/test.sh
