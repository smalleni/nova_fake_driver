# nova_fake_driver

Goal of this driver is to test rally scenarios without libvirt driver but
with network functionality. For this, nova fake driver should simulate VMs
with network namespaces and ports. When the rally scenario creates VMs and
ping their IP, it should get a ping reply from these namespace ports.
This helps testing network functionality i.e neutron drivers (ML2/OVS and OVN)
without spawning a real VM.

This nova fake driver works in client server model. Here nova driver (fake) is
the client which runs in container (in OSP) inside the compute and
fake_vif_wsgi_server.py is the server which runs on the compute node host.

Changes in nova_compute container in compute node
1) copy fake_vif.py driver to nova python modules
   cp /var/log/nova/fake_vif.py /usr/lib/python3.6/site-packages/nova/virt/
2) installed needed pip packages
   pip3 install fixtures httplib2

Changes in compute node host
1) set fake driver i.e
   compute_driver=fake_vif.OVSFakeDriver
   in /var/lib/config-data/puppet-generated/nova_libvirt/etc/nova/nova.conf
2) stop nova_compute container so that it will stop binding to server socket
   docker stop nova_compute
2) run the server as a background process
   python fake_vif_wsgi_server.py & 
3) start nova_compute container
   docker start nova_compute 

Server (fake_vif_wsgi_server.py) will listen on unix socket[1] for the requests
from the client (i.e nova fake driver which is inside nova_compute container).
When the client requests for adding or deleting namespace or ports,
it does that through "ip netns" command (and adding OVS port to br-int)
on the compute node host. 

Nova fake driver (fake_vif.py) which is in nova_compute container inside compute node,
will send request to fake_vif_wsgi_server.py using unix socket during vif_plug
for creating network namespace and ports when it gets a request to spawn a new VM.

Challenges encountered with alternative approaches i.e nova fake driver
directly adding namespaces and ports inside container are documented in [2]

[1] /var/log/containers/nova/fake_driver_netns.sock 
[2] "alternatives" file in this repo
