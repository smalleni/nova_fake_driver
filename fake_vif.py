# special subclass of FakeDriver that also adds OVS controls.
# this file should be copied into the Nova installation in the local
# Python, such as /usr/lib/python2.7/site-packages/nova/virt/fake_vif.py
# It then can be invoked from nova.conf via
# compute_driver=fake_vif.OVSFakeDriver

import httplib2
import json
import socket
from six.moves import http_client as httplib

import nova.conf
from nova.virt import fake

from oslo_log import log as logging


CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)
socket_path = "/var/log/nova/fake_driver_netns.sock"


class UnixDomainHTTPConnection(httplib.HTTPConnection):
    """Connection class for HTTP over UNIX domain socket."""
    def __init__(self, host, port=None, strict=None, timeout=None,
                 proxy_info=None):
        httplib.HTTPConnection.__init__(self, host, port, strict)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)


class FakeNovaDriverClientConnection(UnixDomainHTTPConnection):
    def __init__(self, *args, **kwargs):
        # Old style super initialization is required!
        UnixDomainHTTPConnection.__init__(
            self, *args, **kwargs)


def send_command(command):
    # Note that the message is sent via a Unix domain socket so that
    # the URL doesn't matter.
    resp, content = httplib2.Http().request(
        'http://127.0.0.1/',
        method="POST",
        headers={'Content-Type': 'application/json'},
        body=json.dumps(command),
        connection_type=FakeNovaDriverClientConnection)

    if resp.status != 200:
        raise Exception('Unexpected response %s' % resp)


class OVSFakeDriver(fake.FakeDriver):
    def __init__(self, *arg, **kw):
        LOG.info("Spinning up OVSFakeDriver")
        super(OVSFakeDriver, self).__init__(*arg, **kw)

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None):
        self.plug_vifs(instance, network_info)
        ret = super(OVSFakeDriver, self).spawn(context, instance,
            image_meta, injected_files, admin_password, allocations,
            network_info=network_info, block_device_info=block_device_info)
        return ret

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        self.unplug_vifs(instance, network_info)
        return super(OVSFakeDriver, self).destroy(context, instance,
            network_info, block_device_info=block_device_info,
            destroy_disks=destroy_disks)

    def plug_vif(self, instance, vif):
        dev = vif.get("devname")
        port = vif.get("id")
        mac_address = vif.get("address")
        if not dev or not port or not mac_address:
            return
        ns = "fake-%s" % instance.uuid
        command = {"add_port": {"namespace": ns,
                                "vif": vif}}
        send_command(command)

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        ns = "fake-%s" % instance.uuid
        command = {"add_namespace": {"namespace": ns}}
        send_command(command)
        for vif in network_info:
            self.plug_vif(instance, vif)

    def unplug_vif(self, instance, vif):
        dev = vif.get("devname")
        port = vif.get("id")
        if not dev:
            if not port:
                return
            dev = "tap" + str(port[0:11])
        ns = "fake-%s" % instance.uuid
        command = {"delete_port": {"namespace": ns,
                                   "vif": vif}}
        send_command(command)

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        for vif in network_info:
            self.unplug_vif(instance, vif)
        # delete namespace after removing ovs ports
        ns = "fake-%s" % instance.uuid
        command = {"delete_namespace": {"namespace": ns}}
        send_command(command)
