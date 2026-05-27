#!/bin/sh
PATH=/usr/local/bin:$PATH
PATH=$HOME/bin:$HOME/.local/bin:$PATH
LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/usr/local/lib64
MANPATH=/usr/local/share/man:$MANPATH
INFOPATH=/usr/local/share/info:$INFOPATH
export PATH MANPATH INFOPATH LD_LIBRARY_PATH
