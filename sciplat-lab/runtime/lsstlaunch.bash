#!/bin/bash
CONFIG_FILE=$1

fallback () {
    # /opt/lsst/sal only exists in SAL builds of the stack
    if [ -d /opt/lsst/sal ]; then
        source /opt/lsst/sal/salbldsteps.bash 2>&1 > /dev/null
        for i in xml idl sal salobj ATDome ATDomeTrajectory ATMCSSimulator \
                simactuators standardscripts scriptqueue externalscripts ; do
            setup ts_${i} -t current
        done
	setup lsst_sitcom  # RFC-992
    else
        source /opt/lsst/software/stack/loadLSST.bash
        setup lsst_distrib
    fi
    setup display_firefly
}

if [ -z "${RSP_SITE_TYPE}" ]; then
   fallback  # Preserve backwards compatibility for a while
else
    case ${RSP_SITE_TYPE} in
	telescope)
            source /opt/lsst/sal/salbldsteps.bash 2>&1 > /dev/null
            for i in xml idl sal salobj ATDome ATDomeTrajectory \
		     ATMCSSimulator simactuators standardscripts \
		     scriptqueue externalscripts ; do
		setup ts_${i} -t current
            done
	    setup lsst_sitcom
	    setup display_firefly
	    ;;
	staff)
            source /opt/lsst/software/stack/loadLSST.bash
	    setup lsst_sitcom
	    setup display_firefly
	    ;;
	*)  # Should be "science", and let's make that the default case.
            source /opt/lsst/software/stack/loadLSST.bash
	    setup lsst_distrib
	    setup display_firefly
	    ;;
    esac
fi

# Source user_setups if it's there
if [ -e ${HOME}/notebooks/.user_setups ]; then
    source ${HOME}/notebooks/.user_setups
fi
# And now transfer control over to Python
exec python3 -m ipykernel -f ${CONFIG_FILE}
