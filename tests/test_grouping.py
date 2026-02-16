import unittest

from modules.dna_automanage import enforce_unique_ips_across_iplists, group_key_for_fqdn


class TestGroupingRules(unittest.TestCase):
    def test_sgmonitoring_grouped_by_env(self):
        self.assertEqual(
            group_key_for_fqdn("0c60359b1d9f40cd84bf7add3a6b4bf7.ece.sgmonitoring.dev.euw.gbis.sg-azure.com"),
            "sgmonitoring.dev",
        )
        self.assertEqual(
            group_key_for_fqdn("1682f82444010702bb8f5584609300ea.ece.sgmonitoring.prd.euw.gbis.sg-azure.com"),
            "sgmonitoring.prd",
        )

    def test_kafka_grouped_by_env(self):
        self.assertEqual(
            group_key_for_fqdn("kfkdev-1-fed.fed.kafka.dev.euw.gbis.sg-azure.com"),
            "kafka.dev",
        )
        self.assertEqual(
            group_key_for_fqdn("kfkprd-6-fed.fed.kafka.prd.euw.gbis.sg-azure.com"),
            "kafka.prd",
        )

    def test_api_split_by_second_label(self):
        self.assertEqual(group_key_for_fqdn("api.account.cloud.socgen"), "api.account")
        self.assertEqual(group_key_for_fqdn("api.group.socgen"), "api.group")
        self.assertEqual(group_key_for_fqdn("api.intra.transactis.fr"), "api.intra")
        self.assertEqual(group_key_for_fqdn("api.sgdocs.prd.euw.gbis.sg-azure.com"), "api.sgdocs")

    def test_api_slb_grouped_together(self):
        self.assertEqual(group_key_for_fqdn("api.slb.eu-fr-north.cloud.socgen"), "api.slb")
        self.assertEqual(group_key_for_fqdn("api.slb.eu-fr-paris.cloud.socgen"), "api.slb")
        self.assertEqual(group_key_for_fqdn("api.slb.hk-hongkong.cloud.socgen"), "api.slb")
        self.assertEqual(group_key_for_fqdn("api.slb.sg-singapore.cloud.socgen"), "api.slb")


class TestUniqueIpOwnership(unittest.TestCase):
    def test_existing_owner_is_preserved(self):
        desired = {
            "DNA_alpha-IPL": {"ips": {"184.5.2.10", "10.0.0.1"}, "fqdns": {"alpha.example"}},
            "DNA_beta-IPL": {"ips": {"184.5.2.10"}, "fqdns": {"beta.example"}},
        }

        result, reassigned = enforce_unique_ips_across_iplists(desired, {"184.5.2.10": "DNA_beta-IPL"})

        self.assertEqual(result["DNA_beta-IPL"]["ips"], {"184.5.2.10"})
        self.assertEqual(result["DNA_alpha-IPL"]["ips"], {"10.0.0.1"})
        self.assertEqual(reassigned, [{"ip": "184.5.2.10", "owner": "DNA_beta-IPL", "removed_from": "DNA_alpha-IPL"}])

    def test_fallback_is_deterministic_with_env_and_name(self):
        desired = {
            "DNA_service-dev-IPL": {"ips": {"192.168.1.1"}, "fqdns": {"svc1.dev.example"}},
            "DNA_service-prd-IPL": {"ips": {"192.168.1.1"}, "fqdns": {"svc1.prd.example"}},
            "DNA_service-uat-IPL": {"ips": {"192.168.1.1"}, "fqdns": {"svc1.uat.example"}},
        }

        result, reassigned = enforce_unique_ips_across_iplists(desired, {})

        self.assertEqual(result["DNA_service-prd-IPL"]["ips"], {"192.168.1.1"})
        self.assertEqual(result["DNA_service-dev-IPL"]["ips"], set())
        self.assertEqual(result["DNA_service-uat-IPL"]["ips"], set())
        self.assertEqual(
            reassigned,
            [
                {"ip": "192.168.1.1", "owner": "DNA_service-prd-IPL", "removed_from": "DNA_service-dev-IPL"},
                {"ip": "192.168.1.1", "owner": "DNA_service-prd-IPL", "removed_from": "DNA_service-uat-IPL"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
