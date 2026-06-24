#################################
Modifying RSP JupyterLab behavior
#################################

At some point you may want to change the way the user's RSP JupyterLab environment behaves.
At present (June 2026) there are two repositories that you are likely to want to modify.

The process of modification is somewhat tricky, the process of testing your modifications is worse, and orchestrating everything so that your code makes it into the next nightly build is even worse than that.

This is how you do it.

We assume you are making these changes to, ultimately, affect the
behavior of `the DM-stack-containing Lab image <https://github.com/lsst-sqre/sciplat-lab>`_.  If you've got some other payload (e.g. T&S RSP images, or SPHEREx), you will have to adapt the instructions below, but the basic principles will remain the same.

Identify what needs changing
============================

If you are modifying the machinery that sets up the user environment before launching a Lab, you are likely to need to change `lsst-rsp <https://github.com/lsst-sqre/lsst-rsp>`_.
This repository is something of a grab-bag, containing both user-facing tools (e.g. convenience classes for TAP authentication and a Python logging formatter) and the machinery for starting the user's lab container.
If, on the other hand, you want to modify how the lab behaves while it is constructing the UI or while the user is using it, you will need to be working in `rsp-jupyter-extensions <https://github.com/lsst-sqre/rsp-jupyter-extensions>`_.
It is possible you will need to modify both to get the effect you want.
We will cover each of these cases separately.

lsst-rsp
========

The ``lsst-rsp`` package is a standard SQuaRE Python package.
It has a ``make init`` target to set up the development environment and the usual ``typing``, ``lint``, and ``py`` tox environments for typing, linting, and testing the package.

Your work will very likely fall into the ``lsst.rsp.startup`` package namespace.
It will probably be a service (possibly with some attached models).
The codebase, unsurprisingly, will be found in the ``src/lsst/rsp/startup/services`` directory with any models in ``src/lsst/rsp/startup/models``.

Development is straightforward if you're familiar with SQuaRE development patterns.
It is testing a new ``lsst-rsp`` package that is tricky, and that will be addressed below.

rsp-jupyter-extensions
======================

If you are a SQuaRE developer, ``rsp-jupyter-extensions`` will look much less familiar than ``lsst-rsp``.

There is `a guide to help you develop the new functionality <https://github.com/lsst-sqre/rsp-jupyter-extensions/blob/main/README.md>`_.

Testing
========

Obviously you should do what you can with unit tests in the codebase.
However, particularly for user-interacting UI work, you will definitely want to build experimental containers with your codebase.

You will begin by making a branch of `sciplat-lab <https://github.com/lsst-sqre/sciplat-lab>`_.
On this branch, go into the ``scripts`` directory.

Where to install?
-----------------

The question of whether your changes need to be in the UI Python environment, or the DM Stack Python environment, or both, is tricky and you will need to think about it.
If your extension is purely about controlling the Lab's behavior, and doesn't need to refer to anything inside a running notebook (which is usually the case) then it only needs to run in the UI environment.  If it presents Python functionality to the user or relies on data coming from inside the DM stack, it will need to run in the payload environment.

To install a package into the UI environment, you will need to add it to pyproject.toml.
The process is not particularly well-documented.
Assuming that you need to update ``rsp-jupyter-extensions`` to run from a branch (probably the most common task), you will need to tell the jupyterlab-base ``pyproject.toml`` to fetch the package from GitHub, and which branch to use.

After the ``lab`` dependency group, add (customized for your own repository and branch):

..code-block:: toml

    [tool.uv.sources]
    rsp-jupyter-extensions = { git = "https://github.com/lsst-sqre/rsp-jupyter-extensions", branch = "tickets/DM-55155" }

Once you've done that, run ``make update-deps`` from the top-level directory to regenerate all dependencies, or ``uv lock --upgrade-package rsp-jupyter-extensions`` (with your own package name) to regenerate just the upgraded dependency.

Commit the updated ``uv.lock`` and the updated ``pyproject.toml``.

Open a PR against your branch; a ``jupyterlab-base`` image will be generated, with a tag that is your branch name with slashes transformed to hyphens (e.g. branch ``tickets/DM-55155`` becomes Docker tag ``tickets-DM-55155``).
Mark this PR as a draft; you will never merge it, but you do want to generate the alternative base container.

If your changes need to be visible from inside the payload Python (in our case, the DM stack), you will also need to add those packages inside the ``uv pip install`` a few lines above (where ``jupyter_firefly_extensions`` is installed).
Try to maintain the ``--no-build-isolation`` flag if you do this here, because otherwise you risk wildly changing the stack environment and your tests may not be representative of what a production container would look like.
This should look something like::

  uv pip install --no-build-isolation \
      'lsst-rsp>=0.7.1' \
      structlog \
      'symbolicmode<3' \
      'jupyter_firefly_extensions>=0.15.0' \
      'git+https://github.com/lsst-sqre/rsp-jupyter-extensions@tickets/DM-49959'


Building a new experimental image
---------------------------------

Now that a temporary branch exists, go to the `Actions page for sciplat-lab <https://github.com/lsst-sqre/sciplat-lab/actions>`_.
Select the "Manually triggered build of sciplat-lab container" action.
Press the "Run workflow" button.
In the drop-down form that appears:

#. Choose the branch of sciplat-lab you created.
#. Pick a stack version to test against; I habitually choose the latest weekly (e.g. ``w_2025_21``).
#. Add a supplementary tag briefly describing what your changes do, like ``landingpage``.
#. Edit the URI.
   You're probably going to test at IDF, so remove the GHCR and Docker Hub URIs from the comma-separated list.
#. There's no point in pushing an experimental to docker.io, and if you're only testing at IDF, you should also remove ghcr.io from the push targets.
#. You should leave ``push`` enabled, because you won't be able to test your changes otherwise (unless you go to a lot of trouble to fake an RSP on your local machine, which we do not recommend).
#. If you built an updated ``jupyterlab-base`` container (above), put the tag name in place of ``latest`` in the input image name in the last field.

Note that if your only changes are in the ``jupyterlab-base`` layer, you can simply build against the ``main`` branch of sciplat-lab.

If you run from ``main`` and do not add a supplementary tag, you will get an experimental tag that corresponds to the input image tag.
(If you are building a release version, it will have a unique build number, so there is no danger of overwriting a published container, and you will not get this tag.)

Press the green "Run workflow" button at the bottom.
It will take a little more than twenty minutes to run; the part you're interested in typically happens about twelve minutes in.
If the build failed, figure out why and correct it.
This is often as simple as having the branch name wrong in the ``uv pip install`` part, but you may get into dependency hell and have to explicitly specify additional packages.

Testing the container
---------------------

After the build completes, wait five minutes to ensure that the prepuller has run and noticed that there is either a new tag, or a changed SHA checksum on an existing tag.

Go to one of the IDF environments (it doesn't matter which), select "Select uncached image" from the image menu, scroll down to near the bottom, and select the Experimental image you just created.
You probably also want to click "Enable debug logs" on the right-hand pane.

Start the image.
If you have UI changes, now would be a good time to open up the Web Developer Tools in the browser and start paying attention to the console messages.
You may also want to watch the logs of your spawning pod, either via kubectl or in ArgoCD.

Then begins the tedious cycle of seeing where your extension failed, making changes to it, rebuilding the experimental image, and relaunching it.
Eventually, however, you will have correct functionality.
You're not done yet: now it's time to get that image into a future release.

Release your changes
====================

Discard the ``sciplat-lab`` branch you made.
Unless you actually needed to change the build process (for example, adding new files to ``/etc/skel``), you are only changing input packages, not the container-building mechanics.

For the packages you worked on, PR your changes to ``main``, get them reviewed, and merge them.

Go to the GitHub page for the repo (or repos) you changed.
Go through the normal SQuaRE release process (don't forget that if you're working with ``rsp-jupyter-extensions`` you have to change the version in ``package.json`` by hand: it doesn't use the cool ``scm_setuptools`` integration that our standard Python packages do).

Now the package will be on PyPi.
If you only updated ``rsp-jupyter-extensions`` you're done: the package will appear in the next night's build.  However, if you updated ``lsst-rsp`` life becomes more complicated.

Updating ``lsst-rsp``
---------------------

Now you need to go to the `Nublado <https://github.com/lsst-sqre/nublado>`_ repository to rebuild the ``nublado-jupyterlab-base`` container.
In ``jupyterlab-base/scripts/install-jupyterlab``, increase the serial number at the bottom.
Commit this change and open a PR.
This will build a base container with a tag based on your branch name (which will likely be tickets-DM-number).

If you're paranoid (and you should be) you should now build a new sciplat-lab image from its ``Actions`` tab, this time using ``main`` as the branch, using the same supplementary tag, but changing the input image at the very bottom to use ``nublado-jupyterlab-base`` with the tag that just got built from the ticket branch.
Build this, wait for it to complete and then give it five more minutes, and then start a container from the image you just built.

Make sure it runs and that it's got your new functionality in it.

When all is well, merge that Nublado PR.

Releasing a new Nublado
-----------------------

Prepare and release a new Nublado release.
Version numbers, thankfully, are basically free.

This will upload the newly-release-tagged Lab base container, and at the next nightly build, the base JupyterLab container used by builds will have the updated lsst-rsp code.
All containers built using the base as an input, therefore, will too.
