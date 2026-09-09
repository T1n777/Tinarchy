import unittest
import queue
import json
from tinarchy import config, telemetry, services, auth, syncthing, reports
from tinarchy.sse import SSEBroker

class TestModularCore(unittest.TestCase):

    def test_config(self):
        cfg = config.get_app_config()
        self.assertIn('hostname', cfg)
        self.assertIn('display_name', cfg)
        self.assertIn('project_name', cfg)
        self.assertTrue(len(cfg['hostname']) > 0)

    def test_telemetry(self):
        ram = telemetry.get_ram_stats()
        self.assertIn('ram_used_mb', ram)
        self.assertIn('ram_total_mb', ram)
        self.assertIn('ram_percent', ram)
        self.assertGreater(ram['ram_total_mb'], 0)

        cpu = telemetry.get_cpu_percent()
        self.assertIsInstance(cpu, float)
        self.assertTrue(0.0 <= cpu <= 100.0)

        snapshot = telemetry.collect_full_system_snapshot()
        self.assertIn('ram_used_mb', snapshot)
        self.assertIn('disk_used', snapshot)
        self.assertIn('cpu_percent', snapshot)
        self.assertIn('net_rx_speed', snapshot)
        self.assertIn('uptime', snapshot)

    def test_auth(self):
        roles_cfg = auth.get_roles_config()
        self.assertIn('roles', roles_cfg)
        self.assertIn('admin_accounts', roles_cfg)

        owner_role = auth.get_user_role("test_random_user")
        self.assertIn(owner_role, ['viewer', 'admin', 'owner'])

        all_svcs = auth.get_user_allowed_services("test_random_user", role="owner")
        self.assertIsInstance(all_svcs, list)
        self.assertIn('suwayomi', all_svcs)

    def test_services(self):
        all_ids = services.get_all_service_ids()
        self.assertIn('suwayomi', all_ids)
        self.assertIn('tailscale-ssh', all_ids)

        svcs_status = services.get_services_status()
        self.assertIsInstance(svcs_status, list)
        self.assertTrue(len(svcs_status) >= 3)
        for s in svcs_status:
            self.assertIn('id', s)
            self.assertIn('status', s)
            self.assertIn(s['status'], ['online', 'offline', 'unknown'])

    def test_sse_broker(self):
        broker = SSEBroker(interval=1.0)
        self.assertEqual(broker.client_count(), 0)

        q1 = broker.subscribe()
        self.assertEqual(broker.client_count(), 1)
        self.assertIsInstance(q1, queue.Queue)

        test_payload = {"cpu": 15.2, "ram": 2048}
        broker.broadcast("telemetry", test_payload)

        raw_msg = q1.get_nowait()
        self.assertTrue(raw_msg.startswith(b"event: telemetry\n"))
        self.assertIn(b'"cpu": 15.2', raw_msg)

        broker.unsubscribe(q1)
        self.assertEqual(broker.client_count(), 0)
        broker.stop()

    def test_reports(self):
        rep = reports.generate_daily_system_report()
        self.assertIn('hostname', rep)
        self.assertIn('markdown_report', rep)
        self.assertIn('governor', rep)
        self.assertIn('battery', rep)
        self.assertIn('services', rep)

if __name__ == '__main__':
    unittest.main()
