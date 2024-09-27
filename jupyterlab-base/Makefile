# We need three pieces of information to build the container:
#  tag is the tag on the input DM Stack container.  It is mandatory.
#  image is the Docker repository image we're pushing to; we can use the
#   default if we don't specify it, which goes to Docker Hub.  image
#   may be a comma-separated list of target repositories.
#  supplementary is an additional tag, which forces the build to an "exp_"
#   (that is, experimental) tag and adds "_" plus the supplement at the end.

# Therefore: the typical use of the Makefile would look like:
#   make tag=w_2021_50

# To push to a different repository:
#   make tag=w_2021_50 image=ghcr.io/lsst-sqre/sciplat-lab

# To use a different input image:
#   make tag=w_2021_49_c0023.008 \
#    input=ts-dockerhub.lsst.org/lsstts/sal-sciplat: \
#    image=ts-dockerhub.lsst.org/lsstts/sal-sciplat-lab

# To tag as experimental "foo" (-> exp_w_2021_50_foo):
#   make tag=w_2021_50 supplementary=foo

# There are five targets: clean, dockerfile, image, push, and retag.

# The default is "push", and the first four are always done in strict linear
#  order.
# "clean" just removes the generated Dockerfile.
# "dockerfile" generates the Dockerfile from the template, but does not build
#  an image or push it.
# "image" builds the image with Docker but does not push it to a repository.
# "push" (aka "all") also pushes the built image.  It assumes that the
#  building user already has appropriate push credentials set.

# The fifth target, "retag", is a little different.  Its tag is the tag on
#  the input image, but "input" will, itself, be a sciplat-lab container.
#  "supplementary" will be the tag to add to this image; no substitution will
#  be done on either the input tag or the supplementary tag.  As with "push"
#  it assumes that the building user has appropriate push credentials set.
# There is no point in retagging without pushing, so "push" is always implicit
#  in retag.

ifeq ($(tag),)
    $(error tag must be set)
endif

# By default, we will push to Docker Hub, Google Artifact Registry,
# and GitHub Container Registry.  We expect to eventually drop Docker Hub.

ifeq ($(image),)
    image = docker.io/lsstsqre/sciplat-lab,us-central1-docker.pkg.dev/rubin-shared-services-71ec/sciplat/sciplat-lab,ghcr.io/lsst-sqre/sciplat-lab
endif

ifeq ($(input),)
    input = docker.io/library/python:3.12-slim
    # For one of the four build targets, you need to include the colon here,
    # and the input tag has to end with $(tag).  For "retag" it's different
    # and is explained below.
endif

# Some day we might use a different build tool.  If you have a new enough
#  docker, you probably want to set DOCKER_BUILDKIT in your environment.
#  ... except that as of August 6, 2023, the new builder (which you get with
#  DOCKER_BUILDKIT=1, or by default as of that date) just hangs at the
#  image-writing stage on GitHub Actions.  So we're going to work around it,
#  at least until legacy build support is removed.
DOCKER := docker

# Force to simply-expanded variables, for when we add the supplementary tag.
tag := $(tag)
image := $(image)
#  version is the tag on the output JupyterLab container.  Releases
#   change the first letter of the tag from "v" to "r", and if a supplementary
#   version is added, the tag will be marked as "exp_" with the supplement
#   added at the end after an underscore.
version := $(tag)
version := $(version:v%=r%)

release_branch := main
branch := $(shell git rev-parse --abbrev-ref HEAD)

# if we are not on the release branch, then force supplementary to be set
ifneq ($(branch),$(release_branch))
    ifeq ($(supplementary),)
        supplementary := $(shell echo $(branch) | tr -c -d \[A-z\]\[0-9\])
    endif
endif
ifneq ($(supplementary),)
    version := exp_$(version)_$(supplementary)
endif

# Experimentals do not get tagged as latest anything.  Dailies, weeklies, and
#  releases get tagged as latest_<category>.  The "latest" tag for the lab
#  container should always point to the latest weekly or release, but not a
#  daily, since we make no guarantees that the daily is fit for purpose.

tag_type = $(shell echo $(version) | cut -c 1)
ifeq ($(tag_type),w)
    ltype := latest_weekly
    latest := latest
else ifeq ($(tag_type),r)
    # if it's got an "rc" in the name, it's a release candidate, and we don't
    #  want to tag it as latest anything either.
    ifeq ($(findstring rc, $(version)),)
       ltype := latest_release
       latest := latest
    endif
else ifeq ($(tag_type),d)
    ltype := latest_daily
endif

# There are no targets in the classic sense, and there is a strict linear
#  dependency from building the dockerfile to the image to pushing it.

# Retagging is a separate action.

# "all" and "build" are just aliases for "push" and "image" respectively.

.PHONY: all push build image dockerfile clean retag

all: push

# push assumes that the building user already has docker credentials
#  to push to whatever the target repository or repositories (specified in
#  $(image), possibly as a comma-separated list of targets) may be.
push: image
	img=$$(echo $(image) | cut -d ',' -f 1) && \
	more=$$(echo $(image) | cut -d ',' -f 2- | tr ',' ' ') && \
	$(DOCKER) push $${img}:$(version) && \
	for m in $${more}; do \
	    $(DOCKER) tag $${img}:$(version) $${m}:$(version) ; \
	    $(DOCKER) push $${m}:$(version) ; \
	done && \
	if [ -n "$(ltype)" ]; then \
	    $(DOCKER) tag $${img}:$(version) $${img}:$(ltype) ; \
	    $(DOCKER) push $${img}:$(ltype) ; \
	    for m in $${more}; do \
	        $(DOCKER) tag $${img}:$(ltype) $${m}:$(ltype) ; \
	        $(DOCKER) push $${m}:$(ltype) ; \
	    done ; \
	fi && \
	if [ -n "$(latest)" ]; then \
	    $(DOCKER) tag $${img}:$(version) $${img}:$(latest) ; \
	    $(DOCKER) push $${img}:$(latest) ; \
	    for m in $${more}; do \
	        $(DOCKER) tag $${img}:$(latest) $${m}:$(latest) ; \
	        $(DOCKER) push $${m}:$(latest) ; \
	    done ; \
	fi

# I keep getting this wrong, so make it work either way.
build: image

image: dockerfile
	img=$$(echo $(image) | cut -d ',' -f 1) && \
	more=$$(echo $(image) | cut -d ',' -f 2- | tr ',' ' ') && \
	$(DOCKER) build ${platform} -t $${img}:$(version) . && \
	for m in $${more}; do \
	    $(DOCKER) tag $${img}:$(version) $${m}:$(version) ; \
	done

dockerfile: clean
	img=$$(echo $(image) | cut -d ',' -f 1) && \
	sed -e "s|{{IMAGE}}|$${img}|g" \
	    -e "s|{{VERSION}}|$(version)|g" \
	    -e "s|{{INPUT}}|$(input)|g" \
	    -e "s|{{TAG}}|$(tag)|g" \
	    < Dockerfile.template > Dockerfile

clean:
	rm -f Dockerfile

# If input is the default, repoint it at the Docker Hub sciplat-lab image.
# Someday this will likely be ghcr.io.
retag:
	inp="$(input)" && \
	if [ "$${inp}" = "docker.io/lsstsqre/centos:7-stack-lsst_distrib-" ] ; then \
	    inp="docker.io/lsstsqre/sciplat-lab" ; \
	fi && \
	$(DOCKER) pull $${inp}:$(tag) && \
	if [ -z "$(supplementary)" ]; then \
	    echo "supplementary parameter must be set for retag!" ; \
	    exit 1 ; \
	else \
	    outputs=$$(echo $(image) | cut -d ',' -f 1- | tr ',' ' ') && \
	    for o in $${outputs}; do \
	        $(DOCKER) tag $${inp}:$(tag) $${o}:$${supplementary} ; \
	        $(DOCKER) push $${o}:$${supplementary} ; \
	    done ; \
	fi
