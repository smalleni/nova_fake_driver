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


def add_port(ns, brint, dev, port_id,
             mac_address, ip_addresses, gateway, mtu):
    vet = "vet" + str(dev[3:14])
    qbr = "qbr" + str(dev[3:14])
    qvb = "qvb" + str(dev[3:14])
    qvo = "qvo" + str(dev[3:14])

    # create linux bridge i.e qbr
    cmd = ["sudo", "ip", "link", "add", qbr, "type", "bridge"]
    execute_command(cmd)

    cmd = ["sudo", "ip", "link", "set", qbr, "up"]
    execute_command(cmd)

    # create tap device as veth pair
    cmd = ["sudo", "ip", "link", "add", dev, "type", "veth", "peer", "name", vet]
    execute_command(cmd)

    cmd = ["sudo", "ip", "link", "set", vet, "up", "master", qbr]
    execute_command(cmd)

    # create qvb-qvo veth pair
    cmd = ["sudo", "ip", "link", "add", qvb, "type", "veth", "peer", "name", qvo]
    execute_command(cmd)

    cmd = ["sudo", "ip", "link", "set", qvb, "up", "master", qbr]
    execute_command(cmd)

    cmd = ["sudo", "ip", "link", "set", qvo, "up"]
    execute_command(cmd)

    # add qvo to ovs br-int
    cmd = ["sudo", "ovs-vsctl", "--may-exist",
           "add-port", brint, qvo,
           "--", "set", "Interface", qvo,
           "external_ids:iface-id=%s" % port_id,
           "--", "set", "Interface", qvo,
           "external-ids:iface-status=active",
           "--", "set", "Interface", qvo,
           "external-ids:attached-mac=%s" % mac_address]
    execute_command(cmd)

    # add tap device to namespace
    cmd = ["sudo", "ip", "link", "set", dev, "netns", ns]
    execute_command(cmd)

    namespace = ["sudo", "ip", "netns", "exec", ns]
    cmd = namespace + ["ip", "link", "set", dev, "up"]
    execute_command(cmd)

    cmd = namespace + ["ip", "link", "set", dev, "address", mac_address]
    execute_command(cmd)

    if mtu:
        cmd = namespace + ["ip", "link", "set", "dev", dev, "mtu", "%s" % mtu]
        execute_command(cmd)

    for address in ip_addresses:
        cmd = ["sudo", "ip", "netns", "exec", ns,
               "ip", "addr", "add", address, "dev", dev]
        execute_command(cmd)

    cmd = namespace + ["ip", "route", "add", "default"]
    cmd = cmd + ["via", gateway, "dev", dev]
    execute_command(cmd)


def delete_port(ns, brint, dev):
    vet = "vet" + str(dev[3:14])
    qbr = "qbr" + str(dev[3:14])
    qvb = "qvb" + str(dev[3:14])
    qvo = "qvo" + str(dev[3:14])

    # delete qvo-qvb veth pair
    cmd = ["sudo", "ovs-vsctl", "--if-exists", "del-port", brint, qvo]
    execute_command(cmd)

    cmd = ["sudo", "ip", "link", "set", qvb, "nomaster"]
    execute_command(cmd)

    cmd = ["sudo", "ip", "link", "delete", qvb]
    execute_command(cmd)

    # delete bridge (tap port will be deleted along with namespace deletion)
    cmd = ["sudo", "ip", "link", "set", vet, "nomaster"]
    execute_command(cmd)

    cmd = ["sudo", "ip", "link", "delete", qbr]
    execute_command(cmd)

def get_mtu(vif):
    network = vif.get("network", {})
    if network.get("meta") and network["meta"].get("mtu"):
        return network["meta"]["mtu"]
    else:
        return None


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
    mtu = get_mtu(vif)
    add_port(ns, bridge, dev, port, mac_address, ip_addresses, gateway, mtu)


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
