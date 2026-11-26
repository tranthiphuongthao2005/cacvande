"""Use synthetic fixtures to exercise preprocessing and the untouched encoder."""

import math
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch

from losses import apcl_loss
from meta_train import build_episode_embeddings
from model import Model, TYPE_NUM
from preprocess.__main__ import run
from preprocess.datasets import Line, Sequence, class_counts, read_bgl, read_hdfs, sample_block_labels, validate_split
from preprocess.npz_io import build_arrays, validate_arrays, vocabulary_manifest, write_split
from preprocess.parameters import (
    HEX, IP, NUM, PATH, STR, UNK, Parameter, Vocabulary, encode_parameters, extract_parameters,
    normalize_number, normalize_path, parameter_type,
)
from preprocess.parsing import DrainAdapter, Event


class ParameterTests(unittest.TestCase):
    def test_extraction(self):
        self.assertEqual(extract_parameters("port=42 at /a/12", "port=<*> at <*>"), (
            Parameter("key:port", "42", NUM), Parameter("pos:2", "/a/12", PATH),
        ))

    def test_types(self):
        for value, kind in (("-1.2e3", NUM), ("/10.0.0.1:9000", IP), ("2001:db8::1", IP),
                            ("0xfa", HEX), ("deadbeef", HEX), ("12345678", NUM),
                            (r"C:\tmp\file", PATH), ("hello", STR)):
            with self.subTest(value=value):
                self.assertEqual(parameter_type(value), kind)

    def test_numeric_normalization(self):
        self.assertAlmostEqual(normalize_number("-12"), -math.log1p(12))
        self.assertEqual(normalize_number("0"), 0)
        with self.assertRaises(ValueError):
            normalize_number("1e999")

    def test_path_normalization(self):
        self.assertEqual(normalize_path("/srv/part42/0xfeed"), "/srv/part<NUM>/<HEX>")

    def test_char_encoding_and_shared_vocabulary(self):
        source = [Parameter("key:user", "abc", STR)]
        vocab = Vocabulary.fit([source])
        key, _, chars, _ = encode_parameters([Parameter("key:foreign", "az", STR)], vocab)
        self.assertEqual(key[0], UNK)
        self.assertEqual(chars[0, :3].tolist(), [vocab.chars["a"], UNK, 0])
        self.assertEqual(vocab.keys.get("key:foreign"), None)
        self.assertEqual(vocabulary_manifest(vocab), vocabulary_manifest(Vocabulary.fit([source])))


class DatasetTests(unittest.TestCase):
    def test_cli_exports_all_splits_with_fixture_embeddings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bgl, hdfs, labels = (root / filename for filename in ("BGL.log", "HDFS.log", "labels.csv"))
            bgl.write_text("".join(
                f"{'ALERT' if i % 40 == 0 else '-'} 0 2005.01.01 node time node type comp INFO status=no {i}\n"
                for i in range(800)
            ), encoding="utf-8")
            hdfs.write_text("".join(
                f"081109 203518 143 INFO dfs.DataNode: status=ok stored blk_{i}\n" for i in range(40)
            ), encoding="utf-8")
            labels.write_text("BlockId,Label\n" + "".join(
                f"blk_{i},{'Normal' if i < 20 else 'Anomaly'}\n" for i in range(40)
            ), encoding="utf-8")
            args = Namespace(bgl_log=bgl, hdfs_log=hdfs, hdfs_labels=labels, sbert_dir=root,
                             output=root / "output", max_sequences=40, bgl_start_line=1,
                             hdfs_max_retained_lines=500, seed=123, embedding_batch_size=8)

            def fixture_vectors(templates, model_dir, batch_size):
                return {template: np.ones(768, np.float32) for template in templates}

            with patch("preprocess.__main__.embed_templates", side_effect=fixture_vectors):
                run(args)
            manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
            print(f"fixture pipeline: {manifest['elapsed_seconds']:.3f}s; "
                  f"process peak working set={manifest['peak_working_set_mib']} MiB", flush=True)
            vocab = Vocabulary(manifest["vocabulary"]["keys"], manifest["vocabulary"]["chars"])
            for domain, window in (("BGL", 20), ("HDFS", 50)):
                for split in ("training", "testing"):
                    lengths = [len(seq["line_ids"]) for seq in manifest["splits"][domain][split]]
                    with np.load(args.output / f"{domain}_{split}.npz", allow_pickle=False) as arrays:
                        validate_arrays(arrays, window, vocab, lengths)
            self.assertEqual(manifest["class_counts"]["HDFS"]["testing"], {"Normal": 4, "Anomaly": 4})

    def test_bgl_windows_labels_and_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "BGL.log"
            path.write_text("".join(
                f"{'ALERT' if i == 22 else '-'} 0 2005.01.01 node time node type comp INFO msg {i}\n"
                for i in range(107)
            ), encoding="utf-8")
            train, test = read_bgl(path, 10)
        self.assertEqual([seq.lines[0].id for seq in train], [1, 21, 41, 61])
        self.assertEqual([seq.label for seq in train], [0, 1, 0, 0])
        self.assertEqual(class_counts(test), {"Normal": 1, "Anomaly": 0})
        validate_split(train, test)

    def test_hdfs_grouping_ground_truth_and_cross_split_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, labels = Path(tmp) / "HDFS.log", Path(tmp) / "labels.csv"
            labels.write_text("BlockId,Label\n" + "".join(
                f"blk_{i},{'Normal' if i < 5 else 'Anomaly'}\n" for i in range(10)
            ), encoding="utf-8")
            members = sample_block_labels(labels, 10, 7)
            train_id = next(k for k, v in members.items() if v[0] == 0)
            test_id = next(k for k, v in members.items() if v[0] == 1)
            contents = [f"INFO {block}" for block in members] * 2
            contents += [f"INFO {train_id} {test_id}", "ERROR blk_100"]
            path.write_text("\n".join(contents), encoding="utf-8")
            train, test, report = read_hdfs(path, labels, 10, 7)
        validate_split(train, test)
        self.assertEqual(report, {"shared_sessions_excluded": 2, "missing_sessions": 0})
        self.assertEqual(len(train) + len(test), 8)
        for seq in train + test:
            self.assertEqual(seq.label, members[seq.id][1])
            self.assertEqual(len(seq.lines), 2)
            self.assertLess(seq.lines[0].id, seq.lines[1].id)

    def test_rejects_leakage(self):
        line = Line(1, "shared")
        with self.assertRaisesRegex(ValueError, "Raw lines"):
            validate_split([Sequence("a", 0, (line,))], [Sequence("b", 1, (line,))])

    def test_drain_keeps_raw_ids_and_freezes_templates(self):
        def seq(number, content):
            text = "081109 203518 143 INFO dfs.DataNode: " + content
            return Sequence(str(number), 0, (Line(number, text),))

        train = [seq(9, "stored block blk_1"), seq(12, "stored block blk_2")]
        test = [seq(99, "never seen status=abc")]
        adapter = DrainAdapter("HDFS")
        adapter.fit(train)
        initial = adapter.transform(train)[9]
        events = adapter.transform(test)
        self.assertEqual(set(events), {9, 12, 99})
        self.assertEqual(initial.template, "stored block <*>")
        self.assertEqual(initial.event_id, events[12].event_id)
        self.assertEqual(events[99].parameters[0].key, "key:status")
        self.assertEqual(adapter.transform(train)[9], initial)


class SchemaAndModelTests(unittest.TestCase):
    def setUp(self):
        self.seq = [
            Sequence("n", 0, (Line(1, ""),)),
            Sequence("a", 1, (Line(2, ""),)),
        ]
        self.events = {
            1: Event(1, "e1", "normal", (Parameter("pos:1", "12", NUM),)),
            2: Event(2, "e2", "anomaly", (Parameter("pos:1", "odd", STR),)),
        }
        self.vocab = Vocabulary.fit(event.parameters for event in self.events.values())
        self.vectors = {"normal": np.ones(768, np.float32), "anomaly": -np.ones(768, np.float32)}

    def test_npz_schema_and_original_loader_forward_apcl(self):
        query_sequences = [
            Sequence("query:n", 0, (Line(3, ""),)),
            Sequence("query:a", 1, (Line(4, ""),)),
        ]
        events = {
            **self.events,
            3: Event(3, "e3", "normal-query", self.events[1].parameters),
            4: Event(4, "e4", "anomaly-query", self.events[2].parameters),
        }
        vectors = {**self.vectors, "normal-query": self.vectors["normal"] * 0.5,
                   "anomaly-query": self.vectors["anomaly"] * 0.5}
        validate_split(self.seq, query_sequences)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "fixture.npz"
            write_split(output, self.seq + query_sequences, events, vectors, self.vocab, 20)
            with np.load(output, allow_pickle=False) as data:
                validate_arrays(data, 20, self.vocab, [1, 1, 1, 1])
                params = tuple(data[key] for key in ("p_key", "p_type", "p_val", "p_num"))
                labels = data["y"].argmax(axis=1)
                torch.manual_seed(123)
                model = Model(num_layers=1, key_vocab_size=int(data["key_vocab_size"]),
                              char_vocab_size=int(data["char_vocab_size"]), window_size=20).eval()
                with torch.inference_mode():
                    support, y_support, query, y_query = build_episode_embeddings(
                        model, data["x"][:2], labels[:2], tuple(p[:2] for p in params),
                        data["x"][2:], labels[2:], tuple(p[2:] for p in params),
                        "cpu", 20, 8, 16,
                    )
                    loss = apcl_loss(support, y_support, query, y_query)
                self.assertEqual(support.shape, (2, 768))
                self.assertTrue(torch.isfinite(support).all().item())
                self.assertTrue(torch.isfinite(loss).item())
                print(f"fixture forward={tuple(support.shape)}, APCL={loss.item():.6f}", flush=True)

    def test_schema_rejects_bad_values(self):
        cases = (("x", (0, 0, 0), np.nan), ("p_num", (0, 0, 0), np.inf),
                 ("p_key", (0, 0, 0), 10000), ("y", (0, 1), 1), ("p_val", (0, 1, 0, 0), 1))
        for field, index, value in cases:
            with self.subTest(field=field):
                arrays = build_arrays(self.seq, self.events, self.vectors, self.vocab, 20)
                arrays[field][index] = value
                with self.assertRaises(ValueError):
                    validate_arrays(arrays, 20, self.vocab, [1, 1])

    def test_original_padding_behavior(self):
        torch.manual_seed(123)
        model = Model(num_layers=1, key_vocab_size=len(self.vocab.keys) + 2,
                      char_vocab_size=len(self.vocab.chars) + 2, window_size=50).eval()

        def encoded(window):
            arrays = build_arrays(self.seq, self.events, self.vectors, self.vocab, window)
            params = tuple(torch.from_numpy(arrays[name]) for name in ("p_key", "p_type", "p_val", "p_num"))
            return model.encode(torch.from_numpy(arrays["x"]), params), params

        with torch.inference_mode():
            short, _ = encoded(1)
            bgl, params = encoded(20)
            hdfs, hdfs_params = encoded(50)
            self.assertTrue(all(torch.equal(a, b[:, :20]) for a, b in zip(params, hdfs_params)))
            inactive = tuple(torch.zeros_like(a[:, 1:2]) for a in params)
            self.assertEqual(inactive[1][0, 0, 0].item(), TYPE_NUM)
            slot_signal = model.param_encoder(*inactive).norm().item()
            self.assertGreater(slot_signal, 0)
            changed_numeric = (*inactive[:3], torch.ones_like(inactive[3]))
            self.assertFalse(torch.equal(model.param_encoder(*inactive), model.param_encoder(*changed_numeric)))
            short_delta = (short - bgl).abs().max().item()
            window_delta = (bgl - hdfs).abs().max().item()
            self.assertGreater(short_delta, 0)
            self.assertGreater(window_delta, 0)
            print(f"padding fixture: max CLS delta 1->20={short_delta:.6f}; "
                  f"20->50={window_delta:.6f}; empty event parameter L2={slot_signal:.6f}", flush=True)


if __name__ == "__main__":
    unittest.main()
