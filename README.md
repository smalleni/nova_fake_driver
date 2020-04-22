# nova_fake_driver

This fake nova driver creates 

1) a network namespace instead of VMs
2) then creates VMs ports in these name spaces.


Goal is when the rally scenario creates VMs and ping their IP,

it should get a ping reply from these namespace ports.

This helps testing network functionality i.e neutron drivers

(ML2/OVS and OVN) without spawning a real VM.
