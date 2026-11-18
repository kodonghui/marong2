"""Prepare a local tunnel configuration that withdraws only the pet hostname."""

import argparse
import os
from pathlib import Path
import re
import sys

import yaml


TEMPLATE = Path(__file__).with_name("pet-ingress.example.yml")
EXAMPLE_HOST = "pet.example.invalid"
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOST = re.compile(rf"{LABEL}(?:\.{LABEL})+")


def blocked_config(source, hostname):
    if len(hostname) > 253 or HOST.fullmatch(hostname) is None:
        raise ValueError("Expected a lowercase DNS hostname")
    config = yaml.safe_load(source)
    tree = yaml.compose(source)
    if not isinstance(config, dict) or not isinstance(tree, yaml.MappingNode):
        raise ValueError("Expected a tunnel configuration mapping")
    entries = [node for key, node in tree.value if key.value == "ingress"]
    if len(entries) != 1 or not isinstance(entries[0], yaml.SequenceNode) or entries[0].flow_style:
        raise ValueError("Expected one block-style ingress list")
    rules = config.get("ingress")
    if not rules or any(not isinstance(rule, dict) for rule in rules):
        raise ValueError("Expected ingress rules to be mappings")

    targeted = [i for i, rule in enumerate(rules)
                if str(rule.get("hostname", "")).lower().rstrip(".") == hostname]
    deny = {"hostname": hostname, "service": "http_status:404"}
    if targeted == [0] and rules[0] == deny:
        return source

    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))["ingress"]
    expected = [{**rule, "hostname": hostname} for rule in template if rule.get("hostname") == EXAMPLE_HOST]
    if len(expected) != 2 or [rules[i] for i in targeted] != expected:
        raise ValueError("The hostname does not have exactly the two expected pet routes")

    lines = source.splitlines(keepends=True)
    nodes = entries[0].value
    if len(nodes) != len(rules):
        raise ValueError("Ingress rules cannot be paired with their source lines")

    def start(node):
        mark = node.start_mark
        position = re.fullmatch(r"([ ]*)-[ ]*", lines[mark.line][:mark.column])
        if position is None:
            raise ValueError("Ingress entries must begin at the start of a list item")
        return mark.line, position[1]

    first, indent = start(nodes[0])
    remove = set()
    for index in targeted:
        node = nodes[index]
        if not isinstance(node, yaml.MappingNode):
            raise ValueError("Pet routes must be written inline in the ingress list")
        begin, _ = start(node)
        end = max(value.end_mark.line for _, value in node.value)
        remove.update(range(begin, end + 1))

    newline = "\r\n" if lines[first].endswith("\r\n") else "\n"
    rule_text = f"{indent}- hostname: {hostname}{newline}{indent}  service: http_status:404{newline}"
    result = "".join((rule_text if i == first else "") + (line if i not in remove else "")
                     for i, line in enumerate(lines))
    expected_config = {**config, "ingress": [deny, *(rule for i, rule in enumerate(rules) if i not in targeted)]}
    if yaml.safe_load(result) != expected_config:
        raise ValueError("The proposed configuration affects another setting")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="current tunnel configuration to read")
    parser.add_argument("hostname", help="approved pet DNS hostname")
    parser.add_argument("output", type=Path, help="new private candidate file")
    args = parser.parse_args()
    try:
        original = args.config.read_bytes().decode("utf-8")
        candidate = blocked_config(original, args.hostname)
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
            output.write(candidate.encode("utf-8"))
    except UnicodeError:
        print("The tunnel configuration must use UTF-8", file=sys.stderr)
        return 1
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, yaml.YAMLError):
        print("Could not read the tunnel configuration or write a new candidate", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
