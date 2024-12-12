"""nox build configuration for Nublado."""

import shutil
import sys
from pathlib import Path

import nox
from nox.command import CommandFailed

# Default sessions
nox.options.sessions = [
    "lint",
    "typing",
    "typing-hub",
    "typing-inithome",
    "typing-client",
    "test",
    "test-hub",
    "test-inithome",
    "test-client",
    "docs",
    "docs-linkcheck",
]

# Other nox defaults
nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True

# pip-installable dependencies for development and documentation. This is not
# used for pytest and typing, since it merges the controller, authenticator,
# spawner, client, and inithome dependencies.
PIP_DEPENDENCIES = [
    (
        "-r",
        "./controller/requirements/main.txt",
        "-r",
        "./controller/requirements/dev.txt",
        "-r",
        "./inithome/requirements/main.txt",
        "-r",
        "./inithome/requirements/dev.txt",
    ),
    ("-e", "./authenticator[dev]"),
    ("-e", "./client[dev]"),
    ("-e", "./controller"),
    ("-e", "./inithome"),
    ("-e", "./spawner[dev]"),
]


def _install(session: nox.Session) -> None:
    """Install the application and all dependencies into the session."""
    session.install("--upgrade", "uv")
    for deps in PIP_DEPENDENCIES:
        session.install(*deps)


def _install_dev(session: nox.Session, bin_prefix: str = "") -> None:
    """Install the application and dev dependencies into the session."""
    python = f"{bin_prefix}python"
    precommit = f"{bin_prefix}pre-commit"

    # Install dev dependencies
    session.run(
        python,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "nox[uv]",
        "pre-commit",
        external=True,
    )
    for deps in PIP_DEPENDENCIES:
        session.run(python, "-m", "uv", "pip", "install", *deps, external=True)

    # Install pre-commit hooks
    session.run(precommit, "install", external=True)


def _pytest(
    session: nox.Session, directory: str, module: str, *, coverage: bool = True
) -> None:
    """Run pytest for the given directory and module, if needed."""
    generic = []
    per_directory = []
    found_per_directory = False
    for arg in session.posargs:
        if arg.startswith("-"):
            generic.append(arg)
        elif arg.startswith(f"{directory}/"):
            per_directory.append(arg.removeprefix(f"{directory}/"))
            found_per_directory = True
        elif "/" in arg and Path(arg).exists():
            found_per_directory = True
        else:
            generic.append(arg)
    if not session.posargs or not found_per_directory or per_directory:
        args = []
        if coverage:
            args.extend([f"--cov={module}", "--cov-branch", "--cov-report="])
        with session.chdir(directory):
            session.run(
                "pytest",
                *args,
                *generic,
                *per_directory,
            )


def _update_deps(
    session: nox.Session,
    *,
    generate_hashes: bool = True,
    hub_only: bool = False,
) -> None:
    session.install("--upgrade", "uv")
    session.install("--upgrade", "pre-commit")
    session.run("pre-commit", "autoupdate")
    directories = ("hub",) if hub_only else ("controller", "hub", "inithome")
    for directory in directories:
        command = ["uv", "pip", "compile", "--upgrade", "--universal"]
        if generate_hashes:
            command.append("--generate-hashes")

        # JupyterHub may use a different Python version.  This must be
        # whatever that is.
        if directory == "hub":
            command.extend(("-p", "3.12"))

        session.run(
            *command,
            "--output-file",
            f"{directory}/requirements/main.txt",
            f"{directory}/requirements/main.in",
        )
        session.run(
            *command,
            "--output-file",
            f"{directory}/requirements/dev.txt",
            f"{directory}/requirements/dev.in",
        )

    print("\nTo refresh the development venv, run:\n\n\tnox -s init\n")


@nox.session(name="venv-init")
def venv_init(session: nox.Session) -> None:
    """Set up a development venv.

    Create a venv in the current directory, replacing any existing one.
    """
    session.run("python", "-m", "venv", ".venv", "--clear")
    _install_dev(session, bin_prefix=".venv/bin/")

    print(
        "\nTo activate this virtual env, run:\n\n\tsource .venv/bin/activate\n"
    )


@nox.session(name="init", python=False, venv_backend="none")
def init(session: nox.Session) -> None:
    """Set up the development environment in the current virtual env."""
    _install_dev(session, bin_prefix="")


@nox.session
def lint(session: nox.Session) -> None:
    """Run pre-commit hooks."""
    session.install("--upgrade", "pre-commit")
    session.run("pre-commit", "run", "--all-files", *session.posargs)


@nox.session
def typing(session: nox.Session) -> None:
    """Check controller type annotations with mypy."""
    session.install(
        "-r",
        "./controller/requirements/main.txt",
        "-r",
        "./controller/requirements/dev.txt",
    )
    session.install("-e", "./controller")
    session.run(
        "mypy",
        *session.posargs,
        "noxfile.py",
        "controller/src",
        "controller/tests",
    )


@nox.session(name="typing-client")
def typing_client(session: nox.Session) -> None:
    """Check client type annotations with mypy."""
    session.install(
        "-e ./client[dev]",
    )
    session.run(
        "mypy",
        *session.posargs,
        "noxfile.py",
        "client/tests",
    )
    # "client" is, alas, a too-generic name, and you get "imported twice"
    # if you don't split it like this, because there's some builtin.  So
    # let's do the package explicitly with -p.
    session.run("mypy", *session.posargs, "-p", "rubin.nublado.client")


@nox.session(name="typing-hub")
def typing_hub(session: nox.Session) -> None:
    """Check hub plugin type annotations with mypy."""
    session.install(
        "-r",
        "./hub/requirements/main.txt",
        "-r",
        "./hub/requirements/dev.txt",
    )
    session.install("--no-deps", "-e", "./authenticator")
    session.install("--no-deps", "-e", "./spawner")
    session.run(
        "mypy",
        *session.posargs,
        "--namespace-packages",
        "--explicit-package-bases",
        "authenticator/src",
        "authenticator/tests",
        env={"MYPYPATH": "authenticator/src:authenticator"},
    )
    session.run(
        "mypy",
        *session.posargs,
        "--namespace-packages",
        "--explicit-package-bases",
        "spawner/src",
        "spawner/tests",
        env={"MYPYPATH": "spawner/src:spawner"},
    )


@nox.session(name="typing-inithome")
def typing_inithome(session: nox.Session) -> None:
    """Check inithome type annotations with mypy."""
    session.install(
        "-r",
        "./inithome/requirements/main.txt",
        "-r",
        "./inithome/requirements/dev.txt",
    )
    session.install("-e", "./inithome")
    session.run(
        "mypy",
        *session.posargs,
        "--namespace-packages",
        "--explicit-package-bases",
        "inithome/src",
        "inithome/tests",
        env={"MYPYPATH": "inithome/src:inithome"},
    )


@nox.session
def test(session: nox.Session) -> None:
    """Run tests of the Nublado controller."""
    session.install(
        "-r",
        "./controller/requirements/main.txt",
        "-r",
        "./controller/requirements/dev.txt",
    )
    session.install("-e", "./controller")
    _pytest(session, "controller", "controller")


@nox.session(name="test-hub")
def test_hub(session: nox.Session) -> None:
    """Run only tests affecting JupyterHub with its frozen dependencies."""
    session.install(
        "-r",
        "./hub/requirements/main.txt",
        "-r",
        "./hub/requirements/dev.txt",
    )
    session.install("--no-deps", "-e", "./authenticator")
    session.install("--no-deps", "-e", "./spawner")
    _pytest(
        session, "authenticator", "rubin.nublado.authenticator", coverage=False
    )
    _pytest(session, "spawner", "rubin.nublado.spawner")


@nox.session(name="test-inithome")
def test_inithome(session: nox.Session) -> None:
    """Run only tests affecting inithome."""
    session.install(
        "-r",
        "./inithome/requirements/main.txt",
        "-r",
        "./inithome/requirements/dev.txt",
    )
    session.install("-e", "./inithome")
    _pytest(session, "inithome", "rubin.nublado.inithome", coverage=False)


@nox.session(name="test-client")
def test_client(session: nox.Session) -> None:
    """Run only tests affecting client."""
    session.install("-e", "./client[dev]")
    _pytest(session, "client", "rubin.nublado.client", coverage=False)


@nox.session
def docs(session: nox.Session) -> None:
    """Build the documentation."""
    _install(session)
    doctree_dir = (session.cache_dir / "doctrees").absolute()

    # https://github.com/sphinx-contrib/redoc/issues/48
    redoc_js_path = Path("docs/_build/html/_static/redoc.js")
    if redoc_js_path.exists():
        redoc_js_path.unlink()

    with session.chdir("docs"):
        session.run(
            "sphinx-build",
            "-W",
            "--keep-going",
            "-n",
            "-T",
            "-b",
            "html",
            "-d",
            str(doctree_dir),
            ".",
            "./_build/html",
        )


@nox.session(name="docs-clean")
def docs_clean(session: nox.Session) -> None:
    """Build the documentation without any cache."""
    if Path("docs/_build").exists():
        shutil.rmtree("docs/_build")
    if Path("docs/dev/api/contents").exists():
        shutil.rmtree("docs/dev/api/contents")
    docs(session)


@nox.session(name="docs-linkcheck")
def docs_linkcheck(session: nox.Session) -> None:
    """Check documentation links."""
    _install(session)
    doctree_dir = (session.cache_dir / "doctrees").absolute()

    # https://github.com/sphinx-contrib/redoc/issues/48
    redoc_js_path = Path("docs/_build/linkcheck/_static/redoc.js")
    if redoc_js_path.exists():
        redoc_js_path.unlink()

    with session.chdir("docs"):
        try:
            session.run(
                "sphinx-build",
                "-W",
                "--keep-going",
                "-n",
                "-T",
                "-blinkcheck",
                "-d",
                str(doctree_dir),
                ".",
                "./_build/linkcheck",
            )
        except CommandFailed:
            output_path = Path("_build") / "linkcheck" / "output.txt"
            if output_path.exists():
                sys.stdout.write(output_path.read_text())
            session.error("Link check reported errors")


@nox.session(name="update-deps")
def update_deps(session: nox.Session) -> None:
    """Update pinned server dependencies and pre-commit hooks."""
    _update_deps(session)


@nox.session(name="update-deps-hub")
def update_deps_hub(session: nox.Session) -> None:
    """Update pinned JupyterHub dependencies and pre-commit hooks."""
    _update_deps(session, hub_only=True)


@nox.session(name="update-deps-no-hashes")
def update_deps_no_hashes(session: nox.Session) -> None:
    """Update pinned server dependencies without hashes.

    Used when testing against unreleased dependencies, such as a Git version
    of Safir.
    """
    _update_deps(session, generate_hashes=False)


@nox.session(name="run")
def run(session: nox.Session) -> None:
    """Run the application in development mode."""
    _install(session)
    with session.chdir("controller"):
        session.run("uvicorn", "controller.main:app", "--reload")
