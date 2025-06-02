#################################
Modifying RSP JupyterLab behavior
#################################

At some point you may want to change the way the user's RSP JupyterLab environment behaves.
At present (June 2025) there are two repositories that you are likely to want to modify.

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

If you need to change the ``rsp-jupyter-extensions`` package, you will need to know that it is a `prebuilt extension <https://jupyterlab.readthedocs.io/en/stable/extension/extension_dev.html#prebuilt-extensions>`_ created from the `JupyterLab extension copier template <https://github.com/jupyterlab/extension-template>`_.
To this copier template we have added GitHub Actions to rebuild containers and client libraries and push them to their respective locations in artifact registries and PyPi.
We have also added a ``Makefile`` and modified ``pyproject.toml`` in order to make it behave more like a standard SQuaRE repository in some ways.

Developing new extension functionality
--------------------------------------

The way our extensions work is that they contain both a backend server component (written in Python, acessible under the ``/rubin`` endpoint within the lab) and a frontend UI component, written in TypeScript.
A request from the user's browser (either via an action taken by a user, or something done on UI load at startup) will go to the backend server, and receive a reply which will guide the UI's action.

The "prebuilt" part
^^^^^^^^^^^^^^^^^^^

The "prebuilt" part of "prebuilt extension" means both that there is no need to install nodejs in the Lab container and that the only thing that needs doing to activate the extension is to ``pip install`` it.
The build process within ``rsp-jupyter-extensions`` will generate and pack the extension JavaScript.

Versioning the extension
^^^^^^^^^^^^^^^^^^^^^^^^
One not-at-all-obvious corollary of using the ``copier`` template to generate the extension framework is that we do not use the standard SQuaRE release process to create a new version tag.
Instead the new version must be specified in ``package.json`` in the extension root directory.

Using the Makefile
^^^^^^^^^^^^^^^^^^
We use ``make`` to initialize the development environment with ``make init``.

``make typing`` typechecks both the TypeScript UI components and the Python server components.
As a side effect (!!) it also builds the packed Javascript that is included with the package.

``make lint`` lints both the TypeScript and the Python components.

``make test`` runs the test suite for the Python back-end server.  There are not currently effective tests for the TypeScript components, only a basic smoke test to ensure that it loads into JupyterLab without throwing an exception.

Developing the server backend
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The server backend behaves much like a standard SQuaRE service.
It is written in typed Python and follows the usual SQuaRE guidelines with respect to linting and typing.
It is found in the ``rsp_jupyter_extensions`` directory.

Write the service
"""""""""""""""""

Write your service; it almost certainly belongs in the ``handlers`` subdirectory.
The handler should probably derive from the ``APIHandler`` superclass; look at another handler for the pattern.
The ``APIHandler`` will return JSON to the caller, which is trivially parsed by the UI ``APIRequest()`` function.

If you end up requiring models of any real complexity for the extension, put them in the ``models`` directory and use Pydantic to represent them.
In theory we should derive the models for both the UI side and the server side using Swagger or something similar, but in practice that seems like a lot of work for what are pretty trivial bits of code, and keeping them in sync manually is not hard.

One thing that is not obvious about backend services is that you get a brand new object on each HTTP request to the backend.
If you need to maintain state between requests, you cannot do it in-process.
For servers that need to cache state, I have been using the filesystem to do this, in the user's ``$HOME/.cache`` directory.

Add the route
"""""""""""""

In the top-level ``__init__.py`` (that is, in the ``rsp_jupyter_extensions`` directory), add your new handler (whose route should start with ``/rubin``) to the map in ``_setup_handlers()``.
This will load your server extension into JupyterLab and make it accessible via the route you choose.


Developing the UI
^^^^^^^^^^^^^^^^^

Adding a new TypeScript component is done in the ``src`` top-level directory.

Choose a token
""""""""""""""
First, if your extension includes a UI widget (most do, but not all; for instance, the environment extension extracts the environment from the server side for the UI's consumption, but does not itself have any user-visible interface in the browser), assign a token (an arbitrary string) to the widget in ``tokens.ts``.

Write the extension
"""""""""""""""""""
The extension should get its own ``.ts`` file in the ``src`` directory; when you export the extension, its ``id`` attribute should be the token and its ``autostart`` attribute should be set to ``false``.
That is because it will be activated by the top-level index.

Note that, once you have the environment, you can use the ``logMessage()`` function to log messages to the console at a specified level.
Usually, ``INFO`` or higher messages will be shown, but if ``Enable debug logging`` was checked on the spawn page, you will get ``DEBUG`` messages too.
This is often extremely handy for determining why your extension isn't working.

Your extension will probably consume a JSON object via an ``apiRequest()`` call to the back end and take action based on the contents of that object's fields.

Update the index to load the extension
""""""""""""""""""""""""""""""""""""""
Finally, the top-level index, in ``index.ts``, should be modified to load your new extension at the appropriate place in the order.

That place is very likely after the environment has been loaded, and in general should probably go towards the bottom of the order.
This explicit activation is why individual components should not be autostarted.

Look at the existing ``index.ts`` for the way progress log messages are formatted.
Maintaining this format makes it easier to use the browser console to debug startup errors.

Testing
=======

Obviously you should do what you can with unit tests in the codebase.
However, particularly for user-interacting UI work, you will definitely want to build experimental containers with your codebase.

You will begin by making a branch of `sciplat-lab <https://github.com/lsst-sqre/sciplat-lab>`_.
On this branch, go into the ``scripts`` directory.

Where to install?
-----------------

The question of whether your changes need to be in the UI Python environment, or the DM Stack Python environment, or both, is tricky and you will need to think about it.
If your extension is purely about controlling the Lab's behavior, and doesn't need to refer to anything inside a running notebook (which is usually the case) then it only needs to run in the UI environment.  If it presents Python functionality to the user or relies on data coming from inside the DM stack, it will need to run in the payload environment.

To install a package into the UI environment, go down to the bottom of the ``install-rsp-user`` script.
You will see the line that activates the UI virtual environment: ``source /usr/local/share/jupyterlab/venv/bin/activate``.
Below there, do a ``uv pip install`` of your updated package or packages from the GitHub branch.

If your changes need to be visible from inside the payload Python (in our case, the DM stack), you will also need to add those packages inside the ``uv pip install`` a few lines above (where ``jupyter_firefly_extensions`` is installed).
Try to maintain the ``--no-build-isolation`` flag if you do this here, because otherwise you risk wildly changing the stack environment and your tests may not be representative of what a production container would look like.

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
#. You should leave the last two fields at their default values.

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
