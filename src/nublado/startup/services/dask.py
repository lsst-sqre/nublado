"""Set up Dask proxy configuration, needed by lsdb."""

import datetime
import shutil
from pathlib import Path
from typing import Any

import yaml
from structlog.stdlib import BoundLogger

__all__ = ["DaskConfigurator"]


class DaskConfigurator:
    """Configure dask proxy for lsdb."""

    def __init__(self, home: Path, logger: BoundLogger) -> None:
        self._home = home
        self._logger = logger

    def setup_dask(self) -> None:
        """Set up Dask proxy configuration."""
        self._logger.debug("Setting up dask dashboard proxy information")
        cfgdir = self._home / ".config" / "dask"
        good_dashboard_config = False
        if cfgdir.is_dir():
            good_dashboard_config = self._tidy_extant_config(cfgdir)
            # If we found and replaced the dashboard config, or if it was
            # already correct, we do not need to write a new file.
            #
            # If there is no config dir, there's nothing to tidy.
        if not good_dashboard_config:
            # We need to write a new file with the correct config.
            self._inject_new_proxy(cfgdir / "dashboard.yaml")

    def _inject_new_proxy(self, tgt: Path) -> None:
        # Conventional for RSP.
        parent = tgt.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            self._logger.exception(
                f"{parent!s} exists and is not a directory; aborting"
            )
            return
        newlink = "{JUPYTERHUB_PUBLIC_URL}proxy/{port}/status"
        goodlink = {"distributed": {"dashboard": {"link": newlink}}}
        if tgt.exists():
            try:
                obj = self._flense_dict(yaml.safe_load(tgt.read_text()))
                if obj is None:
                    obj = {}
                    # We'll turn it into an empty dict and get it in the
                    # update.  Why was there an empty dashboard.yaml?  Weird.
                elif obj == goodlink:
                    # This is the expected case.  There's only one entry in
                    # the target dashboard.yaml, and it's already correct.
                    return
                else:
                    self._logger.warning(
                        f"{tgt!s} exists; contains '{obj}'"
                        f" not just '{goodlink}'"
                    )
                obj.update(goodlink)
            except Exception:
                self._logger.exception(f"Failed to load {tgt!s}")
        else:
            obj = goodlink
        try:
            tgt.write_text(yaml.dump(obj, default_flow_style=False))
        except Exception:
            self._logger.exception(f"Failed to write '{obj}' to {tgt!s}")

    def _flense_dict(
        self, obj: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Recursively walk a dict; any place a null value is found, it
        and its corresponding key are removed.
        """
        if not obj:
            return None
        retval: dict[str, Any] = {}
        for key, val in obj.items():
            if val is None:
                continue
            if not isinstance(val, dict):
                retval[key] = val
                continue
            flensed = self._flense_dict(val)
            if flensed is None:
                continue
            retval[key] = flensed
        return retval or None

    def _tidy_extant_config(self, cfgdir: Path) -> bool:
        #
        # This is the controversial method.  We have had (at least) four
        # regimes of dask usage in the RSP.
        #
        # 1) Back in the mists of time (2018-ish), dask was present, and
        # all configuration was left to the user.
        # 2) For a while in 2019-2021-ish, we had a pretty sophisticated
        # system that allowed users to spawn whole additional pods, and we used
        # this for a really cool demo with Gaia DR1 data.  But then we moved to
        # the Nublado controller from KubeSpawner, and that no longer worked...
        # but we didn't do anything about the user config, so users had broken
        # config left over.
        # 3) from 2022-ish-to-2025 dask was not present.  The broken config
        # thus didn't cause any harm.
        # 4) in 2025, we added lsdb to the RSP.  lsdb relies on dask.  Suddenly
        # the abandoned config could cause harm, and without config, the wrong
        # dashboard information is presented to the user, which makes the lsdb
        # tutorial for Rubin DP1 data needlessly confusing.
        #
        # This is an attempt to clean that mess up.
        #
        # First we check for any files that don't do anything.  We know the
        # config will be YAML (dask config can also be JSON, but the RSP
        # machinery never wrote any such files, so we assume any JSON is
        # user-generated and not directly our problem), and those files will
        # be named with "yaml" or "yml" suffixes (both exist in extant user
        # config) per https://github.com/dask/dask/blob/main/dask/config.py .
        #
        # "Don't do anything" means that when deserialized to a Python object,
        # that object is None or empty, or it's a dictionary that contains only
        # empty objects as its leaves.  We move these files aside, with a date
        # suffix so that dask will no longer try to load them.
        #
        # Second, assuming the file survived that process, we check
        # specifically for the dashboard link, and correct it from its old,
        # non-user-domain-aware form, to a form that will be correct whether or
        # not user domains are enabled.  We save the original file with a date
        # suffix; again, dask will no longer try to load it.
        #
        # Other settings should stay the same; this may mean that the user has
        # settings for in-cluster kubernetes-driven workers, and those will
        # fail to spawn, but we haven't yet figured out how to safely remove
        # that configuration.
        #
        # If, after doing all of this, at least one file contains the correct
        # dashboard config, return True.  Otherwise, return False.

        retval = False

        for suffix in ("yaml", "yml"):
            files = list(cfgdir.glob(f"*.{suffix}"))
            if files:
                for fl in files:
                    today = (
                        datetime.datetime.now(tz=datetime.UTC)
                        .date()
                        .isoformat()
                    )
                    bk = Path(f"{fl!s}.{today}")
                    newcfg = self._clean_empty_config(fl, bk)
                    if not newcfg:
                        continue  # next file
                    retval = self._fix_dashboard(newcfg, fl, bk)
        return retval

    def _clean_empty_config(self, fl: Path, bk: Path) -> dict[str, Any] | None:
        # returns the deserialized yaml object if 1) it was deserializable
        # in the first place, and 2) it survived flensing.
        try:
            obj = yaml.safe_load(fl.read_text())
        except Exception:
            self._logger.exception(
                f"Failed to deserialize {fl!s} as yaml; moving to {bk}"
            )
            obj = None
        flensed = self._flense_dict(obj) if obj else None
        if not flensed:
            self._logger.warning(
                f"{fl} is empty after flensing; moving to {bk}"
            )
            shutil.move(fl, bk)
            return None
        # It's legal YAML and it's not empty
        return flensed

    def _fix_dashboard(self, cfg: dict[str, Any], fl: Path, bk: Path) -> bool:
        # Look for "distributed.dashboard.link".
        # It may have an older, non-user-domain-aware link in it,
        # and if so, then we need to replace it with the newer,
        # user-domain-aware one.

        # Dask does the template-from-environment substitution so these are
        # just strings.  The point is that "old" is not correct in a
        # user-domain-aware world, but "new" works in either case (and also
        # is something JupyterHub gives us for free, and does not rely on our
        # very-RSP-specific-and-going-away-with-service-discovery
        # EXTERNAL_INSTANCE_URL variable).

        # We return True if the deserialized contents of the file named by fl
        # (which will be passed to us as cfg) is a dashboard config with the
        # new template (whether initially or after correction) and False
        # otherwise.

        old = "{EXTERNAL_INSTANCE_URL}{JUPYTERHUB_SERVICE_PREFIX}"
        new = "{JUPYTERHUB_PUBLIC_URL}"

        try:
            val = cfg["distributed"]["dashboard"]["link"]
            if not isinstance(val, str):
                # Pretty sure this is an error, but leave it as the user's
                # problem.
                self._logger.warning(
                    "distributed.dashboard.link is not a string"
                )
                return False
        except KeyError:
            # We don't have the structure.  This file is not our problem.
            self._logger.debug(
                f"{fl!s} does not contain `distributed.dashboard.link`"
            )
            return False
        if val.find(new) > -1:
            # The structure is there and is already correct.
            # Return True and don't update anything.
            return True
        if val.find(old) < 0:
            # The structure is there but doesn't have the old-style link.
            # Assume, again, that's intentional.
            self._logger.debug(f"{val} does not contain {old}")
            return False

        # At this point, we have found distributed.dashboard.link.
        # It is a string, and it contains the old-style template so we want
        # to copy the original file to something without a yaml/yml suffix,
        # and replace the contents of the file with the old data but the
        # corrected link.
        try:
            # Make a backup.
            shutil.copy2(fl, bk)
        except Exception:
            self._logger.exception(f"Failed to back up {fl!s} to {bk!s}")
            return False
        newval = val.replace(old, new)
        if newval == val:
            self._logger.warning(
                f"Replacing '{old}' with '{new}' in '{val}' had no effect"
            )
            return False
        cfg["distributed"]["dashboard"]["link"] = newval
        self._logger.info(f"Replaced link in {fl!s}: {old}->{new}")
        try:
            fl.write_text(yaml.dump(cfg, default_flow_style=False))
        except Exception:
            self._logger.exception(f"Failed to write '{cfg}' to {fl!s}")
            return False
        return True
