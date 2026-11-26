"""Adapt the original Drain tree to selected raw lines with stable line IDs."""

import hashlib
import re
from dataclasses import dataclass

from Drain import LogParser, Logcluster, Node
from .parameters import EXPLICIT, STR, extract_parameters, parameter_type

FORMATS = {
    "BGL": "<Label> <Timestamp> <Date> <Node> <Time> <NodeRepeat> <Type> <Component> <Level> <Content>",
    "HDFS": "<Date> <Time> <Pid> <Level> <Component>: <Content>",
}
MASKS = {
    "BGL": [
        r"core\.\d+",
        r"(/|)([0-9]+\.){3}[0-9]+(:[0-9]+|)(:|)",
        r"(?:\/[\*\w\.-]+)+",
        r"0x[0-9a-f]+(?: [0-9a-f]{8})*",
        r"[0-9a-f]{8}(?: [0-9a-f]{8})*",
        r"(?<=[^A-Za-z0-9])(\-?\+?\d+)(?=[^A-Za-z0-9])|[0-9]+$",
    ],
    "HDFS": [
        r"blk_-?[0-9]+",
        r"(/|)([0-9]+\.){3}[0-9]+(:[0-9]+|)(:|)",
        r"(?<=[^A-Za-z0-9])(\-?\+?\d+)(?=[^A-Za-z0-9])|[0-9]+$",
    ],
}


@dataclass(frozen=True)
class Event:
    line_id: int
    event_id: str
    template: str
    parameters: tuple


class DrainAdapter:
    def __init__(self, domain):
        self.parser = LogParser(FORMATS[domain], depth=4, st=0.5, rex=MASKS[domain])
        _, self.pattern = self.parser.generate_logformat_regex(FORMATS[domain])
        self.root = Node()
        self.training_clusters = {}
        self.events = {}
        self.fitted = False

    def content(self, line):
        match = self.pattern.fullmatch(line.text)
        if not match or not match["Content"].strip():
            raise ValueError(f"Drain format mismatch or empty Content at raw line {line.id}")
        return " ".join(match["Content"].split())

    def tokens(self, content):
        def mask_assignment(match):
            prefix_length = match.start("value") - match.start()
            return match.group()[:prefix_length] + "<*>"

        def mask_typed_token(match):
            token = match.group()
            return "<*>" if parameter_type(token) != STR else token

        masked = EXPLICIT.sub(mask_assignment, content)
        masked = re.sub(r"\S+", mask_typed_token, masked)
        return self.parser.preprocess(masked).split()

    @staticmethod
    def unique_lines(sequences):
        lines = {line.id: line for seq in sequences for line in seq.lines}
        return (lines[line_id] for line_id in sorted(lines))

    def fit(self, sequences):
        if self.fitted:
            raise ValueError("Drain adapter is already fitted")
        for line in self.unique_lines(sequences):
            content = self.content(line)
            tokens = self.tokens(content)
            cluster = self.parser.treeSearch(self.root, tokens)
            if cluster is None:
                cluster = Logcluster(tokens, [])
                self.parser.addSeqToPrefixTree(self.root, cluster)
            else:
                cluster.logTemplate = self.parser.getTemplate(tokens, cluster.logTemplate)
            self.training_clusters[line.id] = cluster
        self.fitted = True

    def transform(self, sequences):
        if not self.fitted:
            raise ValueError("Fit Drain before transform")
        for line in self.unique_lines(sequences):
            content = self.content(line)
            tokens = self.tokens(content)
            cluster = self.training_clusters.get(line.id)
            if cluster is None:
                cluster = self.parser.treeSearch(self.root, tokens)
            template = " ".join(tokens if cluster is None else cluster.logTemplate)
            event_id = hashlib.md5(template.encode("utf-8")).hexdigest()[:8]
            self.events[line.id] = Event(line.id, event_id, template, extract_parameters(content, template))
        return self.events
