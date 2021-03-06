#    Copyright 2015 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import logging
import os
import time

import pytest

from mos_tests.functions.base import OpenStackTestCase
from mos_tests.functions import common as common_functions

logger = logging.getLogger(__name__)


@pytest.mark.undestructive
class WindowCompatibilityIntegrationTests(OpenStackTestCase):
    """Basic automated tests for OpenStack Windows Compatibility verification.
    """

    def setUp(self):
        super(self.__class__, self).setUp()

        # Get path on node to 'templates' dir
        self.templates_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'templates')
        # Get path on node to 'images' dir
        self.images_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'images')

        self.uid_list = []

        # timeouts (in minutes)
        self.ping_timeout = 3
        self.hypervisor_timeout = 10

        self.amount_of_images_before = len(list(self.glance.images.list()))
        self.image = None
        self.our_own_flavor_was_created = False
        self.expected_flavor_id = 3
        self.node_to_boot = None
        self.security_group_name = "ms_compatibility"
        # protect for multiple definition of the same group
        for sg in self.nova.security_groups.list():
            if sg.name == self.security_group_name:
                self.nova.security_groups.delete(sg)
        # adding required security group
        self.the_security_group = self.nova.security_groups.create(
            name=self.security_group_name,
            description="Windows Compatibility")
        # Add rules for ICMP, TCP/22
        self.icmp_rule = self.nova.security_group_rules.create(
            self.the_security_group.id,
            ip_protocol="icmp",
            from_port=-1,
            to_port=-1,
            cidr="0.0.0.0/0")
        self.tcp_rule = self.nova.security_group_rules.create(
            self.the_security_group.id,
            ip_protocol="tcp",
            from_port=22,
            to_port=22,
            cidr="0.0.0.0/0")
        # Add both rules to default group
        self.default_security_group_id = 0
        for sg in self.nova.security_groups.list():
            if sg.name == 'default':
                self.default_security_group_id = sg.id
                break
        self.icmp_rule_default = self.nova.security_group_rules.create(
            self.default_security_group_id,
            ip_protocol="icmp",
            from_port=-1,
            to_port=-1,
            cidr="0.0.0.0/0")
        self.tcp_rule_default = self.nova.security_group_rules.create(
            self.default_security_group_id,
            ip_protocol="tcp",
            from_port=22,
            to_port=22,
            cidr="0.0.0.0/0")
        # adding floating ip
        self.floating_ip = self.nova.floating_ips.create(
            self.nova.floating_ip_pools.list()[0].name)

        # creating of the image
        self.image = self.glance.images.create(
            name='MyTestSystem',
            disk_format='qcow2',
            container_format='bare')
        self.glance.images.upload(
            self.image.id,
            open('/tmp/trusty-server-cloudimg-amd64-disk1.img', 'rb'))
        # check that required image in active state
        is_activated = False
        while not is_activated:
            for image_object in self.glance.images.list():
                if image_object.id == self.image.id:
                    self.image = image_object
                    logger.info(
                        "Image in the {} state".format(self.image.status))
                    if self.image.status == 'active':
                        is_activated = True
                        break
            time.sleep(1)

        # Default - the first
        network_id = self.nova.networks.list()[0].id
        # More detailed check of network list
        for network in self.nova.networks.list():
            if 'internal' in network.label:
                network_id = network.id
        logger.info("Starting with network interface id {}".format(network_id))

        # TODO(mlaptev) add check flavor parameters vs. vm parameters
        # Collect information about the medium flavor and create a copy of it
        for flavor in self.nova.flavors.list():
            if 'medium' in flavor.name and 'copy.of.' not in flavor.name:
                new_flavor_name = "copy.of." + flavor.name
                new_flavor_id = common_functions.get_flavor_id_by_name(
                    self.nova,
                    new_flavor_name)
                # delete the flavor if it already exists
                if new_flavor_id is not None:
                    common_functions.delete_flavor(self.nova, new_flavor_id)
                # create the flavor for our needs
                expected_flavor = self.nova.flavors.create(
                    name=new_flavor_name,
                    ram=flavor.ram,
                    vcpus=1,  # Only one VCPU
                    disk=flavor.disk)
                self.expected_flavor_id = expected_flavor.id
                self.our_own_flavor_was_created = True
                break
        logger.info("Starting with flavor {}".format(
            self.nova.flavors.get(self.expected_flavor_id)))
        # nova boot
        self.node_to_boot = common_functions.create_instance(
            nova_client=self.nova,
            inst_name="MyTestSystemWithNova",
            flavor_id=self.expected_flavor_id,
            net_id=network_id,
            security_groups=[self.the_security_group.name, 'default'],
            image_id=self.image.id)
        # check that boot returns expected results
        self.assertEqual(self.node_to_boot.status, 'ACTIVE',
                         "The node not in active state!")

        logger.info("Using following floating ip {}".format(
            self.floating_ip.ip))

        self.node_to_boot.add_floating_ip(self.floating_ip)

        self.assertTrue(common_functions.check_ip(self.nova,
                                                  self.node_to_boot.id,
                                                  self.floating_ip.ip))

    def tearDown(self):
        if self.node_to_boot is not None:
            common_functions.delete_instance(self.nova, self.node_to_boot.id)
        if self.image is not None:
            common_functions.delete_image(self.glance, self.image.id)
        if self.our_own_flavor_was_created:
            common_functions.delete_flavor(self.nova, self.expected_flavor_id)
        # delete the floating ip
        self.nova.floating_ips.delete(self.floating_ip)
        # delete the security group
        self.nova.security_group_rules.delete(self.icmp_rule)
        self.nova.security_group_rules.delete(self.tcp_rule)
        self.nova.security_groups.delete(self.the_security_group.id)
        # delete security rules from the 'default' group
        self.nova.security_group_rules.delete(self.icmp_rule_default)
        self.nova.security_group_rules.delete(self.tcp_rule_default)
        self.assertEqual(self.amount_of_images_before,
                         len(list(self.glance.images.list())),
                         "Length of list with images should be the same")

    @pytest.mark.testrail_id('634680')
    def test_create_instance_with_windows_image(self):
        """This test checks that instance with Windows image could be created

        Steps:
        1. Upload Windows 2012 Server image to Glance
        2. Create VM with this Windows image
        3. Assign floating IP to this VM
        4. Ping this VM and verify that we can ping it
        :return: Nothing
        """
        ping_result = common_functions.ping_command(self.floating_ip.ip)
        self.assertTrue(ping_result, "Instance is not reachable")

    @pytest.mark.testrail_id('634681')
    def test_pause_and_unpause_instance_with_windows_image(self):
        """This test checks that instance with Windows image could be paused
        and unpaused

        Steps:
        1. Upload Windows 2012 Server image to Glance
        2. Create VM with this Windows image
        3. Assign floating IP to this VM
        4. Ping this VM and verify that we can ping it
        5. Pause this VM
        6. Verify that we can't ping it
        7. Unpause it and verify that we can ping it again
        8. Reboot VM
        9. Verify that we can ping this VM after reboot.
        :return: Nothing
        """
        # Initial check
        ping_result = common_functions.ping_command(self.floating_ip.ip)
        self.assertTrue(ping_result, "Instance is not reachable")
        # Paused state check
        self.node_to_boot.pause()
        # Make sure that the VM in 'Paused' state
        ping_result = common_functions.ping_command(self.floating_ip.ip,
                                                    should_be_available=False)
        self.assertTrue(ping_result, "Instance is reachable")
        # Unpaused state check
        self.node_to_boot.unpause()
        # Make sure that the VM in 'Unpaused' state
        ping_result = common_functions.ping_command(self.floating_ip.ip)
        self.assertTrue(ping_result, "Instance is not reachable")
        # Reboot the VM and make sure that we can ping it
        self.node_to_boot.reboot(reboot_type='HARD')
        instance_status = common_functions.check_inst_status(
            self.nova,
            self.node_to_boot.id,
            'ACTIVE')
        self.node_to_boot = [s for s in self.nova.servers.list()
                             if s.id == self.node_to_boot.id][0]
        if not instance_status:
            raise AssertionError(
                "Instance status is '{0}' instead of 'ACTIVE".format(
                    self.node_to_boot.status))

        # Waiting for up-and-run of Virtual Machine after reboot
        ping_result = common_functions.ping_command(self.floating_ip.ip)
        self.assertTrue(ping_result, "Instance is not reachable")

    @pytest.mark.testrail_id('638381')
    def test_suspend_and_resume_instance_with_windows_image(self):
        """This test checks that instance with Windows image can be suspended
        and resumed

        Steps:
        1. Upload Windows 2012 Server image to Glance
        2. Create VM with this Windows image
        3. Assign floating IP to this VM
        4. Ping this VM and verify that we can ping it
        5. Suspend VM
        6. Verify that we can't ping it
        7. Resume and verify that we can ping it again.
        8. Reboot VM
        9. Verify that we can ping this VM after reboot.
        :return: Nothing
        """
        # Initial check
        ping_result = common_functions.ping_command(self.floating_ip.ip)
        self.assertTrue(ping_result, "Instance is not reachable")
        # Suspend state check
        self.node_to_boot.suspend()
        # Make sure that the VM in 'Suspended' state
        ping_result = common_functions.ping_command(
            self.floating_ip.ip,
            should_be_available=False
        )
        self.assertTrue(ping_result, "Instance is reachable")
        # Resume state check
        self.node_to_boot.resume()
        # Make sure that the VM in 'Resume' state
        ping_result = common_functions.ping_command(self.floating_ip.ip)
        self.assertTrue(ping_result, "Instance is not reachable")
        # Reboot the VM and make sure that we can ping it
        self.node_to_boot.reboot(reboot_type='HARD')
        instance_status = common_functions.check_inst_status(
            self.nova,
            self.node_to_boot.id,
            'ACTIVE')
        self.node_to_boot = [s for s in self.nova.servers.list()
                             if s.id == self.node_to_boot.id][0]
        if not instance_status:
            raise AssertionError(
                "Instance status is '{0}' instead of 'ACTIVE".format(
                    self.node_to_boot.status))

        # Waiting for up-and-run of Virtual Machine after reboot
        ping_result = common_functions.ping_command(self.floating_ip.ip)
        self.assertTrue(ping_result, "Instance is not reachable")

    @pytest.mark.testrail_id('634682')
    def test_live_migration_for_windows_instance(self):
        """This test checks that instance with Windows Image could be
        migrated without any issues

        Steps:
        1. Upload Windows 2012 Server image to Glance
        2. Create VM with this Windows image
        3. Assign floating IP to this VM
        4. Ping this VM and verify that we can ping it
        5. Migrate this VM to another compute node
        6. Verify that live Migration works fine for Windows VMs
        and we can successfully ping this VM
        7. Reboot VM and verify that
        we can successfully ping this VM after reboot.

        :return: Nothing
        """
        # 1. 2. 3. -> Into setUp function
        # 4. Ping this VM and verify that we can ping it
        hypervisor_hostname_attribute = "OS-EXT-SRV-ATTR:hypervisor_hostname"
        ping_result = common_functions.ping_command(self.floating_ip.ip)
        self.assertTrue(ping_result, "Instance is not reachable")
        hypervisors = {h.hypervisor_hostname: h for h
                       in self.nova.hypervisors.list()}
        old_hyper = getattr(self.node_to_boot,
                            hypervisor_hostname_attribute)
        logger.info("Old hypervisor is: {}".format(old_hyper))
        new_hyper = [h for h in hypervisors.keys() if h != old_hyper][0]
        logger.info("New hypervisor is: {}".format(new_hyper))
        # Execute the live migrate
        self.node_to_boot.live_migrate(new_hyper)

        self.node_to_boot = self.nova.servers.get(self.node_to_boot.id)
        end_time = time.time() + 60 * self.hypervisor_timeout
        debug_string = "Waiting for changes."
        is_timeout = False
        while getattr(self.node_to_boot,
                      hypervisor_hostname_attribute) != new_hyper:
            if time.time() > end_time:
                is_timeout = True
            time.sleep(30)
            debug_string += "."
            self.node_to_boot = self.nova.servers.get(self.node_to_boot.id)
        logger.info(debug_string)
        if is_timeout:
            raise AssertionError(
                "Hypervisor is not changed after live migration")
        self.assertEqual(self.node_to_boot.status, 'ACTIVE')
        # Ping the Virtual Machine
        ping_result = common_functions.ping_command(self.floating_ip.ip)
        self.assertTrue(ping_result, "Instance is not reachable")
        # Reboot the VM and make sure that we can ping it
        self.node_to_boot.reboot(reboot_type='HARD')
        instance_status = common_functions.check_inst_status(
            self.nova,
            self.node_to_boot.id,
            'ACTIVE')
        self.node_to_boot = [s for s in self.nova.servers.list()
                             if s.id == self.node_to_boot.id][0]
        if not instance_status:
            raise AssertionError(
                "Instance status is '{0}' instead of 'ACTIVE".format(
                    self.node_to_boot.status))

        # Waiting for up-and-run of Virtual Machine after reboot
        ping_result = common_functions.ping_command(self.floating_ip.ip)
        self.assertTrue(ping_result, "Instance is not reachable")
