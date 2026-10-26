import json
import subprocess
from unittest import mock

import click
import pytest
from click.testing import CliRunner

from oasees_sdk.cli.commands import topology as topo


def test_between_sets_both_directions_and_from_to_one():
    t = topo.load_topology({
        "nodes": {"n1": {"tier": "far-edge", "zone": "line-a"}, "n0": {"tier": "cloud"}},
        "links": [{"between": ["n1", "n0"], "delay_ms": 40, "rate_mbit": 10},
                  {"from": "n2", "to": "n0", "delay_ms": 5, "loss_pct": 1}]})
    links = {(l["from"], l["to"]): l for l in t["links"]}
    assert set(links) == {("n1", "n0"), ("n0", "n1"), ("n2", "n0")}
    assert links[("n0", "n1")]["delay_ms"] == 40 and links[("n0", "n1")]["rate_mbit"] == 10
    assert t["nodes"]["n1"] == {topo.TIER_LABEL: "far-edge", topo.ZONE_LABEL: "line-a"}


def test_a_later_link_overrides_an_earlier_one_for_that_direction():
    t = topo.load_topology({"links": [{"between": ["a", "b"], "delay_ms": 10},
                                      {"from": "a", "to": "b", "delay_ms": 99}]})
    links = {(l["from"], l["to"]): l["delay_ms"] for l in t["links"]}
    assert links == {("a", "b"): 99, ("b", "a"): 10}


@pytest.mark.parametrize("bad, message", [
    ({"links": [{"between": ["a", "b"]}]}, "sets none of"),
    ({"links": [{"between": ["a", "a"], "delay_ms": 1}]}, "two different nodes"),
    ({"links": [{"from": "a", "delay_ms": 1}]}, "needs 'between"),
    ({"links": [{"from": "a", "to": "b", "loss_pct": 120}]}, "between 0 and 100"),
])
def test_invalid_topologies_are_rejected(bad, message):
    with pytest.raises(click.ClickException, match=message):
        topo.load_topology(bad)


def test_netem_script_only_touches_traffic_to_listed_peers():
    params = {"delay_ms": 80, "jitter_ms": 10, "loss_pct": 1.5, "rate_mbit": 10}
    script = topo.netem_script("10.0.0.1", [("10.0.0.2", params), ("10.0.0.3", {**params, "jitter_ms": 0, "loss_pct": 0})])
    assert "prio bands 3 priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0" in script     # default traffic -> band 1:1
    assert "parent 1:2 handle 20: netem delay 80ms 10ms loss 1.5% rate 10mbit" in script
    assert "parent 1:3 handle 30: netem delay 80ms rate 10mbit" in script
    assert "match ip dst 10.0.0.2/32 flowid 1:2" in script and "match ip dst 10.0.0.3/32 flowid 1:3" in script
    assert "root netem" not in script                                            # never the whole interface


def test_netem_script_without_rules_just_clears():
    script = topo.netem_script("10.0.0.1", [])
    assert "tc qdisc del dev $IF root" in script and "tc qdisc add" not in script


def test_parse_ping_reads_averages_and_total_loss():
    out = ("PING 10.0.0.2\n5 packets transmitted, 5 received, 0% packet loss, time 800ms\n"
           "rtt min/avg/max/mdev = 80.1/81.4/83.0/1.0 ms\n"
           "PING 10.0.0.3\n5 packets transmitted, 0 received, 100% packet loss, time 4000ms\n")
    assert topo.parse_ping(out) == {"10.0.0.2": 81.4, "10.0.0.3": None}


NODES = json.dumps({"items": [
    {"metadata": {"name": n}, "status": {"addresses": [{"type": "InternalIP", "address": ip}]}}
    for n, ip in (("n0", "10.0.0.1"), ("n1", "10.0.0.2"), ("n2", "10.0.0.3"))]})


def _kubectl():
    """Fake kubectl: knows the nodes, records applied pods, says every pod succeeded."""
    calls = {"pods": [], "labels": [], "configmaps": []}

    def run(cmd, input=None, **kw):
        out = ""
        if cmd[:3] == ["kubectl", "get", "nodes"]:
            out = NODES
        elif cmd[:2] == ["kubectl", "apply"]:
            obj = json.loads(input)
            calls["pods" if obj["kind"] == "Pod" else "configmaps"].append(obj)
        elif cmd[:2] == ["kubectl", "label"]:
            calls["labels"].append(cmd)
        elif cmd[:3] == ["kubectl", "get", "pod"]:
            out = "Succeeded"
        elif cmd[:2] == ["kubectl", "logs"]:
            out = "interface eth0"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    return run, calls


def test_apply_runs_one_privileged_host_network_pod_per_node(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text("nodes: {n1: {tier: far-edge}}\nlinks:\n- {between: [n1, n0], delay_ms: 50}\n")
    run, calls = _kubectl()
    with mock.patch.object(topo.subprocess, "run", run), mock.patch.object(topo.time, "sleep"):
        result = CliRunner().invoke(topo.topology_commands, ["apply", "-f", str(f)])
    assert result.exit_code == 0, result.output
    pods = {p["spec"]["nodeName"]: p for p in calls["pods"]}
    assert set(pods) == {"n0", "n1", "n2"}                     # n2 has no links: it gets cleared
    spec = pods["n1"]["spec"]
    assert spec["hostNetwork"] and spec["containers"][0]["securityContext"]["capabilities"]["add"] == ["NET_ADMIN"]
    assert "match ip dst 10.0.0.1/32" in spec["containers"][0]["command"][2]
    assert "tc qdisc add" not in pods["n2"]["spec"]["containers"][0]["command"][2]
    assert calls["labels"] == [["kubectl", "label", "node", "n1", "--overwrite", f"{topo.TIER_LABEL}=far-edge"]]
    assert json.loads(calls["configmaps"][0]["data"]["topology.json"])["links"]


def test_apply_rejects_nodes_that_are_not_in_the_cluster(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text("links:\n- {between: [n1, ghost], delay_ms: 50}\n")
    run, calls = _kubectl()
    with mock.patch.object(topo.subprocess, "run", run):
        result = CliRunner().invoke(topo.topology_commands, ["apply", "-f", str(f)])
    assert result.exit_code != 0 and "Not cluster nodes: ghost" in result.output and not calls["pods"]
