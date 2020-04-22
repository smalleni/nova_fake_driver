# copy this file to nova/privsep folder.
# This runs in privilege mode to create and delete
# namespaces.
"""
Linux network specific helpers.
"""


import errno
import os
import six

from pyroute2 import netns
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils

from nova import exception
import nova.privsep.linux_net


LOG = logging.getLogger(__name__)


@nova.privsep.sys_admin_pctxt.entrypoint
def create_netns(name):
    """Create a network namespace.

    :param name: The name of the namespace to create
    """
    try:
        netns.create(name)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

@nova.privsep.sys_admin_pctxt.entrypoint
def remove_netns(name):
    """Remove a network namespace.

    :param name: The name of the namespace to remove
    """
    try:
        netns.remove(name)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise


@nova.privsep.sys_admin_pctxt.entrypoint
def list_netns(**kwargs):
    """List network namespaces.

    Caller requires raised priveleges to list namespaces
    """
    return netns.listnetns(**kwargs)


