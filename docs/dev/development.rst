#################
Development guide
#################

This page provides procedures and guidelines for developing and contributing to Nublado.

Scope of contributions
======================

Nublado is an open source package, meaning that you can contribute to Nublado itself, or fork Nublado for your own purposes.

Since Nublado is intended for internal use by Rubin Observatory, community contributions can only be accepted if they align with Rubin Observatory's aims.
For that reason, it's a good idea to propose changes with a new `GitHub issue`_ before investing time in making a pull request.

Nublado is developed by the Rubin Observatory SQuaRE team.

.. _GitHub issue: https://github.com/lsst-sqre/nublado/issues/new

.. _dev-environment:

Setting up a local development environment
==========================================

Nublado is developed using `uv workspaces`_.
You will therefore need uv_ installed to set up a development environment.
See the `uv installation instructions <https://docs.astral.sh/uv/getting-started/installation/>`__ for details.

.. _uv workspaces: https://docs.astral.sh/uv/concepts/projects/workspaces/

Nublado development may require the :command:`pg_config` executable.
For Debian-based systems, install the ``libpq-dev`` package.
For RPM-based systems, install ``libpq-devel``.
For MacOS, using :command:`brew`, install ``postgresql``, or you can get the `PostgreSQL App <https://postgresapp.com/>`_ if you prefer standard Mac application packaging.

Once you have those prerequisites installed, get started by cloning the repository and setting up a virtual environment:

.. code-block:: sh

   git clone https://github.com/lsst-sqre/nublado.git
   cd nublado
   make init

This init step does three things:

1. Creates a Python virtual environment in the :file:`.venv` subdirectory with the packages needed to do Nublado development installed.
2. Installs Nublado in an editable mode in that virtual environment.
3. Installs the pre-commit hooks.

You can activate the Nublado virtual environment if you wish with:

.. prompt:: bash

   source .venv/bin/activate

This is optional; you do not have to activate the virtual environment to do development.
However, if you do, you can omit :command:`uv run` from the start of all commands described below.
Also, editors with Python integration, such as VSCode, may work more smoothly if you activate the virtualenv before starting them.

.. _pre-commit-hooks:

Pre-commit hooks
================

The pre-commit hooks, which are automatically installed by the :ref:`previous step <dev-environment>`, ensure that files are valid and properly formatted.
Some pre-commit hooks automatically reformat code:

``ruff``
    Lint Python code and attempt to automatically fix some problems.

``blacken-docs``
    Automatically formats Python code in reStructuredText documentation and docstrings.

When these hooks fail, your Git commit will be aborted.
To proceed, stage the new modifications and commit again.

If you have to commit changes that fail pre-commit checks, pass the ``--no-verify`` flag to :command:`git commit`.
This will have to be temporary, though, since the change will fail GitHub CI checks.

.. _dev-run-tests:

Running tests
=============

Nublado uses nox_ as its automation tool for testing.

To run all Nublado tests, run:

.. prompt:: bash

   uv run nox

This will run several nox sessions to lint and type-check the code, run the test suite, and build the documentation.

To list the available sessions, run:

.. prompt:: bash

   uv run nox --list

To run a specific test or list of tests, you can add test file names (and any other pytest_ options) after ``--`` when executing the ``test`` nox session.
For example:

.. prompt:: bash

   uv run nox -s test -- controller/tests/handlers/labs_test.py

Building documentation
======================

Documentation is built with Sphinx_.
It is built as part of a normal test run to check that the documentation can still build without warnings, or can be built explicitly with:

.. _Sphinx: https://www.sphinx-doc.org/en/master/

.. prompt:: bash

   uv run nox -s docs

The build documentation is located in the :file:`docs/_build/html` directory.

Additional dependencies required for the documentation build should be added to the ``docs`` dependency group in :file:`pyproject.toml`.

Documentation builds are incremental, and generate and use cached descriptions of the internal Python APIs.
If you see errors in building the Python API documentation or have problems with changes to the documentation (particularly diagrams) not showing up, try a clean documentation build with:

.. prompt:: bash

   uvn run nox -s docs-clean

This will be slower, but it will ensure that the documentation build doesn't rely on any cached data.

To check the documentation for broken links, run:

.. code-block:: sh

   uv run nox -s docs-linkcheck

Update pinned dependencies
==========================

All dependencies for Nublado are pinned to ensure reproducible builds and to control when dependencies are updated.
These pinned dependencies should be updated before each release.

Different parts of Nublado need to be installable in different contexts with different Python versions, so Nublado pins dependencies in multiple places.
The :file:`uv.lock` file at the top level handles some utility libraries, documentation builds, and some development dependencies.
Separte :file:`uv.lock` files in the :file:`client`, :file:`controller`, and :file:`hub` directories pin dependencies for those components.

To update all dependencies, run:

.. prompt:: bash

   make update-deps

You can instead run :command:`make update` to also update the installed dependencies in the development virtual environment.

If you need to add a new dependency as part of development, be sure to add it to the appropriate :file:`uv.lock` file.
This will generally be the :file:`uv.lock` file closest in proximity to where you made the change, which is often not the one at the top level of the project.

JupyterHub version upgrades
---------------------------

The dependency on ``jupyterhub`` used to construct the Nublado JupyterHub container is pinned in :file:`hub/pyproject.toml` to a specific version.
This version must match the version used in the image referenced in :file:`Dockerfile.jupyterhub` as the basis for the JupyterHub image.

The version shown in that file is the Zero to JupyterHub version, which will not match the ``jupyterhub`` package version.
You will need to look at the `Zero to JupyterHub change log <https://z2jh.jupyter.org/en/stable/changelog.html>`__ for a given Zero to JupyterHub release to determine the corresponding ``jupyterhub`` version.

When there is a new release of Zero to JupyterHub, update its version in :file:`Dockerfile.jupyterhub`, update :file:`hub/pyproject.toml` to corresponding ``jupyterhub`` version, and then regenerate dependencies with :command:`make update-deps`.

If the new version of ``jupyterhub`` is a major version bump, you will also need to update the dependency constraints in :file:`hub/plugins/authenticator/pyproject.toml` and :file:`hub/plugins/spawner/pyproject.toml`.

.. _dev-change-log:

Updating the change log
=======================

Nublado uses scriv_ to maintain its change log.

When preparing a pull request, run :command:`uv run scriv create`.
This will create a change log fragment in :file:`changelog.d`.
Edit that fragment, removing the sections that do not apply and adding entries fo this pull request.
You can pass the ``--edit`` flag to :command:`uv run scriv create` to open the created fragment automatically in an editor.

Change log entries use the following sections:

- **Backward-incompatible changes**
- **New features**
- **Bug fixes**
- **Other changes** (for minor, patch-level changes that are not bug fixes, such as logging formatting changes or updates to the documentation)

Changes that are not visible to the user, including minor documentation changes, should not have a change log fragment to avoid clutttering the change log with changes the user doesn't need to care about.

Do not include a change log entry solely for updating pinned dependencies, without any visible change to Nublado's behavior.
Every release is implicitly assumed to update all pinned dependencies.

These entries will eventually be cut and pasted into the release description for the next release, so the Markdown for the change descriptions must be compatible with GitHub's Markdown conventions for the release description.
Specifically:

- Each bullet point should be entirely on one line, even if it contains multiple sentences.
  This is an exception to the normal documentation convention of a newline after each sentence.
  Unfortunately, GitHub interprets those newlines as hard line breaks, so they would result in an ugly release description.
- Be cautious with complex markup, such as nested bullet lists, since the formatting in the GitHub release description may not be what you expect and manually repairing it is tedious.

.. _style-guide:

Style guide
===========

Code
----

- Nublado follows the :sqr:`072` Python style guide and uses the repository layout documented in :sqr:`075`.

- The code formatting follows :pep:`8`, though in practice lean on Black_ and Ruff_ to format the code for you.

- Use :pep:`484` type annotations.
  The :command:`uv run nox -s typing` session, which runs mypy_, ensures that the project's types are consistent.

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
