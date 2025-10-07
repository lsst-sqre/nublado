"""The Purger class provides mechanisms for setting its policy,
planning actions according to its policy, reporting its plans, and
executing its plans.
"""

import asyncio
import datetime
from pathlib import Path

import yaml
from safir.logging import configure_logging
from safir.slack.webhook import SlackRouteErrorHandler
from structlog.stdlib import BoundLogger, get_logger

from .config import Config
from .constants import ROOT_LOGGER
from .exceptions import NotLockedError, PlanNotReadyError
from .models.plan import FileClass, FileReason, FileRecord, Plan
from .models.v1.policy import DirectoryPolicy, Policy


class Purger:
    """Object to plan and execute filesystem purges."""

    def __init__(
        self, config: Config, logger: BoundLogger | None = None
    ) -> None:
        self._config = config
        if logger is None:
            self._logger = get_logger(ROOT_LOGGER)
            configure_logging(
                name=ROOT_LOGGER,
                profile=config.logging.profile,
                log_level=config.logging.log_level,
                add_timestamp=config.logging.add_timestamp,
            )
        else:
            self._logger = logger
        if self._config.alert_hook:
            SlackRouteErrorHandler.initialize(
                str(self._config.alert_hook), ROOT_LOGGER, self._logger
            )
            self._logger.debug("Slack webhook initialized")
        cfgdict = self._config.to_dict()
        if "alert_hook" in cfgdict:
            cfgdict["alert_hook"] = "<SECRET>"
        self._logger.info("Purger initialized", config=cfgdict)
        # Anything that uses the plan should acquire the lock before
        # proceeding.
        self._lock = asyncio.Lock()
        self._plan: Plan | None = None

    def set_policy_file(self, policy_file: Path) -> None:
        old = self._config.policy_file
        self._config.policy_file = policy_file
        self._logger.debug(f"Reset policy file: '{old}' -> '{policy_file}'")

    async def plan(self) -> None:
        """Scan our directories and assemble a plan.  We can only do this
        when an operation is not in progress, hence the lock.
        """
        self._logger.debug("Attempting to acquire lock for plan()")
        async with self._lock:
            self._logger.debug("Lock for plan() acquired.")
            await self._perform_plan()

    async def _perform_plan(self) -> None:
        # This does the actual work.
        # We split it so we can do a do-it-all run under a single lock.
        if not self._lock.locked():
            raise NotLockedError("Cannot plan: do not have lock")

        self._logger.debug(f"Reloading policy from {self._config.policy_file}")
        policy_doc = yaml.safe_load(self._config.policy_file.read_text())
        policy = Policy.model_validate(policy_doc)

        # Invalidate any current plan
        self._plan = None

        directories = policy.get_directories()

        visited: list[Path] = []

        # Set time at beginning of run
        now = datetime.datetime.now(tz=datetime.UTC)
        then = now
        later = self._config.future_duration
        if later:
            self._logger.info(
                f"Planning for time {later.total_seconds()}s from now."
            )
            then += later
        purge: list[FileRecord] = []
        while directories:
            # Take a directory (the longest remaining) off the end
            # of the list, and consider it.
            consider = directories.pop()
            self._logger.debug(f"Considering {consider!s}")
            # Grab the policy.
            current_policy = self._get_directory_policy(
                path=consider, policy=policy
            )
            for root, _, files in consider.walk():
                # Check whether this root has already been handled
                # by another, more specific policy.
                if self._check_visited(root, visited):
                    self._logger.debug(f"Directory {root!s} already checked.")
                    continue
                # Check each file.
                for file in files:
                    purge_file = self._check_file(
                        path=root / file, policy=current_policy, when=then
                    )
                    if purge_file is not None:
                        self._logger.debug(
                            f"Adding {purge_file} to purge list"
                        )
                        purge.append(purge_file)
            # OK, we're done with this tree.  Skip it when
            # considering higher (shorter-named) directories.
            visited.insert(0, consider)

        self._plan = Plan(files=purge, directories=visited)

    def _get_directory_policy(
        self, path: Path, policy: Policy
    ) -> DirectoryPolicy:
        for d_policy in policy.directories:
            if d_policy.path == path:
                return d_policy
        # We don't raise a specific error because this should be a can't-
        # happen kind of error: we only ever run _get_directory_policy from
        # inside a loop over policy directories.
        raise ValueError(f"Policy for '{path}' not found")

    def _check_visited(self, root: Path, visited: list[Path]) -> bool:
        return any(vis == root or vis in root.parents for vis in visited)

    def _check_file(
        self, path: Path, policy: DirectoryPolicy, when: datetime.datetime
    ) -> FileRecord | None:
        # This is the actual meat of the purger.  We've found a file.
        # Determine if it is large or small, and then compare its three
        # times against our removal criteria.  If any of them match, mark
        # it for deletion.
        #
        # If it is a match, return a FileRecord; if not, return None.
        #
        # If it is a symlink, ignore it.  If it's a link to an actual file
        # managed by our policy, we'll get to it there, and if it isn't,
        # we shouldn't do anything about it.  That will leave a dangling
        # symlink and the directories leading down to it.  We might want to
        # think about this sometime, but it's only going to be a handful
        # of bytes in any event.
        if path.is_symlink():
            self._logger.debug(f"{path!s} is a symbolic link; skipping")
            return None
        self._logger.debug(f"Checking {path!s} against {policy} for {when}")
        try:
            st = path.stat()
        except FileNotFoundError as exc:
            self._logger.warning(f"{path!s} not found: {exc!s}; skipping")
            return None
        except PermissionError as exc:
            self._logger.warning(
                f"Could not stat() '{path!s}': {exc!s}; skipping"
            )
        # Get large-or-small policy, depending.
        size = st.st_size
        if size >= policy.threshold:
            ivals = policy.intervals.large
            f_class = FileClass.LARGE
        else:
            ivals = policy.intervals.small
            f_class = FileClass.SMALL
        atime = datetime.datetime.fromtimestamp(st.st_atime, tz=datetime.UTC)
        ctime = datetime.datetime.fromtimestamp(st.st_ctime, tz=datetime.UTC)
        mtime = datetime.datetime.fromtimestamp(st.st_mtime, tz=datetime.UTC)
        a_max = ivals.access_interval
        c_max = ivals.creation_interval
        m_max = ivals.modification_interval

        # Check the file against the intervals
        if a_max and (atime + a_max < when):
            self._logger.debug(f"atime: {path!s}")
            return FileRecord(
                path=path,
                file_class=f_class,
                file_reason=FileReason.ATIME,
                file_interval=when - atime,
                criterion_interval=a_max,
            )
        if c_max and (ctime + c_max < when):
            self._logger.debug(f"ctime: {path!s}")
            return FileRecord(
                path=path,
                file_class=f_class,
                file_reason=FileReason.CTIME,
                file_interval=when - ctime,
                criterion_interval=c_max,
            )
        if m_max and (mtime + m_max < when):
            self._logger.debug(f"mtime: {path!s}")
            return FileRecord(
                path=path,
                file_class=f_class,
                file_reason=FileReason.MTIME,
                file_interval=when - mtime,
                criterion_interval=m_max,
            )
        return None

    async def report(self) -> None:
        """Report what directories are to be purged."""
        self._logger.debug("Awaiting lock for report()")
        async with self._lock:
            self._logger.debug("Acquired lock for report()")
            await self._perform_report()

    async def _perform_report(self) -> None:
        # This does the actual work.
        # We split it so we can do a do-it-all run under a single lock.
        if not self._lock.locked():
            raise NotLockedError("Cannot report: do not have lock")
        if self._plan is None:
            raise PlanNotReadyError("Cannot report: plan not ready")
        rpt_text = str(self._plan)
        self._logger.info(rpt_text)

    async def purge(self) -> None:
        """Purge files and after-purge-empty directories."""
        if self._config.dry_run:
            self._logger.warning(
                "Cannot purge because dry_run enabled; reporting instead"
            )
            await self.report()
            return
        if self._config.future_duration:
            self._logger.warning(
                "Cannot purge because future_duration is set; reporting"
                " instead"
            )
            await self.report()
            return
        self._logger.debug("Awaiting lock for purge()")
        async with self._lock:
            self._logger.debug("Acquired lock for purge()")
            await self._perform_purge()

    async def _perform_purge(self) -> None:
        # This does the actual work.
        # We split it so we can do a do-it-all run under a single lock.
        if not self._lock.locked():
            raise NotLockedError("Cannot purge: do not have lock")
        if self._plan is None:
            raise PlanNotReadyError("Cannot purge: plan not ready")
        failed_files: dict[Path, Exception] = {}
        for purge_file in self._plan.files:
            path = purge_file.path
            self._logger.debug(f"Removing {path!s}")
            try:
                path.unlink()
            except (FileNotFoundError, PermissionError) as exc:
                failed_files[path] = exc
        self._logger.debug("File purge complete; removing empty dirs")
        self._tidy_victim_dirs(failed_files)

    def _tidy_victim_dirs(self, failed_files: dict[Path, Exception]) -> None:
        if self._plan is None:
            # This can't really happen, but mypy doesn't know that
            return
        plan_dirs = self._plan.directories
        victim_dirs: list[Path] = []
        for pdir in plan_dirs:
            res = pdir.walk()
            for thing in res:
                dirpath = thing[0]
                dirnames = thing[1]
                victim_dirs.extend([(dirpath / x) for x in dirnames])
        vd_l = sorted(victim_dirs, key=lambda x: len(str(x)), reverse=True)
        victims = self._filter_victim_dirs(vd_l, plan_dirs)
        self._logger.debug(
            f"Now-empty dirs to remove: {[str(x) for x in vd_l]}"
        )
        for victim in victims:
            if len(list(victim.glob("*"))) == 0:
                self._logger.debug(f"Removing empty directory {victim!s}")
                try:
                    victim.rmdir()
                except (FileNotFoundError, PermissionError) as exc:
                    failed_files[victim] = exc

        if failed_files:
            failed_files_str = {
                str(k): str(v) for k, v in failed_files.items()
            }
            self._logger.warning(
                "Purge encountered errors", failed_files=failed_files_str
            )
        else:
            self._logger.debug("Purge complete")
        # We've acted on the plan, so it is no longer valid.  We must
        # rerun plan() before running purge() or report() again.
        self._plan = None

    def _filter_victim_dirs(
        self, candidates: list[Path], plan_dirs: list[Path]
    ) -> set[Path]:
        victim_dirs: set[Path] = set()
        parents: set[Path] = set()
        for named in plan_dirs:
            for p_dir in named.parents:
                parents.add(p_dir)
        for victim in candidates:
            if victim in plan_dirs:
                self._logger.debug(
                    f"Won't remove directory {victim!s} named"
                    " directly in policy"
                )
                continue
            if victim in parents:
                self._logger.debug(
                    f"Won't remove directory {victim!s} because it is a"
                    " parent of a directory named in policy"
                )
                continue
            victim_dirs.add(victim)
        return victim_dirs

    async def execute(self) -> None:
        """Create a plan, report it, and immediately execute it.

        This is the do-it-all method and will be the usual entrypoint for
        actual use.
        """
        self._logger.debug("Awaiting lock for execute()")
        async with self._lock:
            self._logger.debug("Acquired lock for execute()")
            await self._perform_plan()
            await self._perform_report()
            await self._perform_purge()
