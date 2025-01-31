# Reaper

The RSP reaper is designed to help keep image proliferation under
control.

## Motivation

The "official" [sciplat-lab](https://ghcr.io/lsst-sqre/sciplat-lab)
image is built every day, and is (as of late 2023) almost 12GB in size.

When there are hundreds of images, the prepuller has to work much harder
to winnow the list to what it wants to pull and display.  It's also not
very neighborly of the Observatory to soak up terabytes of disk space at
various repository sites with images that no one will ever want to pull
again.

## Policy

Currently the Rubin Observatory guarantees that the last 24 daily
images, the last 52 weekly images, and two years' worth of releases will
be available.  No particular promises are currently made for
experimental images or for release candidate images.

Enforcement of this policy is manual and haphazard (and subject to the
whims of the various repository UIs; in particular, multiple-image
deletion at Docker Hub seems to, well, *not really work*).  Hence this
project, which aims to do the following things:

* Provide a clear, document-driven way to specify how many images of
each type to retain, for how long,
* Remove those images from the repository when their rentention policy
indicates they have expired, and
* Be able to do so for each of the repository types in common use (thus
far, we know of Docker Hub, Google Artifact Registry, Github Container
Registry, and Nexus), which tend to have irritatingly idiosyncratic
methods for removing images from a repository.

## Architecture

### Docker Storage Driver

The reaper will depend on the Docker storage driver from [Nublado
Controller](https://github.com/lsst-sqre/nublado/controller) to list
the repository contents for a given image, and to interpret the tags as
defined in [SQR-059](https://sqr-059.lsst.io/).

A future extension would be to allow it to work for any image style
tagged with [Semantic Versioning Tags](https://semver.org/).

Once development of the delete methods has been done, it is plausible
that the entire container storage driver should be lifted up into
[Safir](https://safir.lsst.io), since there will be two consumers of it.

### Operational Theory

Once a list of all images has been generated, then a document specifying
which tags to keep (by category, number, and age) will be compared
against that list.  Any images found that do not meet the "keep"
criteria will then be purged from the repository.

### How it will be run

We envision that any given reaper will run as a
[Roundtable](https://roundtable.lsst.io/) application, but it will not
need an API route and is not going to be a FastAPI application: instead
it will be a container that is run periodically through a CronJob.  That
is, it won't be triggered by user action, but will simply run at some
fixed frequency.

## Caution

Each repository ought to have at most one reaper specified for it,
globally.  Otherwise, what you're going to get is the results of the
most aggressive one you have defined.

## Nomenclature

Yes, of course the whole thing is going to be stuffed absolutely full of
Blue Öyster Cult jokes.  That might even be a primary motivation for
writing it in the first place.

## PR

This is some text to change so I can do repeated image builds from a PR.
Serial #1.
