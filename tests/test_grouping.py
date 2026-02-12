import unittest

from modules.dna_automanage import group_key_for_fqdn


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


if __name__ == "__main__":
    unittest.main()
