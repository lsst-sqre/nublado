#################
Development guide
#################

This page provides procedures and guidelines for developing and contributing to Nublado.

Scope of contributions
======================

Nublado is an open source package, meaning that you can contribute to Nublado itself, or fork Nublado for your own purposes.

Since Nublado is intended for internal use by Rubin Observatory, community contributions can only be accepted if they align with Rubin Observatory's aims.
For that reason, it's a good idea to propose changes with a new `GitHub issue`_ before investing time in making a pull request.

Nublado is developed by the LSST SQuaRE team.

.. _GitHub issue: https://github.com/lsst-sqre/nublado/issues/new

.. _dev-environment:

Setting up a local development environment
==========================================

Development of Nublado should be done inside a virtual environment.

Nublado uses nox_ as its build system, which can manage a virtual environment for you.
Run:

.. prompt:: bash

   nox -s venv-init

The resulting virtual environment will be created in :file:`.venv`.
Enable it by running :command:`source .venv/bin/activate`.

Alternately, you can create a virtual environment with any other method of your choice (such as virtualenvwrapper_).
If you use a different virtual environment, run the following command after you have enabled it:

.. prompt:: bash

   nox -s init

Either ``venv-init`` or ``init`` does the following:

#. Installs build system dependencies in the virtual environment.
#. Installs package dependencies, including test and documentation dependencies.
#. Installs Nublado packages in editable mode so that changes made to the Git checkout will be picked up by the virtual environment.
#. Installs pre-commit hooks.

.. _pre-commit-hooks:

Pre-commit hooks
================

The pre-commit hooks, which are automatically installed by the :ref:`previous step <dev-environment>`, ensure that files are valid and properly formatted.
Some pre-commit hooks automatically reformat code:

``ruff``
    Lint Python code and attempt to automatically fix some problems.

``black``
    Automatically formats Python code.

``blacken-docs``
    Automatically formats Python code in reStructuredText documentation and docstrings.

When these hooks fail, your Git commit will be aborted.
To proceed, stage the new modifications and commit again.

If you have to commit changes that fail pre-commit checks, pass the ``--no-verify`` flag to :command:`git commit`.
This will have to be temporary, though, since the change will fail GitHub CI checks.

.. _dev-run-tests:

Running tests
=============

To run all Nublado tests, run:

.. prompt:: bash

   nox -s

This tests the library in the same way that the CI workflow does.
You may wish to run the individual sessions (``lint``, ``typing``, ``typing-hub``, ``test``, ``test-hub``, and ``docs``) when iterating on a specific change.
Consider using the ``-R`` flag when you haven't updated dependencies, as discussed below.

mypy and pytest tests are divided into two nox sessions: one for the Nublado controller (the default) and one for JupyterHub and its plugins.
The JupyterHub plugins have to support different versions of Python and have different frozen dependencies, so must be tested separately.
Use the ``typing-hub`` and ``test-hub`` sessions to do that.
Since most code and thus most code changes is part of the controller, the ``typing`` and ``test`` sessions with no suffix test it.

To see a listing of nox sessions:

.. prompt:: bash

   nox --list

To run a specific test or list of tests, you can add test file names (and any other pytest_ options) after ``--`` when executing the ``test`` or ``test-hub`` nox session.
For example:

.. prompt:: bash

   nox -s test -- controller/tests/handlers/prepuller_test.py

If you are interating on a specific test failure, you may want to pass the ``-R`` flag to skip the dependency installation step.
This will make nox run much faster, at the cost of not fixing out-of-date dependencies.
For example:

.. prompt:: bash

   nox -Rs test -- controller/tests/handlers/prepuller_test.py

Update pinned dependencies
==========================

All dependencies for Nublado are pinned to ensure reproducible builds and to control when dependencies are updated.
These pinned dependencies should be updated before each release.

To update dependencies, run:

.. prompt:: bash

   nox -s update-deps

The dependency on ``jupyterhub`` is a special exception
It is always pinned to a specific point release that matches the version used in :file:`Dockerfile.hub` as the basis for the JupyterHub containers.
When there is a new release of JupyterHub, update its version in both :file:`Dockerfile.hub` and :file:`hub/requirements/main.in` to the same version, and then regenerate dependencies using the above command.

Building documentation
======================

Documentation is built with Sphinx_:

.. _Sphinx: https://www.sphinx-doc.org/en/master/

.. prompt:: bash

   nox -s docs

The build documentation is located in the :file:`docs/_build/html` directory.

Additional dependencies required for the documentation build should be added as development dependencies of the Nublado controller, in :file:`controller/requirements/dev.in`.

Documentation builds are incremental, and generate and use cached descriptions of the internal Python APIs.
If you see errors in building the Python API documentation or have problems with changes to the documentation (particularly diagrams) not showing up, try a clean documentation build with:

.. prompt:: bash

   nox -s docs-clean

This will be slower, but it will ensure that the documentation build doesn't rely on any cached data.

To check the documentation for broken links, run:

.. code-block:: sh

   nox -s docs-linkcheck

.. _dev-change-log:

Updating the change log
=======================

Nublado uses scriv_ to maintain its change log.

When preparing a pull request, run :command:`scriv create`.
This will create a change log fragment in :file:`changelog.d`.
Edit that fragment, removing the sections that do not apply and adding entries fo this pull request.
You can pass the ``--edit`` flag to :command:`scriv create` to open the created fragment automatically in an editor.

Change log entries use the following sections:

- **Backward-incompatible changes**
- **New features**
- **Bug fixes**
- **Other changes** (for minor, patch-level changes that are not bug fixes, such as logging formatting changes or updates to the documentation)

Do not include a change log entry solely for updating pinned dependencies, without any visible change to Nublado's behavior.
Every release is implicitly assumed to update all pinned dependencies.

These entries will eventually be cut and pasted into the release description for the next release, so the Markdown for the change descriptions must be compatible with GitHub's Markdown conventions for the release description.
Specifically:

- Each bullet point should be entirely on one line, even if it contains multiple sentences.
  This is an exception to the normal documentation convention of a newline after each sentence.
  Unfortunately, GitHub interprets those newlines as hard line breaks, so they would result in an ugly release description.
- Avoid using too much complex markup, such as nested bullet lists, since the formatting in the GitHub release description may not be what you expect and manually editing it is tedious.

.. _style-guide:

Style guide
===========

Code
----

- Nublado follows the :sqr:`072` Python style guide and uses the repository layout documented in :sqr:`075`.

- The code formatting follows :pep:`8`, though in practice lean on Black_ and Ruff_ to format the code for you.

- Use :pep:`484` type annotations.
  The :command:`nox -s typing` session, which runs mypy_, ensures that the project's types are consistent.

- Nublado uses the Ruff_ linter with most checks enabled.
  Try to avoid ``noqa`` markers except for issues that need to be fixed in the future.
  Tests that generate false positives should normally be disabled, but if the lint error can be avoided with minor rewriting that doesn't make the code harder to read, prefer the rewriting.

- Write tests for pytest_.

Documentation
-------------

- Follow the `LSST DM User Documentation Style Guide`_, which is primarily based on the `Google Developer Style Guide`_.

- Document the Python API with numpydoc-formatted docstrings.
  See the `LSST DM Docstring Style Guide`_.

- Follow the `LSST DM ReStructuredTextStyle Guide`_.
  In particular, ensure that prose is written **one-sentence-per-line** for better Git diffs.

.. _`LSST DM User Documentation Style Guide`: https://developer.lsst.io/user-docs/index.html
.. _`Google Developer Style Guide`: https://developers.google.com/style/
.. _`LSST DM Docstring Style Guide`: https://developer.lsst.io/python/style.html
.. _`LSST DM ReStructuredTextStyle Guide`: https://developer.lsst.io/restructuredtext/style.html
