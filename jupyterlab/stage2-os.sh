#!/bin/sh
mkdir -p ${srcdir}/thirdparty
# Install Hub
cd /tmp && \
     V="2.14.2" && \
     FN="hub-linux-amd64-${V}" && \
     F="${FN}.tgz" && \
     URL="https://github.com/github/hub/releases/download/v${V}/${F}" && \
     cmd="curl -L ${URL} -o ${F}" && \
     ${cmd} && \
     tar xpfz ${F} && \
     install -m 0755 ${FN}/bin/hub /usr/bin && \
     rm -rf ${F} ${FN}
# This is for Fritz, and my nefarious plan to make the "te" in "Jupyter"
#  TECO
# We're not doing the "Make" alias--too likely to confuse
cd ${srcdir}/thirdparty && \
      git clone https://github.com/blakemcbride/TECOC.git && \
      cd TECOC/src && \
      make -f makefile.linux && \
      install -m 0755 tecoc /usr/local/bin && \
      mkdir -p /usr/local/share/doc/tecoc && \
      cp ../doc/* /usr/local/share/doc/tecoc && \
      cd /usr/local/bin && \
      for i in teco inspect mung; do \
          ln -s tecoc ${i} ; \
      done
# Install minimal LaTeX from TexLive
cd /tmp/tex && \
      FN="install-tl-unx.tar.gz" && \
      wget http://mirror.ctan.org/systems/texlive/tlnet/${FN} && \
      tar xvpfz ${FN} && \
      ./install-tl-*/install-tl --repository \
      http://ctan.math.illinois.edu/systems/texlive/tlnet \
        --profile /tmp/tex/texlive.profile && \
      rm -rf /tmp/tex/${FN} /tmp/tex/install-tl*
# More TeX stuff we need for PDF export
PATH=/usr/local/texlive/2020/bin/x86_64-linux:${PATH} && \
     tlmgr install caption lm adjustbox xkeyval collectbox xcolor \
     upquote eurosym ucs fancyvrb zapfding booktabs enumitem ulem palatino \
     mathpazo tcolorbox pgf environ trimspaces etoolbox float rsfs jknapltx \
     latexmk dvipng beamer parskip fontspec titling tools
# This, bizarrely, has to be installed on its own to get the binaries.
PATH=/usr/local/texlive/2020/bin/x86_64-linux:${PATH} && \
     tlmgr install xetex && \
     ln -s /usr/local/texlive/2020/bin/x86_64-linux/xelatex \
           /usr/local/texlive/2020/bin/x86_64-linux/bibtex \
           /usr/bin
