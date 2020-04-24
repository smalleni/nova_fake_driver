from eventlet import wsgi
import eventlet
import logging
import netaddr
import os
import socket
import subprocess
import webob.dec


logfile = "/var/log/containers/nova/fake_driver_netns.log"
logging.basicConfig(filename=logfile, level=logging.DEBUG)


socket_path = "/var/log/containers/nova/fake_driver_netns.sock"
if os.path.exists(socket_path):
    os.remove(socket_path)


def execute_command(cmd):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        output, err = p.communicate()
    except Exception as e:
        logging.exception("cmd failed %s", e)
        raise
    return output, err


def add_namespace(ns):
    full_args = ["sudo", "ip", "netns", "add", ns]
    execute_command(full_args)
    full_args = ["sudo", "ip", "netns", "exec", ns,
                 "ip", "link", "set", "lo", "up"]
    execute_command(full_args)


def delete_namespace(ns):
    full_args = ["sudo", "ip", "netns", "del", ns]
    execute_command(full_args)


def add_port(ns, bridge, ovs_port, port_id,
             mac_address, ip_addresses, gateway):
    cmd = ["sudo", "ovs-vsctl", "--may-exist",
           "add-port", bridge, ovs_port,
           "--", "set", "Interface", ovs_port,
           "type=internal",
           "--", "set", "Interface", ovs_port,
           "external_ids:iface-id=%s" % port_id,
           "--", "set", "Interface", ovs_port,
           "external-ids:iface-status=active",
           "--", "set", "Interface", ovs_port,
           "external-ids:attached-mac=%s" % mac_address]
    execute_command(cmd)

    cmd = ["sudo", "ip", "link", "set", ovs_port, "netns", ns]
    execute_command(cmd)

    namespace = ["sudo", "ip", "netns", "exec", ns]
    cmd = namespace + ["ip", "link", "set", ovs_port, "up"]
    execute_command(cmd)

    namespace = ["sudo", "ip", "netns", "exec", ns]
    cmd = namespace + ["ip", "link", "set", ovs_port, "address", mac_address]
    execute_command(cmd)

    for address in ip_addresses:
        cmd = ["sudo", "ip", "netns", "exec", ns,
               "ip", "addr", "add", address, "dev", ovs_port]
        execute_command(cmd)

    namespace = ["sudo", "ip", "netns", "exec", ns]
    cmd = namespace + ["ip", "route", "add", "default"]
    cmd = cmd + ["via", gateway, "dev", ovs_port]
    execute_command(cmd)


def delete_port(ns, bridge, ovs_port):
    cmd = ["sudo", "ovs-vsctl", "--if-exists", "del-port", bridge, ovs_port]
    execute_command(cmd)


def get_ip_addresses(vif):
    addresses = []
    network = vif.get("network", {})
    for subnet in network.get("subnets", []):
        if subnet and subnet.get("version", "") == 4:
            cidr = subnet.get("cidr", None)
            for ip in subnet.get("ips", []):
                ip_address = ip.get("address", None)
                if cidr and ip_address:
                    prefixlen = netaddr.IPNetwork(cidr).prefixlen
                    ip_address = "%s/%s" % (ip_address, prefixlen)
                    addresses = addresses + [ip_address]
    return addresses


def get_default_route(vif):
    network = vif.get("network", {})
    for subnet in network.get("subnets", []):
        if subnet and subnet.get("version", "") == 4:
            gateway = subnet.get("gateway", {})
            return gateway.get("address", None)
    return None


def plug_vif(ns, vif):
    bridge = "br-int"
    dev = vif.get("devname")
    port = vif.get("id")
    mac_address = vif.get("address")
    if not dev or not port or not mac_address:
        return
    ip_addresses = get_ip_addresses(vif)
    gateway = get_default_route(vif)
    add_port(ns, bridge, dev, port, mac_address, ip_addresses, gateway)


def unplug_vif(ns, vif):
    bridge = "br-int"
    dev = vif.get("devname")
    port = vif.get("id")
    if not dev:
        if not port:
            return
        dev = "tap" + str(port[0:11])
    delete_port(ns, bridge, dev)


class UnixDomainHttpProtocol(eventlet.wsgi.HttpProtocol):
    def __init__(self, *args):
        server = args[-1]
        if len(args) == 2:
            conn_state = args[0]
            client_address = conn_state[0]
            if not client_address:
                conn_state[0] = ('<local>', 0)
            eventlet.wsgi.HttpProtocol.__init__(self, conn_state, server)
        elif len(args) == 3:
            request = args[0]
            client_address = args[1]
            if not client_address:
                client_address = ('<local>', 0)
            eventlet.wsgi.HttpProtocol.__init__(
                self, request, client_address, server)
        else:
            eventlet.wsgi.HttpProtocol.__init__(self, *args)


@webob.dec.wsgify(RequestClass=webob.Request)
def netns_handler(req, *args, **kwargs):
    content = req.json_body
    for k,v in content.items():
        if k == "add_namespace":
            namespace = v.get("namespace", None)
            add_namespace(namespace)
        elif k == "delete_namespace":
            namespace = v.get("namespace", None)
            delete_namespace(namespace)
        elif k == "add_port":
            namespace = v.get("namespace", None)
            vif = v.get("vif", None)
            plug_vif(namespace, vif)
        elif k == "delete_port":
            namespace = v.get("namespace", None)
            vif = v.get("vif", None)
            unplug_vif(namespace, vif)
        else:
            logging.warning("invalid key %s", k)
    return webob.response.Response()


socket = eventlet.listen(socket_path, family=socket.AF_UNIX, backlog=4906)

eventlet.wsgi.server(socket, netns_handler,
                     protocol=UnixDomainHttpProtocol,
                     keepalive=True,
                     socket_timeout=None)
