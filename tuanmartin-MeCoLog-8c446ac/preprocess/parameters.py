"""Typed parameter features consumed by the original MeCoLog encoder."""

import ipaddress
import math
import re
from dataclasses import dataclass

import numpy as np

NUM, IP, HEX, PATH, STR = range(5)
P, C = 8, 16
PAD, UNK = 0, 1
NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
HEX_VALUE = re.compile(r"(?:0x[0-9a-f]+|(?=[0-9a-f]*[a-f])[0-9a-f]{8,})", re.I)
PATH_VALUE = re.compile(r"(?:[A-Za-z]:[\\/]|[\\/]|\.{1,2}[\\/])\S+")
EXPLICIT = re.compile(r"""(?<![\w.-])(?P<key>[A-Za-z_][\w.-]*)\s*=\s*(?P<value>"[^"]*"|'[^']*'|[^\s,;]+)""")
VOLATILE = re.compile(r"0x[0-9a-f]+|(?<![a-z])[0-9a-f]{8,}(?![a-z])|\d+", re.I)


@dataclass(frozen=True)
class Parameter:
    key: str
    value: str
    kind: int


def parameter_type(value):
    address = value.lstrip("/")
    if address.startswith("[") and "]" in address:
        address = address[1:address.index("]")]
    elif address.count(":") == 1 and "." in address:
        address = address.split(":")[0]
    try:
        ipaddress.ip_address(address)
        return IP
    except ValueError:
        pass
    if HEX_VALUE.fullmatch(value):
        return HEX
    if NUMBER.fullmatch(value):
        return NUM
    if PATH_VALUE.fullmatch(value):
        return PATH
    return STR


def normalize_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite numeric parameter: {value}")
    return math.copysign(math.log1p(abs(number)), number)


def normalize_path(value):
    return VOLATILE.sub(
        lambda match: "<NUM>" if match.group().isdigit() else "<HEX>", value
    )


def extract_parameters(content, template):
    """Find explicit assignments and capture remaining Drain wildcard spans."""
    explicit = [
        (*match.span("value"), "key:" + match["key"], match["value"].strip("\"'"))
        for match in EXPLICIT.finditer(content)
    ]
    candidates = list(explicit)
    fragments = template.split("<*>")
    if len(fragments) > 1:
        pattern = "(.*?)".join(re.escape(fragment) for fragment in fragments)
        match = re.fullmatch(pattern, content)
        if match:
            for group in range(1, len(fragments)):
                start, end = match.span(group)
                if start < end and not any(start < b and a < end for a, b, _, _ in explicit):
                    candidates.append((start, end, None, match[group]))
    parameters = []
    for index, (_, _, key, value) in enumerate(sorted(candidates), 1):
        value = value.strip()
        if value:
            parameters.append(Parameter(key or f"pos:{index}", value, parameter_type(value)))
    return tuple(parameters[:P])


@dataclass(frozen=True)
class Vocabulary:
    keys: dict[str, int]
    chars: dict[str, int]

    @classmethod
    def fit(cls, events):
        keys = {f"pos:{index}" for index in range(1, P + 1)}
        chars = set()
        for parameters in events:
            for param in parameters:
                keys.add(param.key)
                if param.kind in {PATH, STR}:
                    chars.update(character_value(param)[:C])
        return cls(
            {key: index for index, key in enumerate(sorted(keys), 2)},
            {char: index for index, char in enumerate(sorted(chars), 2)},
        )


def character_value(param):
    return normalize_path(param.value) if param.kind == PATH else param.value


def encode_parameters(parameters, vocab):
    keys = np.zeros(P, dtype=np.int64)
    kinds = np.zeros(P, dtype=np.int64)
    chars = np.zeros((P, C), dtype=np.int64)
    numbers = np.zeros(P, dtype=np.float32)
    for index, param in enumerate(parameters[:P]):
        keys[index] = vocab.keys.get(param.key, UNK)
        kinds[index] = param.kind
        if param.kind in {PATH, STR}:
            encoded = [vocab.chars.get(char, UNK) for char in character_value(param)[:C]]
            chars[index, :len(encoded)] = encoded
        elif param.kind == NUM:
            numbers[index] = normalize_number(param.value)
    return keys, kinds, chars, numbers
