"""
tests.py

Stdlib-only unit tests covering each stage: generator, extractor, graph,
rewriter (including the human-notes preservation behavior), and linter
(including the orphan-miscount regression this codebase actually hit
during development -- see test_linter_does_not_miscount_referenced_by).
"""

import os
import shutil
import tempfile
import unittest

from generator import generate_corpus
from extractor import extract_all, extract_entity, Entity
from graph import build_graph, orphan_ids
from rewriter import compile_pages, render_page
from linter import lint
from compiler import compile_wiki


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deterministic_output(self):
        dir_a = os.path.join(self.tmp, "a")
        dir_b = os.path.join(self.tmp, "b")
        paths_a = generate_corpus(dir_a, num_files=15, seed=42)
        paths_b = generate_corpus(dir_b, num_files=15, seed=42)
        self.assertEqual(len(paths_a), 15)
        for pa, pb in zip(sorted(paths_a), sorted(paths_b)):
            with open(pa) as fa, open(pb) as fb:
                self.assertEqual(fa.read(), fb.read())

    def test_file_count_matches_request(self):
        d = os.path.join(self.tmp, "c")
        paths = generate_corpus(d, num_files=37, seed=7)
        self.assertEqual(len(paths), 37)
        self.assertEqual(len(os.listdir(d)), 37)


class TestExtractor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_hash_header_extracted(self):
        path = self._write("a.txt", "# My Topic\ncreated: 2026-01-01\n\nbody text here\n")
        e = extract_entity(path)
        self.assertEqual(e.name, "My Topic")
        self.assertEqual(e.created, "2026-01-01")
        self.assertIn("body text here", e.body)

    def test_bare_uppercase_header_extracted(self):
        path = self._write("b.txt", "MY TOPIC\n\nsome content\n")
        e = extract_entity(path)
        self.assertEqual(e.name, "My Topic")

    def test_missing_header_falls_back_to_filename(self):
        path = self._write("fallback_name.txt", "just some prose, no header at all\n")
        e = extract_entity(path)
        self.assertEqual(e.name, "Fallback Name")

    def test_aliases_parsed(self):
        path = self._write("c.txt", "# Thing\naliases: t1, t2, t3\n\nbody\n")
        e = extract_entity(path)
        self.assertEqual(e.aliases, ["t1", "t2", "t3"])

    def test_extract_all_returns_all_files(self):
        self._write("x.txt", "# X\n\nbody\n")
        self._write("y.txt", "# Y\n\nbody\n")
        self._write("not_txt.md", "# Z\n\nbody\n")  # should be ignored
        entities = extract_all(self.tmp)
        self.assertEqual(len(entities), 2)


class TestGraph(unittest.TestCase):
    def test_bidirectional_edge_created(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", body="mentions Beta here"),
            "b": Entity(entity_id="b", name="Beta", body="no mentions of others"),
        }
        g = build_graph(entities)
        self.assertIn("b", g["a"]["outgoing"])
        self.assertIn("a", g["b"]["incoming"])

    def test_no_self_link(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", body="Alpha refers to itself"),
        }
        g = build_graph(entities)
        self.assertNotIn("a", g["a"]["outgoing"])

    def test_orphan_detection(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", body="mentions Beta"),
            "b": Entity(entity_id="b", name="Beta", body="mentions nothing"),
            "c": Entity(entity_id="c", name="Gamma", body="mentions nothing either"),
        }
        g = build_graph(entities)
        orphans = orphan_ids(g)
        self.assertIn("c", orphans)      # nothing links to Gamma
        self.assertIn("a", orphans)      # nothing links to Alpha either
        self.assertNotIn("b", orphans)   # Beta is referenced by Alpha


class TestRewriter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_related_and_referenced_by_sections_correct(self):
        entities = {
            "alpha": Entity(entity_id="alpha", name="Alpha", body="mentions Beta"),
            "beta": Entity(entity_id="beta", name="Beta", body="mentions nothing"),
        }
        g = build_graph(entities)
        page_a = render_page(entities["alpha"], g["alpha"], entities)
        page_b = render_page(entities["beta"], g["beta"], entities)
        self.assertIn("[[Beta]]", page_a.split("## Related")[1].split("## Referenced By")[0])
        self.assertIn("[[Alpha]]", page_b.split("## Referenced By")[1])

    def test_human_notes_preserved_across_recompile(self):
        entities = {
            "alpha": Entity(entity_id="alpha", name="Alpha", body="first pass body"),
        }
        g = build_graph(entities)
        out_dir = self.tmp
        compile_pages(entities, g, out_dir)

        path = os.path.join(out_dir, "alpha.md")
        with open(path) as f:
            content = f.read()
        content = content.replace(
            "_(add your own notes here -- preserved on recompile)_",
            "MANUALLY WRITTEN CONTENT",
        )
        with open(path, "w") as f:
            f.write(content)

        # Recompile with changed source body -- Notes should survive.
        entities["alpha"].body = "second pass body, changed"
        compile_pages(entities, g, out_dir)

        with open(path) as f:
            recompiled = f.read()
        self.assertIn("MANUALLY WRITTEN CONTENT", recompiled)
        self.assertIn("second pass body, changed", recompiled)  # body section did update


class TestLinter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_linter_does_not_miscount_referenced_by(self):
        # Regression test: Referenced By sections contain [[links]] too.
        # A naive linter that scans the whole file for incoming-link
        # counting will falsely mark real orphans as non-orphaned.
        entities = {
            "alpha": Entity(entity_id="alpha", name="Alpha", body="mentions Beta"),
            "beta": Entity(entity_id="beta", name="Beta", body="mentions nothing"),
        }
        g = build_graph(entities)
        compile_pages(entities, g, self.tmp)
        report = lint(self.tmp)
        # Alpha has no incoming links (nothing links to it) -> orphan.
        self.assertIn("alpha.md", report.orphan_pages)
        self.assertNotIn("beta.md", report.orphan_pages)

    def test_broken_link_detected(self):
        entities = {
            "alpha": Entity(entity_id="alpha", name="Alpha", body="no mentions"),
        }
        g = build_graph(entities)
        compile_pages(entities, g, self.tmp)
        path = os.path.join(self.tmp, "alpha.md")
        with open(path, "a") as f:
            f.write("\nSee [[Ghost Page]] too.\n")
        report = lint(self.tmp)
        self.assertEqual(len(report.broken_links), 1)
        self.assertEqual(report.broken_links[0], ("alpha.md", "Ghost Page"))

    def test_clean_wiki_has_no_broken_links(self):
        entities = {
            "alpha": Entity(entity_id="alpha", name="Alpha", body="mentions Beta"),
            "beta": Entity(entity_id="beta", name="Beta", body="mentions nothing"),
        }
        g = build_graph(entities)
        compile_pages(entities, g, self.tmp)
        report = lint(self.tmp)
        self.assertEqual(report.broken_links, [])


class TestFullPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_end_to_end_on_generated_corpus(self):
        raw_dir = os.path.join(self.tmp, "raw")
        out_dir = os.path.join(self.tmp, "out")
        generate_corpus(raw_dir, num_files=30, seed=42)
        result = compile_wiki(raw_dir, out_dir)
        self.assertEqual(len(result["entities"]), 30)
        self.assertEqual(len(result["written_paths"]), 30)
        self.assertEqual(result["lint_report"].broken_links, [])
        self.assertEqual(result["lint_report"].total_pages, 30)

    def test_recompile_is_idempotent_on_compiler_owned_sections(self):
        raw_dir = os.path.join(self.tmp, "raw")
        out_dir = os.path.join(self.tmp, "out")
        generate_corpus(raw_dir, num_files=10, seed=42)
        compile_wiki(raw_dir, out_dir)
        first_pass = {}
        for fname in os.listdir(out_dir):
            with open(os.path.join(out_dir, fname)) as f:
                first_pass[fname] = f.read()

        compile_wiki(raw_dir, out_dir)
        second_pass = {}
        for fname in os.listdir(out_dir):
            with open(os.path.join(out_dir, fname)) as f:
                second_pass[fname] = f.read()

        self.assertEqual(first_pass, second_pass)


if __name__ == "__main__":
    unittest.main(verbosity=2)
