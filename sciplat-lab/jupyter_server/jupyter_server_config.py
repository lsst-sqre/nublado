import os
import sys

# Set the standard console logger to log on WARNING (in jupyterlab startup).
#
# Create a new stdout logger on INFO and below; only use DEBUG if the
# environment variable DEBUG is set.

level="INFO"
if os.getenv("DEBUG"):
    level="DEBUG"

c.Application.logging_config = {
    'handlers': {
        'stdout': {
            'class': 'logging.StreamHandler',
            'level': level,
            'stream': 'ext://sys.stdout'
        }
    },
    'loggers': {
        'stdout': {
            'level': level,
            'handlers': [ 'stdout' ],
        }
    }
}
