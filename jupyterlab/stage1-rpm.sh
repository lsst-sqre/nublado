#!/bin/sh
# This will be an interactive system, so we do want man pages after all
sed -i -e '/tsflags\=nodocs/d' /etc/yum.conf
yum clean all
rpm -qa --qf "%{NAME}\n" | xargs yum -y reinstall
yum install -y epel-release man man-pages
yum repolist
yum -y upgrade
yum -y install \
      sudo gettext fontconfig ack screen tmux tree vim-enhanced emacs-nox jq \
      unzip nano file ed
