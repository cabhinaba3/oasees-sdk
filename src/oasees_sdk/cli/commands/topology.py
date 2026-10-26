import json
import os
import re
import subprocess
import time

import click
import yaml

# Image with tc and ping that runs on each node to set up or measure the links.
NETEM_IMAGE = os.environ.get("OASEES_NETEM_IMAGE", "nicolaka/netshoot:v0.13")
TIER_LABEL = "topology.oasees.io/tier"
ZONE_LABEL = "topology.oasees.io/zone"
STATE_CONFIGMAP = "oasees-topology"


@click.group(name='topology')
def topology_commands():
    '''Network topology between the cluster nodes (delay, loss, bandwidth)'''
    pass


def load_topology(source):
    """Read topology.yaml (path or dict). Returns {"nodes": {name: labels}, "links": [link dicts]}.

    A link is `between: [a, b]` (both directions) or `from: a` / `to: b` (one direction), with any of
    delay_ms, jitter_ms, loss_pct, rate_mbit. Later links override earlier ones for the same direction."""
    if isinstance(source, dict):
        data = source
    else:
        with open(source) as f:
            data = yaml.safe_load(f) or {}

    nodes = {}
    for name, info in (data.get("nodes") or {}).items():
        info = info or {}
        labels = {}
        if info.get("tier"):
            labels[TIER_LABEL] = str(info["tier"])
        if info.get("zone"):
            labels[ZONE_LABEL] = str(info["zone"])
        nodes[name] = labels

    links = {}
    for i, raw in enumerate(data.get("links") or []):
        params = {k: float(raw.get(k, 0)) for k in ("delay_ms", "jitter_ms", "loss_pct", "rate_mbit")}
        if not any(params.values()):
            raise click.ClickException(f"Link {i + 1} sets none of delay_ms, jitter_ms, loss_pct, rate_mbit")
        if not 0 <= params["loss_pct"] <= 100:
            raise click.ClickException(f"Link {i + 1}: loss_pct must be between 0 and 100")
        if "between" in raw:
            pair = raw["between"]
            if not isinstance(pair, list) or len(pair) != 2 or pair[0] == pair[1]:
                raise click.ClickException(f"Link {i + 1}: 'between' needs two different nodes")
            directions = [(pair[0], pair[1]), (pair[1], pair[0])]
        elif "from" in raw and "to" in raw:
            if raw["from"] == raw["to"]:
                raise click.ClickException(f"Link {i + 1}: 'from' and 'to' are the same node")
            directions = [(raw["from"], raw["to"])]
        else:
            raise click.ClickException(f"Link {i + 1} needs 'between: [a, b]' or 'from' and 'to'")
        for src, dst in directions:
            links[(str(src), str(dst))] = params

    return {"nodes": nodes,
            "links": [{"from": s, "to": d, **p} for (s, d), p in links.items()]}


def netem_script(node_ip, rules):
    """Shell for one node: impair traffic to each destination IP in rules [(ip, params)].

    Only traffic to those IPs is touched (each gets its own band in a prio qdisc); everything else,
    including SSH, goes through band 1:1 unchanged. With no rules it just removes earlier ones."""
    find_iface = (f"IF=$(ip -o -4 addr show | awk '$4 ~ \"^{node_ip}/\" {{print $2; exit}}'); "
                  f"[ -n \"$IF\" ] || {{ echo 'no interface has {node_ip}'; exit 1; }}; ")
    lines = ["tc qdisc del dev $IF root 2>/dev/null || true"]
    if rules:
        if len(rules) > 15:
            raise click.ClickException("At most 15 impaired destinations per node")
        lines.append(f"tc qdisc add dev $IF root handle 1: prio bands {len(rules) + 1} priomap {' '.join(['0'] * 16)}")
        for band, (ip, p) in enumerate(rules, start=2):
            netem = "netem"
            if p["delay_ms"] or p["jitter_ms"]:
                netem += f" delay {p['delay_ms']:g}ms" + (f" {p['jitter_ms']:g}ms" if p["jitter_ms"] else "")
            if p["loss_pct"]:
                netem += f" loss {p['loss_pct']:g}%"
            if p["rate_mbit"]:
                netem += f" rate {p['rate_mbit']:g}mbit"
            lines.append(f"tc qdisc add dev $IF parent 1:{band} handle {band}0: {netem}")
            lines.append(f"tc filter add dev $IF parent 1: protocol ip prio 1 u32 match ip dst {ip}/32 flowid 1:{band}")
    lines.append("echo \"interface $IF\"; tc qdisc show dev $IF")
    return "set -e; " + find_iface + "; ".join(lines)


def node_addresses():
    """{node name: InternalIP} for every node in the cluster."""
    result = subprocess.run(["kubectl", "get", "nodes", "-o", "json"], capture_output=True, text=True)
    if result.returncode != 0:
        raise click.ClickException(f"Could not list the cluster nodes: {result.stderr.strip()}")
    addresses = {}
    for item in json.loads(result.stdout)["items"]:
        for a in item["status"].get("addresses", []):
            if a["type"] == "InternalIP":
                addresses[item["metadata"]["name"]] = a["address"]
    return addresses


def _pod_name(prefix, node):
    return f"{prefix}-{re.sub(r'[^a-z0-9-]', '-', node.lower())}"[:63].rstrip("-")


def run_on_nodes(prefix, scripts, timeout=180):
    """Run one shell script per node {node: script} in a short-lived privileged pod on the host
    network. Returns {node: (succeeded, output)}."""
    pods = {node: _pod_name(prefix, node) for node in scripts}
    for node, script in scripts.items():
        manifest = {
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": pods[node], "labels": {"app": "oasees-topology"}},
            "spec": {"nodeName": node, "hostNetwork": True, "restartPolicy": "Never",
                     "tolerations": [{"operator": "Exists"}],
                     "containers": [{"name": "net", "image": NETEM_IMAGE, "command": ["sh", "-c", script],
                                     "securityContext": {"capabilities": {"add": ["NET_ADMIN"]}}}]}}
        subprocess.run(["kubectl", "delete", "pod", pods[node], "--ignore-not-found", "--wait=true"],
                       capture_output=True, text=True)
        applied = subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(manifest),
                                 capture_output=True, text=True)
        if applied.returncode != 0:
            raise click.ClickException(f"Could not start the pod on {node}: {applied.stderr.strip()}")

    results, deadline = {}, time.time() + timeout
    while len(results) < len(pods) and time.time() < deadline:
        for node, pod in pods.items():
            if node in results:
                continue
            phase = subprocess.run(["kubectl", "get", "pod", pod, "-o", "jsonpath={.status.phase}"],
                                   capture_output=True, text=True).stdout.strip()
            if phase in ("Succeeded", "Failed"):
                logs = subprocess.run(["kubectl", "logs", pod], capture_output=True, text=True).stdout
                results[node] = (phase == "Succeeded", logs.strip())
        time.sleep(2)
    for node, pod in pods.items():
        results.setdefault(node, (False, f"timed out after {timeout}s"))
        subprocess.run(["kubectl", "delete", "pod", pod, "--ignore-not-found", "--wait=false"],
                       capture_output=True, text=True)
    return results


def _save_state(topology):
    configmap = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": STATE_CONFIGMAP},
                 "data": {"topology.json": json.dumps(topology)}}
    subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(configmap), capture_output=True, text=True)


def _load_state():
    result = subprocess.run(["kubectl", "get", "configmap", STATE_CONFIGMAP, "-o", "jsonpath={.data.topology\\.json}"],
                            capture_output=True, text=True)
    return json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else None


def _check_nodes(topology, addresses):
    used = set(topology["nodes"]) | {l["from"] for l in topology["links"]} | {l["to"] for l in topology["links"]}
    unknown = sorted(used - set(addresses))
    if unknown:
        raise click.ClickException(f"Not cluster nodes: {', '.join(unknown)}. Nodes: {', '.join(sorted(addresses))}")


def _report(results, action):
    failed = [n for n, (ok, _) in results.items() if not ok]
    for node, (ok, output) in sorted(results.items()):
        click.echo(f"{'✅' if ok else '❌'} {node}: {action if ok else output.splitlines()[-1] if output else 'failed'}")
    if failed:
        raise click.ClickException(f"Failed on {', '.join(failed)}")


@topology_commands.command()
@click.option('--file', '-f', 'path', required=True, type=click.Path(exists=True), help='topology.yaml')
def apply(path):
    '''Apply the links in topology.yaml, replacing any earlier topology'''
    topology = load_topology(path)
    addresses = node_addresses()
    _check_nodes(topology, addresses)

    for node, labels in topology["nodes"].items():
        if labels:
            subprocess.run(["kubectl", "label", "node", node, "--overwrite"] + [f"{k}={v}" for k, v in labels.items()],
                           capture_output=True, text=True, check=True)
            click.echo(f"Labelled {node}: " + ", ".join(f"{k}={v}" for k, v in labels.items()))

    # every node gets a script, so nodes that lost their links are cleared too
    scripts = {}
    for node, ip in addresses.items():
        rules = [(addresses[l["to"]], l) for l in topology["links"] if l["from"] == node]
        scripts[node] = netem_script(ip, rules)
    results = run_on_nodes("oasees-netem", scripts)
    _save_state(topology)
    for l in topology["links"]:
        click.echo(f"  {l['from']} -> {l['to']}: " + ", ".join(
            f"{k} {l[k]:g}" for k in ("delay_ms", "jitter_ms", "loss_pct", "rate_mbit") if l[k]))
    _report(results, "links applied")


@topology_commands.command()
def clear():
    '''Remove every link impairment from every node'''
    addresses = node_addresses()
    results = run_on_nodes("oasees-netem", {node: netem_script(ip, []) for node, ip in addresses.items()})
    subprocess.run(["kubectl", "delete", "configmap", STATE_CONFIGMAP, "--ignore-not-found"],
                   capture_output=True, text=True)
    _report(results, "cleared")


@topology_commands.command()
def show():
    '''Show the topology that was last applied'''
    topology = _load_state()
    if not topology or not topology["links"]:
        click.echo("No topology applied.")
        return
    for node, labels in topology["nodes"].items():
        if labels:
            click.echo(f"{node}: " + ", ".join(f"{k}={v}" for k, v in labels.items()))
    for l in topology["links"]:
        click.echo(f"{l['from']} -> {l['to']}: " + ", ".join(
            f"{k} {l[k]:g}" for k in ("delay_ms", "jitter_ms", "loss_pct", "rate_mbit") if l[k]))


def parse_ping(output):
    """{destination ip: average rtt in ms} from the measure script's output."""
    rtts = {}
    for ip, avg in re.findall(r"PING (\S+).*?(?:= [\d.]+/([\d.]+)/|100% packet loss)", output, re.S):
        rtts[ip] = float(avg) if avg else None
    return rtts


@topology_commands.command()
@click.option('--count', default=5, show_default=True, help='Pings per pair')
def measure(count):
    '''Ping every node from every other node and print the round-trip times (ms)'''
    addresses = node_addresses()
    names = sorted(addresses)
    scripts = {node: "; ".join(f"echo PING {addresses[o]}; ping -c {count} -i 0.2 -q -W 2 {addresses[o]} | tail -2"
                               for o in names if o != node) or "true"
               for node in names}
    results = run_on_nodes("oasees-ping", scripts)
    width = max(len(n) for n in names)
    click.echo("round-trip ms".ljust(width) + "  " + "  ".join(n.rjust(width) for n in names))
    for src in names:
        ok, output = results[src]
        rtts = parse_ping(output) if ok else {}
        cells = []
        for dst in names:
            value = rtts.get(addresses[dst], "x") if dst != src else "-"
            cells.append(("lost" if value is None else value if isinstance(value, str) else f"{value:.1f}").rjust(width))
        click.echo(src.ljust(width) + "  " + "  ".join(cells))
