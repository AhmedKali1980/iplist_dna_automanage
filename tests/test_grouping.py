import unittest

from modules.dna_automanage import group_key_for_fqdn, regroup_by_exact_ips_with_bridge_fqdn


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


class TestRegroupByExactIps(unittest.TestCase):
    def test_shared_ip_candidates_are_merged_into_one_iplist(self):
        desired = {
            "DNA_pkumar2-IPL": {"ips": {"184.5.2.10"}, "fqdns": {"pkumar2.fr.world.socgen"}},
            "DNA_sawasthi-IPL": {"ips": {"184.5.2.10"}, "fqdns": {"sawasthi.fr.world.socgen"}},
            "DNA_sbreux-IPL": {"ips": {"184.5.2.10"}, "fqdns": {"sbreux.fr.world.socgen"}},
        }

        regrouped, events = regroup_by_exact_ips_with_bridge_fqdn(desired)

        self.assertEqual(set(regrouped.keys()), {"DNA_pkumar2-IPL"})
        self.assertEqual(regrouped["DNA_pkumar2-IPL"]["ips"], {"184.5.2.10"})
        self.assertEqual(
            regrouped["DNA_pkumar2-IPL"]["fqdns"],
            {"pkumar2.fr.world.socgen", "sawasthi.fr.world.socgen", "sbreux.fr.world.socgen"},
        )
        self.assertEqual(len(events), 1)

    def test_bridge_fqdn_is_used_for_target_name(self):
        desired = {
            "groupA": {"ips": {"10.1.1.1", "10.1.1.2"}, "fqdns": {"zzz.example", "aaa.example"}},
            "groupB": {"ips": {"10.1.1.1", "10.1.1.2"}, "fqdns": {"bbb.example"}},
        }

        regrouped, events = regroup_by_exact_ips_with_bridge_fqdn(desired)

        self.assertEqual(set(regrouped.keys()), {"DNA_aaa-IPL"})
        self.assertEqual(regrouped["DNA_aaa-IPL"]["ips"], {"10.1.1.1", "10.1.1.2"})
        self.assertEqual(events[0]["bridge_fqdn"], "aaa.example")

    def test_empty_ip_groups_are_ignored(self):
        desired = {
            "groupA": {"ips": set(), "fqdns": {"empty.example"}},
        }

        regrouped, events = regroup_by_exact_ips_with_bridge_fqdn(desired)

        self.assertEqual(regrouped, {})
        self.assertEqual(events, [])



if __name__ == "__main__":
    unittest.main()
