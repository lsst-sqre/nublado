#!/bin/sh
if [ "${TERM}" == "xterm" ]; then
    TERM="xterm-color"
fi
export TERM

# Possibly controversial.  Feel free to override, change the color definitions,
#  or disable completely in your own .bash_profile.
eval $(dircolors -b /etc/dircolors.ansi-universal)
alias ls="ls --color=auto"

