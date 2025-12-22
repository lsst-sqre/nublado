"""Set up custom logging for RSP.

At startup, if ${HOME}/.ipython/profile_default/startup/20-logging.py does
not exist, this file will be copied to it from /opt/lsst/software/jupyterlab.

It will also be copied if that file exists but is an earlier standard version
(as determined via sha256sum).

If you don't like what it does, create an empty file (or one that does what
you want) at ${HOME}/.ipython/profile_default/startup/20-logging.py and it
will not be recopied.
"""

import logging
import os
import sys

customlogger = False

try:
    from lsst.rsp import IPythonHandler, forward_lsst_log

    customlogger = True
except ImportError:
    pass  # Probably a container that doesn't have our new code

# If the whole container is in debug mode, enable debug logging by default.
# Otherwise, use the default level (which is warning); however, lsst logs
# should be at info level.
debug = os.getenv("DEBUG")
handlers = []
if customlogger:
    # Forward anything at INFO or above, unless debug is set, in which case,
    # forward DEBUG and above.
    if debug:
        forward_lsst_log("DEBUG")
    else:
        forward_lsst_log("INFO")
    handlers = [IPythonHandler()]
else:
    # Set up WARNING and above as stderr, below that to stdout.  This is
    # intended to make GKE error reporting more consistent and to correspond
    # to the usual Unix distinction between error and non-error output.
    warnhandler = logging.StreamHandler(stream=sys.stderr)
    warnhandler.setLevel(logging.WARNING)
    handlers = [warnhandler]
    if debug:
        lowhandler = logging.StreamHandler(stream=sys.stdout)
        lowhandler.setLevel(logging.DEBUG)
        handlers.append(lowhandler)
logging.basicConfig(force=True, handlers=handlers)
# Now set up INFO for lsst logs everywhere
logging.getLogger("lsst").setLevel(logging.INFO)
