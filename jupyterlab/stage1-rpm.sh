#!/bin/sh
# This will be an interactive system, so we do want man pages after all
sed -i -e '/tsflags\=nodocs/d' /etc/yum.conf
yum clean all
rpm -qa --qf "%{NAME}\n" | xargs yum -y reinstall
yum install -y epel-release man man-pages
yum repolist
yum -y upgrade
yum -y install \
      git sudo \
      http-parser perl-Digest-MD5 \
      make zlib-devel perl-ExtUtils-MakeMaker gettext \
      ack screen tmux tree vim-enhanced emacs-nox jq \
      graphviz geos-devel hdf5-devel \
      sqlite-devel \
      mariadb mysql mysql-devel \
      unzip nano file ed \
      ncurses ncurses-devel wget
# Tkinter and git: install from SCL
yum -y install centos-release-scl && \
     yum -y install rh-git218
# Install git-lfs repo and then git-lfs
S="script.rpm.sh" && \
      curl -s \
       https://packagecloud.io/install/repositories/github/git-lfs/${S} \
       -o /tmp/script.rpm.sh && \
      bash /tmp/script.rpm.sh && \
      rm /tmp/script.rpm.sh && \
      yum -y install git-lfs && \
      source scl_source enable rh-git218 && \
      git lfs install
# Install newer nodejs for system; needed for JupyterLab build
cd /tmp && \
      curl -sL https://rpm.nodesource.com/setup_14.x -o node_repo.sh && \
      chmod 0755 node_repo.sh && \
      ./node_repo.sh && \
      rm ./node_repo.sh && \
      yum -y install nodejs
# Install yarn repo and then yarn
curl --silent --location https://dl.yarnpkg.com/rpm/yarn.repo \
       > /etc/yum.repos.d/yarn.repo && \
      yum -y install yarn
