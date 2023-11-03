import nox

# Default sessions
nox.options.sessions = ["lint", "typing", "test", "docs"]

# Other nox defaults
nox.options.default_venv_backend = "venv"
nox.options.reuse_existing_virtualenvs = True

# pip-installable dependencies for all subpackages.
PIP_DEPENDENCIES = [
    ("--upgrade", "pip", "setuptools", "wheel"),
    ("-r", "controller/requirements/main.txt"),
    ("-r", "controller/requirements/dev.txt"),
    ("-e", "controller"),
    ("-r", "spawner/requirements/main.txt"),
    ("-r", "spawner/requirements/dev.txt"),
    ("-e", "spawner"),
]


def _install(session: nox.Session) -> None:
    """Install the application and all dependencies into the session."""
    for deps in PIP_DEPENDENCIES:
        session.install(*deps)


def _install_dev(session: nox.Session, bin_prefix: str = "") -> None:
    """Install the application and dev dependencies into the session."""
    python = f"{bin_prefix}python"
    precommit = f"{bin_prefix}pre-commit"

    # Install dev dependencies
    for deps in PIP_DEPENDENCIES:
        session.run(python, "-m", "pip", "install", *deps, external=True)
    session.run(
        python, "-m", "pip", "install", "nox", "pre-commit", external=True
    )

    # Install pre-commit hooks
    session.run(precommit, "install", external=True)


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


@nox.session(name="init", python=False)
def init(session: nox.Session) -> None:
    """Set up the development environment in the current virtual env."""
    _install_dev(session, bin_prefix="")


@nox.session
def lint(session: nox.Session) -> None:
    """Run pre-commit hooks."""
    session.install("pre-commit")
    session.run("pre-commit", "run", "--all-files", *session.posargs)


@nox.session
def typing(session: nox.Session) -> None:
    """Check type annotations with mypy."""
    _install(session)
    session.install("mypy")
    session.run(
        "mypy",
        *session.posargs,
        "noxfile.py",
        "controller/src",
        "spawner/src",
    )
    session.run(
        "mypy",
        *session.posargs,
        "controller/tests",
    )
    session.run(
        "mypy",
        *session.posargs,
        "spawner/tests",
    )


@nox.session
def test(session: nox.Session) -> None:
    """Run tests."""
    _install(session)
    with session.chdir("controller"):
        controller_args = [
            a.removeprefix("controller/")
            for a in session.posargs
            if a.startswith(("-", "controller/"))
        ]
        if not session.posargs or controller_args:
            session.run(
                "pytest",
                "--cov=controller",
                "--cov-branch",
                "--cov-report=",
                *controller_args,
            )
    with session.chdir("spawner"):
        spawner_args = [
            a.removeprefix("spawner/")
            for a in session.posargs
            if a.startswith(("-", "spawner/"))
        ]
        if not session.posargs or spawner_args:
            session.run(
                "pytest",
                "--cov=rsp_restspawner",
                "--cov-branch",
                "--cov-report=",
                *spawner_args,
            )


@nox.session
def docs(session: nox.Session) -> None:
    """Build the documentation."""
    _install(session)
    doctree_dir = (session.cache_dir / "doctrees").absolute()
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


@nox.session(name="docs-linkcheck")
def docs_linkcheck(session: nox.Session) -> None:
    """Check documentation links."""
    _install(session)
    doctree_dir = (session.cache_dir / "doctrees").absolute()
    with session.chdir("docs"):
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
            "./_build/html",
        )


@nox.session(name="update-deps")
def update_deps(session: nox.Session) -> None:
    """Update pinned server dependencies and pre-commit hooks."""
    session.install(
        "--upgrade", "pip-tools", "pip", "setuptools", "wheel", "pre-commit"
    )
    session.run("pre-commit", "autoupdate")
    for subdir in ("controller", "spawner"):
        session.run(
            "pip-compile",
            "--upgrade",
            "--resolver=backtracking",
            "--build-isolation",
            "--allow-unsafe",
            "--generate-hashes",
            "--output-file",
            f"{subdir}/requirements/main.txt",
            f"{subdir}/requirements/main.in",
        )
        session.run(
            "pip-compile",
            "--upgrade",
            "--resolver=backtracking",
            "--build-isolation",
            "--allow-unsafe",
            "--generate-hashes",
            "--output-file",
            f"{subdir}/requirements/dev.txt",
            f"{subdir}/requirements/dev.in",
        )

    print("\nTo refresh the development venv, run:\n\n\tnox -s init\n")


@nox.session(name="run")
def run(session: nox.Session) -> None:
    """Run the application in development mode."""
    _install(session)
    with session.chdir("controller"):
        session.run("uvicorn", "controller.main:app", "--reload")