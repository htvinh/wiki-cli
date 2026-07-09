"""
tests.py

Stdlib-only unit tests covering each stage: generator, extractor, graph,
rewriter (including the human-notes preservation behavior), and linter
(including the orphan-miscount regression this codebase actually hit
during development -- see test_linter_does_not_miscount_referenced_by).
"""

import os
import shutil
import sys
import tempfile
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from compiler import compile_wiki
from extractor import Entity, extract_all, extract_entity
from generator import generate_corpus
from graph import build_graph, build_navigation_edges, graph_report, orphan_ids
from linter import lint
from rewriter import compile_pages, render_page


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

    def test_vietnamese_hash_header_extracted(self):
        body = "nội dung chính tại đây\n"
        path = self._write("viet.txt", "# Hệ Thống\ncreated: 2026-03-15\n\n" + body)
        e = extract_entity(path)
        self.assertEqual(e.name, "Hệ Thống")
        self.assertIn("nội dung chính tại đây", e.body)

    def test_vietnamese_slug_from_unicode_name(self):
        path = self._write("vt.txt", "# Nguyễn Văn A\n\nxin chào\n")
        e = extract_entity(path)
        self.assertEqual(e.slug, "nguyễn_văn_a")
        self.assertNotEqual(e.entity_id, "nguyễn_văn_a")
        self.assertEqual(len(e.entity_id), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in e.entity_id))

    def test_mixed_vietnamese_english_body_extracted(self):
        path = self._write("mix.txt", "# Chủ Đề\n\n"
                            "This topic covers nhiều vấn đề quan trọng.\n"
                            "See also Gradient Descent and Hệ Thống.\n")
        e = extract_entity(path)
        self.assertIn("This topic covers", e.body)
        self.assertIn("nhiều vấn đề quan trọng", e.body)


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

    def test_vietnamese_mention_detected(self):
        entities = {
            "ht": Entity(entity_id="ht", name="Hệ Thống", body="xin chào"),
            "nd": Entity(entity_id="nd", name="Nội Dung", body="bài viết về Hệ Thống"),
        }
        g = build_graph(entities)
        self.assertIn("ht", g["nd"]["outgoing"])
        self.assertIn("nd", g["ht"]["incoming"])

    def test_mixed_english_vietnamese_mention_detected(self):
        entities = {
            "topic": Entity(entity_id="topic", name="Chủ Đề",
                            body="this is about Hệ Thống and Gradient Descent"),
            "ht": Entity(entity_id="ht", name="Hệ Thống", body="nội dung"),
            "gd": Entity(entity_id="gd", name="Gradient Descent", body="some text"),
        }
        g = build_graph(entities)
        self.assertIn("ht", g["topic"]["outgoing"])
        self.assertIn("gd", g["topic"]["outgoing"])

    def test_vietnamese_no_self_link(self):
        entities = {
            "ht": Entity(entity_id="ht", name="Hệ Thống", body="Hệ Thống is mentioned in itself"),
        }
        g = build_graph(entities)
        self.assertNotIn("ht", g["ht"]["outgoing"])

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

    def test_alias_mention_detected(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", body="mentions Apex in text"),
            "b": Entity(entity_id="b", name="Beta", aliases=["Apex"],
                        body="nothing"),
        }
        g = build_graph(entities)
        self.assertIn("b", g["a"]["outgoing"])
        self.assertIn("a", g["b"]["incoming"])

    def test_alias_mention_skips_self(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", aliases=["Apex"],
                        body="Apex appears in its own body"),
        }
        g = build_graph(entities)
        self.assertNotIn("a", g["a"]["outgoing"])

    def test_name_mention_still_detected_with_aliases(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", aliases=["Apex"],
                        body="mentions Beta"),
            "b": Entity(entity_id="b", name="Beta", body="nothing"),
        }
        g = build_graph(entities)
        self.assertIn("b", g["a"]["outgoing"])

    def test_alias_multi_word_mention_detected(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha Corp",
                        body="refers to Apex Solutions here"),
            "b": Entity(entity_id="b", name="Beta LLC",
                        aliases=["Apex Solutions"], body="nothing"),
        }
        g = build_graph(entities)
        self.assertIn("b", g["a"]["outgoing"])
        self.assertIn("a", g["b"]["incoming"])

    def test_navigation_edges_added_to_most_linked(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", body="mentions Beta and Gamma"),
            "b": Entity(entity_id="b", name="Beta", body="mentions Gamma"),
            "c": Entity(entity_id="c", name="Gamma", body="nothing"),
            "d": Entity(entity_id="d", name="Delta", body="mentions nothing either"),
        }
        g = build_graph(entities)
        g = build_navigation_edges(g, entities, top_n=1)
        # Gamma has 2 incoming (from a, b) — should be the only hub
        self.assertIn("c", g["a"]["outgoing"])
        self.assertIn("c", g["b"]["outgoing"])
        self.assertIn("c", g["d"]["outgoing"])

    def test_navigation_edges_respects_top_n(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", body="mentions B C D"),
            "b": Entity(entity_id="b", name="B", body="mentions C D"),
            "c": Entity(entity_id="c", name="C", body="mentions D"),
            "d": Entity(entity_id="d", name="D", body="nothing"),
        }
        g = build_graph(entities)
        g = build_navigation_edges(g, entities, top_n=2)
        # D (incoming=3), C (incoming=2) should be hubs
        for eid in ("a", "b", "c"):
            self.assertIn("d", g[eid]["outgoing"])

    def test_navigation_zero_disabled(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", body="mentions Beta"),
            "b": Entity(entity_id="b", name="Beta", body="nothing"),
        }
        g = build_graph(entities)
        g = build_navigation_edges(g, entities, top_n=0)
        self.assertEqual(g, build_graph(entities))

    def test_graph_report_counts(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", body="mentions Beta and Gamma"),
            "b": Entity(entity_id="b", name="Beta", body="mentions Gamma"),
            "c": Entity(entity_id="c", name="Gamma", body="nothing"),
        }
        g = build_graph(entities)
        r = graph_report(g, entities)
        self.assertEqual(r.entity_count, 3)
        self.assertEqual(r.edge_count, 3)  # a→b, a→c, b→c

    def test_graph_report_top_linked(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", body="mentions B and C and D"),
            "b": Entity(entity_id="b", name="B", body="mentions C and D"),
            "c": Entity(entity_id="c", name="C", body="mentions D"),
            "d": Entity(entity_id="d", name="D", body="nothing"),
        }
        g = build_graph(entities)
        r = graph_report(g, entities, top_n=2)
        # D (in 3), C (in 2), B (in 1), A (in 0)
        self.assertEqual(len(r.top_linked), 2)
        self.assertEqual(r.top_linked[0][0], "d")
        self.assertEqual(r.top_linked[0][1], 3)

    def test_graph_report_lexical_unlinked(self):
        entities = {
            "a": Entity(entity_id="a", name="Alpha", body="mentions Beta"),
            "b": Entity(entity_id="b", name="Beta", body="nothing"),
            "c": Entity(entity_id="c", name="Gamma", body="nothing"),
        }
        g = build_graph(entities)
        r = graph_report(g, entities)
        self.assertIn("a", r.lexical_unlinked)
        self.assertIn("c", r.lexical_unlinked)
        self.assertNotIn("b", r.lexical_unlinked)

    def test_graph_report_empty(self):
        r = graph_report({})
        self.assertEqual(r.entity_count, 0)
        self.assertEqual(r.edge_count, 0)
        self.assertEqual(r.top_linked, [])
        self.assertEqual(r.lexical_unlinked, [])


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
        self.assertIn("[Beta](beta.md)", page_a.split("## Related")[1].split("## Referenced By")[0])
        self.assertIn("[Alpha](alpha.md)", page_b.split("## Linked From")[1])

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

    def test_linter_no_unreachable_when_index_references_all(self):
        # The auto-generated index.md links to every page,
        # so no pages are unreachable without store.
        entities = {
            "alpha": Entity(entity_id="alpha", name="Alpha", body="mentions Beta"),
            "beta": Entity(entity_id="beta", name="Beta", body="mentions nothing"),
        }
        g = build_graph(entities)
        compile_pages(entities, g, self.tmp)
        report = lint(self.tmp)
        self.assertEqual(len(report.unreachable_pages), 0)

    def test_linter_unreachable_without_index(self):
        # A page that's not in any index is unreachable.
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        # Write only a content page, no index
        with open(os.path.join(out, "lonely.md"), "w") as f:
            f.write("# Lonely\n\n## Body\n\nNobody links to me.")
        report = lint(out)
        self.assertIn("lonely.md", report.unreachable_pages)

    def test_broken_link_detected(self):
        entities = {
            "alpha": Entity(entity_id="alpha", name="Alpha", body="no mentions"),
        }
        g = build_graph(entities)
        compile_pages(entities, g, self.tmp)
        path = os.path.join(self.tmp, "alpha.md")
        with open(path, "a") as f:
            f.write("\nSee [Ghost Page](ghost_page.md) too.\n")
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
        self.assertEqual(len(result["written_paths"]), 31)  # 30 content + 1 index
        self.assertEqual(result["lint_report"].broken_links, [])
        self.assertEqual(result["lint_report"].total_pages, 31)

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


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        self.cache_dir = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _store(self):
        from store import SQLiteStore
        return SQLiteStore(self.db_path, cache_dir=self.cache_dir)

    def test_entity_round_trip(self):
        store = self._store()
        store.entities.put("abc123", name="Test Entity",
                           slug="test_entity", body_hash="h1")
        loaded = store.entities.get("abc123")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["name"], "Test Entity")
        self.assertEqual(loaded["slug"], "test_entity")
        self.assertEqual(loaded["body_hash"], "h1")

    def test_entity_exists(self):
        store = self._store()
        self.assertFalse(store.entities.exists("nope"))
        store.entities.put("e1", name="Eins", slug="eins")
        self.assertTrue(store.entities.exists("e1"))

    def test_entity_delete(self):
        store = self._store()
        store.entities.put("e1", name="Eins", slug="eins")
        self.assertTrue(store.entities.exists("e1"))
        store.entities.delete("e1")
        self.assertFalse(store.entities.exists("e1"))

    def test_entity_iter_ids(self):
        store = self._store()
        store.entities.put("a", name="A", slug="a")
        store.entities.put("b", name="B", slug="b")
        ids = list(store.entities.iter_ids())
        self.assertCountEqual(ids, ["a", "b"])

    def test_entity_iter_entities(self):
        store = self._store()
        store.entities.put("a", name="A", slug="a")
        all_ents = list(store.entities.iter_entities())
        self.assertEqual(len(all_ents), 1)
        self.assertEqual(all_ents[0]["name"], "A")

    def test_graph_edge_round_trip(self):
        store = self._store()
        store.graph.put_edge("a", "b")
        self.assertEqual(store.graph.get_outgoing("a"), {"b"})
        self.assertEqual(store.graph.get_incoming("b"), {"a"})

    def test_graph_delete_outgoing(self):
        store = self._store()
        store.graph.put_edge("a", "b")
        store.graph.put_edge("a", "c")
        store.graph.delete_outgoing("a")
        self.assertEqual(store.graph.get_outgoing("a"), set())
        self.assertEqual(store.graph.get_incoming("b"), set())

    def test_graph_delete_incoming(self):
        store = self._store()
        store.graph.put_edge("a", "b")
        store.graph.put_edge("c", "b")
        store.graph.delete_incoming("b")
        self.assertEqual(store.graph.get_incoming("b"), set())
        self.assertEqual(store.graph.get_outgoing("a"), set())

    def test_graph_iter_edges(self):
        store = self._store()
        store.graph.put_edge("a", "b")
        store.graph.put_edge("c", "d")
        edges = list(store.graph.iter_edges())
        self.assertCountEqual(edges, [("a", "b"), ("c", "d")])

    def test_graph_edge_count(self):
        store = self._store()
        self.assertEqual(store.graph.get_edge_count(), 0)
        store.graph.put_edge("a", "b")
        store.graph.put_edge("a", "c")
        self.assertEqual(store.graph.get_edge_count(), 2)

    def test_graph_get_all_outgoing(self):
        store = self._store()
        store.graph.put_edge("a", "b")
        store.graph.put_edge("a", "c")
        store.graph.put_edge("d", "e")
        all_out = store.graph.get_all_outgoing()
        self.assertEqual(all_out["a"], {"b", "c"})
        self.assertEqual(all_out["d"], {"e"})

    def test_graph_get_outgoing_by_type(self):
        store = self._store()
        store.graph.put_edge("a", "b", "explicit")
        store.graph.put_edge("a", "c", "alias")
        self.assertEqual(store.graph.get_outgoing_by_type("a", "explicit"), {"b"})
        self.assertEqual(store.graph.get_outgoing_by_type("a", "alias"), {"c"})

    def test_graph_get_incoming_by_type(self):
        store = self._store()
        store.graph.put_edge("a", "x", "explicit")
        store.graph.put_edge("b", "x", "alias")
        self.assertEqual(store.graph.get_incoming_by_type("x", "explicit"), {"a"})
        self.assertEqual(store.graph.get_incoming_by_type("x", "alias"), {"b"})

    def test_graph_iter_edges_by_type(self):
        store = self._store()
        store.graph.put_edge("a", "b", "explicit")
        store.graph.put_edge("a", "c", "alias")
        store.graph.put_edge("d", "e", "explicit")
        explicit = list(store.graph.iter_edges_by_type("explicit"))
        self.assertCountEqual(explicit, [("a", "b"), ("d", "e")])
        alias = list(store.graph.iter_edges_by_type("alias"))
        self.assertCountEqual(alias, [("a", "c")])

    def test_index_round_trip(self):
        store = self._store()
        store.index.index_name("e1", "attention mechanism")
        candidates = store.index.get_candidates("attention")
        self.assertEqual(candidates, ["e1"])

    def test_index_alias_round_trip(self):
        store = self._store()
        store.index.index_alias("e1", "apex solution")
        candidates = store.index.get_candidates("apex")
        self.assertEqual(candidates, ["e1"])

    def test_index_drop(self):
        store = self._store()
        store.index.index_name("e1", "test name")
        self.assertEqual(store.index.get_candidates("test"), ["e1"])
        store.index.drop_entity_index("e1")
        self.assertEqual(store.index.get_candidates("test"), [])

    def test_state_round_trip(self):
        store = self._store()
        store.state.set("key1", "value1")
        self.assertEqual(store.state.get("key1"), "value1")
        self.assertIsNone(store.state.get("missing"))
        self.assertEqual(store.state.get_int("key1"), None)
        store.state.set("int_key", "42")
        self.assertEqual(store.state.get_int("int_key"), 42)
        store.state.set("float_key", "3.14")
        self.assertEqual(store.state.get_float("float_key"), 3.14)

    def test_content_repo_fs_backed(self):
        store = self._store()
        store.content.put("e1", "hello world")
        self.assertEqual(store.content.get("e1"), "hello world")
        store.content.delete("e1")
        self.assertIsNone(store.content.get("e1"))

    def test_content_repo_size(self):
        store = self._store()
        self.assertEqual(store.content.size(), 0)
        store.content.put("e1", "hello")
        store.content.put("e2", "world")
        self.assertGreater(store.content.size(), 0)

    def test_transaction_rollback_on_error(self):
        store = self._store()
        store.entities.put("e1", name="Keep", slug="keep")
        try:
            with store.transaction():
                store.entities.put("e2", name="Rolled Back", slug="rollback")
                raise ValueError("boom")
        except ValueError:
            pass
        self.assertTrue(store.entities.exists("e1"))
        self.assertFalse(store.entities.exists("e2"))

    def test_transaction_commit(self):
        store = self._store()
        with store.transaction():
            store.entities.put("e1", name="Commited", slug="commited")
        self.assertTrue(store.entities.exists("e1"))

    def test_make_entity_id_deterministic(self):
        from store import make_entity_id
        id1 = make_entity_id("/path/to/file.txt")
        id2 = make_entity_id("/path/to/file.txt")
        self.assertEqual(id1, id2)
        id3 = make_entity_id("/different/path.txt")
        self.assertNotEqual(id1, id3)
        self.assertEqual(len(id1), 32)

    def test_sqlite_store_vacuum(self):
        store = self._store()
        store.vacuum()

    def test_sqlite_store_close_reopen(self):
        store = self._store()
        store.entities.put("e1", name="Persist", slug="persist")
        store.close()
        store2 = self._store()
        loaded = store2.entities.get("e1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["name"], "Persist")
        store2.close()

    def test_memory_store_entity(self):
        from store import MemoryStore
        ms = MemoryStore()
        ms.entities.put("e1", name="Mem", slug="mem")
        self.assertTrue(ms.entities.exists("e1"))
        loaded = ms.entities.get("e1")
        self.assertEqual(loaded["name"], "Mem")

    def test_memory_store_graph(self):
        from store import MemoryStore
        ms = MemoryStore()
        ms.graph.put_edge("a", "b")
        self.assertEqual(ms.graph.get_outgoing("a"), {"b"})
        self.assertEqual(ms.graph.get_edge_count(), 1)

    def test_memory_graph_get_all_outgoing(self):
        from store import MemoryStore
        ms = MemoryStore()
        ms.graph.put_edge("a", "b")
        ms.graph.put_edge("a", "c")
        ms.graph.put_edge("d", "e")
        all_out = ms.graph.get_all_outgoing()
        self.assertEqual(all_out["a"], {"b", "c"})
        self.assertEqual(all_out["d"], {"e"})

    def test_memory_store_content(self):
        from store import MemoryStore
        ms = MemoryStore()
        ms.content.put("e1", "body text")
        self.assertEqual(ms.content.get("e1"), "body text")
        self.assertGreater(ms.content.size(), 0)


class TestStoreMigrations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_schema_version_set_on_open(self):
        from store import SCHEMA_VERSION, SQLiteStore
        db_path = os.path.join(self.tmp, "migrate.db")
        store = SQLiteStore(db_path, cache_dir=self.tmp)
        self.assertEqual(store.state.get_int("schema_version"), SCHEMA_VERSION)
        store.close()

    def test_reopen_keeps_schema_version(self):
        from store import SCHEMA_VERSION, SQLiteStore
        db_path = os.path.join(self.tmp, "reopen.db")
        store = SQLiteStore(db_path, cache_dir=self.tmp)
        store.close()
        store2 = SQLiteStore(db_path, cache_dir=self.tmp)
        self.assertEqual(store2.state.get_int("schema_version"), SCHEMA_VERSION)
        store2.close()

    def test_migration_from_scratch(self):
        from store import SQLiteStore
        db_path = os.path.join(self.tmp, "scratch.db")
        store = SQLiteStore(db_path, cache_dir=self.tmp)
        tables = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r[0] for r in tables}
        for expected in ("compile_state", "entities", "graph_edges",
                         "aliases", "word_index"):
            self.assertIn(expected, table_names)
        store.close()


class TestCompiler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_config_defaults(self):
        from compiler import CompilerConfig
        cfg = CompilerConfig()
        self.assertEqual(cfg.cache_dir, ".cache")
        self.assertEqual(cfg.workers, 1)
        self.assertTrue(cfg.lint)
        self.assertTrue(cfg.incremental)
        self.assertFalse(cfg.parallel)
        self.assertIsNone(cfg.source_provider)

    def test_compile_event_creation(self):
        import time

        from compiler import CompileEvent
        t = time.perf_counter()
        ev = CompileEvent("phase_start", "extract", t,
                          entity_id="abc", elapsed=0.5,
                          payload={"count": 10})
        self.assertEqual(ev.event, "phase_start")
        self.assertEqual(ev.phase, "extract")
        self.assertEqual(ev.entity_id, "abc")
        self.assertEqual(ev.elapsed, 0.5)
        self.assertEqual(ev.payload, {"count": 10})

    def test_change_set_construction(self):
        from compiler import ChangeSet
        cs = ChangeSet(
            added={"a", "b"},
            modified={"c"},
            deleted=set(),
            renamed={"old": "new"},
            unchanged={"d"},
        )
        self.assertEqual(cs.added, {"a", "b"})
        self.assertEqual(cs.modified, {"c"})
        self.assertEqual(cs.deleted, set())
        self.assertEqual(cs.renamed, {"old": "new"})
        self.assertEqual(cs.unchanged, {"d"})

    def test_compile_stats_defaults(self):
        from compiler import CompileStats
        s = CompileStats()
        self.assertEqual(s.entity_count, 0)
        self.assertEqual(s.edge_count, 0)
        self.assertEqual(s.cache_hit_ratio, 0.0)

    def test_compile_result_construction(self):
        from compiler import CompileResult, CompileStats
        from linter import LintReport
        stats = CompileStats(entity_count=5, pages_changed=3, elapsed_s=0.1)
        report = LintReport(total_pages=5)
        result = CompileResult(pages_written=3, lint_report=report, stats=stats)
        self.assertEqual(result.pages_written, 3)
        self.assertIs(result.lint_report, report)
        self.assertIs(result.stats, stats)

    def test_compiler_compile_produces_output(self):
        from compiler import Compiler, CompilerConfig
        raw_dir = os.path.join(self.tmp, "raw")
        out_dir = os.path.join(self.tmp, "out")
        from generator import generate_corpus
        generate_corpus(raw_dir, num_files=10, seed=42)
        compiler = Compiler(CompilerConfig(lint=True))
        result = compiler.compile(raw_dir, out_dir)
        self.assertEqual(result.pages_written, 11)  # 10 content + 1 index
        self.assertIsNotNone(result.lint_report)
        self.assertEqual(result.stats.entity_count, 10)
        self.assertGreater(result.stats.elapsed_s, 0)

    def test_compiler_compile_events_yields_events(self):
        from compiler import Compiler, CompilerConfig
        raw_dir = os.path.join(self.tmp, "raw_events")
        out_dir = os.path.join(self.tmp, "out_events")
        from generator import generate_corpus
        generate_corpus(raw_dir, num_files=5, seed=1)
        compiler = Compiler(CompilerConfig(lint=True))
        events = list(compiler.compile_events(raw_dir, out_dir))
        event_types = {e.event for e in events}
        self.assertIn("phase_start", event_types)
        self.assertIn("phase_end", event_types)
        self.assertIn("extracted", event_types)
        self.assertIn("written", event_types)
        self.assertIn("done", event_types)
        self.assertGreater(len(events), 0)

    def test_compiler_no_lint(self):
        from compiler import Compiler, CompilerConfig
        raw_dir = os.path.join(self.tmp, "raw_nolint")
        out_dir = os.path.join(self.tmp, "out_nolint")
        from generator import generate_corpus
        generate_corpus(raw_dir, num_files=3, seed=7)
        compiler = Compiler(CompilerConfig(lint=False))
        result = compiler.compile(raw_dir, out_dir)
        self.assertIsNone(result.lint_report)

    def test_compiler_graph_report_present(self):
        from compiler import Compiler, CompilerConfig
        raw_dir = os.path.join(self.tmp, "raw_report")
        out_dir = os.path.join(self.tmp, "out_report")
        from generator import generate_corpus
        generate_corpus(raw_dir, num_files=5, seed=1)
        compiler = Compiler(CompilerConfig(lint=False))
        result = compiler.compile(raw_dir, out_dir)
        self.assertIsNotNone(result.graph_report)
        self.assertEqual(result.graph_report.entity_count, 5)
        self.assertGreater(result.graph_report.edge_count, 0)

    def test_compile_wiki_backward_compat(self):
        raw_dir = os.path.join(self.tmp, "raw_bc")
        out_dir = os.path.join(self.tmp, "out_bc")
        from compiler import compile_wiki
        from generator import generate_corpus
        generate_corpus(raw_dir, num_files=10, seed=42)
        result = compile_wiki(raw_dir, out_dir)
        self.assertEqual(len(result["entities"]), 10)
        self.assertEqual(len(result["written_paths"]), 11)  # 10 content + 1 index
        self.assertIsNotNone(result["lint_report"])
        self.assertIn("graph", result)

    def test_new_compiler_produces_same_output_as_wrapper(self):
        from compiler import Compiler, CompilerConfig, compile_wiki
        from generator import generate_corpus
        raw1 = os.path.join(self.tmp, "cmp1")
        out1 = os.path.join(self.tmp, "out1")
        raw2 = os.path.join(self.tmp, "cmp2")
        out2 = os.path.join(self.tmp, "out2")
        generate_corpus(raw1, num_files=5, seed=7)
        generate_corpus(raw2, num_files=5, seed=7)
        old = compile_wiki(raw1, out1, run_lint=True)
        compiler = Compiler(CompilerConfig(lint=True))
        new = compiler.compile(raw2, out2)
        self.assertEqual(len(old["written_paths"]), new.pages_written)
        self.assertEqual(len(old["lint_report"].broken_links),
                         len(new.lint_report.broken_links))
        self.assertEqual(len(old["lint_report"].unreachable_pages),
                         len(new.lint_report.unreachable_pages))

    def test_compiler_with_di(self):
        from compiler import CompilePlanner, Compiler, CompilerConfig
        from source import FilesystemProvider
        planner = CompilePlanner()
        provider = FilesystemProvider()
        compiler = Compiler(
            config=CompilerConfig(lint=False),
            planner=planner,
            source_provider=provider,
        )
        self.assertIs(compiler.planner, planner)
        self.assertIs(compiler._source_provider, provider)


class TestChangeDetector(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, content: str = "Title\n\nbody") -> str:
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_no_store_adds_all_docs(self):
        from compiler import ChangeDetector, ChangeSet
        from source import FilesystemProvider
        from store import MemoryStore
        self._write("a.txt", "# Alpha\n\nhello")
        self._write("b.txt", "# Beta\n\nworld")
        store = MemoryStore()
        detector = ChangeDetector(store)
        result = detector.detect(FilesystemProvider(), self.tmp)
        self.assertIsInstance(result, ChangeSet)
        self.assertEqual(len(result.added), 2)
        self.assertEqual(len(result.modified), 0)
        self.assertEqual(len(result.unchanged), 0)

    def test_all_unchanged_when_store_matches(self):
        import hashlib

        from compiler import ChangeDetector
        from source import FilesystemProvider
        from store import MemoryStore, make_entity_id
        path_a = self._write("a.txt", "# Alpha\n\nhello")
        path_b = self._write("b.txt", "# Beta\n\nworld")
        store = MemoryStore()
        eid_a = make_entity_id(os.path.abspath(path_a))
        eid_b = make_entity_id(os.path.abspath(path_b))
        st_a = os.stat(path_a)
        st_b = os.stat(path_b)
        store.entities.put(eid_a, name="Alpha", slug="alpha",
                           source_path=path_a,
                           source_hash=hashlib.sha256(
                               b"# Alpha\n\nhello").hexdigest(),
                           mtime=st_a.st_mtime, size=st_a.st_size)
        store.entities.put(eid_b, name="Beta", slug="beta",
                           source_path=path_b,
                           source_hash=hashlib.sha256(
                               b"# Beta\n\nworld").hexdigest(),
                           mtime=st_b.st_mtime, size=st_b.st_size)
        detector = ChangeDetector(store)
        result = detector.detect(FilesystemProvider(), self.tmp)
        self.assertEqual(len(result.added), 0)
        self.assertEqual(len(result.modified), 0)
        self.assertEqual(len(result.unchanged), 2)
        self.assertEqual(len(result.deleted), 0)

    def test_modified_detected_via_hash(self):
        from compiler import ChangeDetector
        from source import FilesystemProvider
        from store import MemoryStore, make_entity_id
        path = self._write("a.txt", "# Alpha\n\nhello")
        st = os.stat(path)
        store = MemoryStore()
        eid = make_entity_id(os.path.abspath(path))
        # Different content hash (change content, force mtime/size mismatch)
        store.entities.put(eid, name="Alpha", slug="alpha",
                           source_path=path,
                           source_hash="old_hash_value",
                           mtime=st.st_mtime - 999, size=st.st_size + 1)
        detector = ChangeDetector(store)
        result = detector.detect(FilesystemProvider(), self.tmp)
        self.assertIn(eid, result.modified)

    def test_modified_detected_via_mtime_change(self):
        import hashlib

        from compiler import ChangeDetector
        from source import FilesystemProvider
        from store import MemoryStore, make_entity_id
        path = self._write("a.txt", "# Alpha\n\nhello")
        st = os.stat(path)
        store = MemoryStore()
        eid = make_entity_id(os.path.abspath(path))
        # Store with same hash but different mtime — triggers re-hash
        store.entities.put(eid, name="Alpha", slug="alpha",
                           source_path=path,
                           source_hash=hashlib.sha256(
                               b"# Alpha\n\nhello").hexdigest(),
                           mtime=st.st_mtime - 9999, size=st.st_size)
        detector = ChangeDetector(store)
        result = detector.detect(FilesystemProvider(), self.tmp)
        self.assertIn(eid, result.unchanged,  # hash still matches
                      msg="same content → unchanged despite mtime change")

    def test_deleted_detected(self):
        from compiler import ChangeDetector
        from source import FilesystemProvider
        from store import MemoryStore, make_entity_id
        path = self._write("a.txt", "# Alpha\n\nhello")
        store = MemoryStore()
        eid = make_entity_id(os.path.abspath(path))
        store.entities.put(eid, name="Alpha", slug="alpha", source_path=path)
        os.remove(path)
        detector = ChangeDetector(store)
        result = detector.detect(FilesystemProvider(), self.tmp)
        self.assertIn(eid, result.deleted)

    def test_version_stale_triggers_modified(self):
        from compiler import ChangeDetector
        from source import FilesystemProvider
        from store import (
            CURRENT_COMPILER_VERSION,
            MemoryStore,
            make_entity_id,
        )
        path = self._write("a.txt", "# Alpha\n\nhello")
        st = os.stat(path)
        store = MemoryStore()
        eid = make_entity_id(os.path.abspath(path))
        store.entities.put(eid, name="Alpha", slug="alpha",
                           source_path=path,
                           compiler_version="0.9.0",  # stale
                           extractor_version=CURRENT_COMPILER_VERSION,
                           tokenizer_version=CURRENT_COMPILER_VERSION,
                           mtime=st.st_mtime, size=st.st_size)
        detector = ChangeDetector(store)
        result = detector.detect(FilesystemProvider(), self.tmp)
        self.assertIn(eid, result.modified)

    def test_added_after_initial_populate(self):
        import hashlib

        from compiler import ChangeDetector
        from source import FilesystemProvider
        from store import MemoryStore, make_entity_id
        path_a = self._write("a.txt", "# Alpha\n\nhello")
        store = MemoryStore()
        eid_a = make_entity_id(os.path.abspath(path_a))
        st_a = os.stat(path_a)
        store.entities.put(eid_a, name="Alpha", slug="alpha",
                           source_path=path_a,
                           source_hash=hashlib.sha256(
                               b"# Alpha\n\nhello").hexdigest(),
                           mtime=st_a.st_mtime, size=st_a.st_size)
        # Add second file after store is populated
        self._write("b.txt", "# Beta\n\nworld")
        detector = ChangeDetector(store)
        result = detector.detect(FilesystemProvider(), self.tmp)
        self.assertEqual(len(result.added), 1)
        self.assertEqual(len(result.unchanged), 1)


class TestCompilePlannerWithStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, content: str = "Title\n\nbody") -> str:
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_detect_changes_with_store(self):
        from compiler import CompilePlanner, CompilerConfig
        from source import FilesystemProvider
        from store import MemoryStore
        self._write("a.txt", "# Alpha\n\nhello")
        store = MemoryStore()
        planner = CompilePlanner(CompilerConfig(), store=store)
        cs = planner.detect_changes(FilesystemProvider(), self.tmp)
        self.assertEqual(len(cs.added), 1)

    def test_detect_changes_without_store(self):
        from compiler import CompilePlanner, CompilerConfig
        from source import FilesystemProvider
        self._write("a.txt", "# Alpha\n\nhello")
        planner = CompilePlanner(CompilerConfig(), store=None)
        cs = planner.detect_changes(FilesystemProvider(), self.tmp)
        self.assertEqual(len(cs.added), 1)

    def test_remove_deleted_cleans_up_everything(self):
        from compiler import CompilePlanner, CompilerConfig
        from extractor import extract_entity
        from graph import build_graph
        from rewriter import compile_pages
        from store import MemoryStore
        path = self._write("a.txt", "# Alpha\n\nhello")
        entity = extract_entity(path)
        store = MemoryStore()
        store.entities.put(entity.entity_id, name=entity.name, slug=entity.slug,
                           source_path=path)
        planner = CompilePlanner(CompilerConfig(), store=store)
        out_dir = os.path.join(self.tmp, "out")
        os.makedirs(out_dir, exist_ok=True)
        compile_pages({entity.entity_id: entity}, build_graph({entity.entity_id: entity}), out_dir)
        self.assertTrue(os.path.exists(os.path.join(out_dir, f"{entity.slug}.md")))
        planner.remove_deleted({entity.entity_id}, out_dir)
        self.assertFalse(store.entities.exists(entity.entity_id))
        self.assertFalse(os.path.exists(os.path.join(out_dir, f"{entity.slug}.md")))

    def test_compiler_with_store_accepts_store(self):
        from compiler import Compiler, CompilerConfig
        from store import MemoryStore
        store = MemoryStore()
        compiler = Compiler(config=CompilerConfig(lint=False), store=store)
        self.assertIs(compiler._store, store)

    def test_compiler_with_store_runs_pipeline(self):
        from compiler import Compiler, CompilerConfig
        from generator import generate_corpus
        from store import MemoryStore
        raw = os.path.join(self.tmp, "raw")
        out = os.path.join(self.tmp, "out")
        os.makedirs(raw, exist_ok=True)
        generate_corpus(raw, num_files=3, seed=5)
        store = MemoryStore()
        compiler = Compiler(config=CompilerConfig(lint=False), store=store)
        result = compiler.compile(raw, out)
        self.assertEqual(result.pages_written, 4)  # 3 content + 1 index

    def test_compiler_with_no_store_backward_compat(self):
        from compiler import Compiler, CompilerConfig
        compiler = Compiler(config=CompilerConfig())
        self.assertIsNone(compiler._store)


class TestGraphBuilder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_graph_builder_result_defaults(self):
        from graph import GraphBuilderResult
        r = GraphBuilderResult()
        self.assertEqual(r.edge_count, 0)
        self.assertEqual(r.elapsed_s, 0.0)
        self.assertEqual(r.graph, {})

    def test_word_index_builder_builds_graph(self):
        import os

        from compiler import ChangeSet
        from extractor import extract_entity
        from graph import WordIndexGraphBuilder
        from store import MemoryStore
        raw = os.path.join(self.tmp, "raw")
        os.makedirs(raw, exist_ok=True)
        a_path = os.path.join(raw, "a.txt")
        with open(a_path, "w") as f:
            f.write("# Alpha\n\nHello from Alpha talking about [[Beta]].")
        b_path = os.path.join(raw, "b.txt")
        with open(b_path, "w") as f:
            f.write("# Beta\n\nBeta mentions [[Alpha]] back.")
        ea = extract_entity(a_path)
        eb = extract_entity(b_path)
        entities = {ea.entity_id: ea, eb.entity_id: eb}
        store = MemoryStore()
        store.entities.put(ea.entity_id, name=ea.name, slug=ea.slug,
                           source_path=a_path)
        store.entities.put(eb.entity_id, name=eb.name, slug=eb.slug,
                           source_path=b_path)
        store.content.put(ea.entity_id, ea.body)
        store.content.put(eb.entity_id, eb.body)
        builder = WordIndexGraphBuilder()
        changes = ChangeSet(added={ea.entity_id, eb.entity_id})
        result = builder.build(changes, store, entities)
        self.assertGreater(result.edge_count, 0)
        self.assertGreater(result.changed_edges, 0)
        self.assertIn(ea.entity_id, result.graph)
        self.assertIn(eb.entity_id, result.graph)

    def test_builder_persists_edges_to_store(self):
        from compiler import ChangeSet
        from extractor import extract_entity
        from graph import WordIndexGraphBuilder
        from store import MemoryStore
        raw = os.path.join(self.tmp, "raw")
        os.makedirs(raw, exist_ok=True)
        a_path = os.path.join(raw, "a.txt")
        with open(a_path, "w") as f:
            f.write("# Alpha\n\nHello from [[Beta]].")
        b_path = os.path.join(raw, "b.txt")
        with open(b_path, "w") as f:
            f.write("# Beta\n\nBeta body.")
        ea = extract_entity(a_path)
        eb = extract_entity(b_path)
        entities = {ea.entity_id: ea, eb.entity_id: eb}
        store = MemoryStore()
        store.entities.put(ea.entity_id, name=ea.name, slug=ea.slug,
                           source_path=a_path)
        store.entities.put(eb.entity_id, name=eb.name, slug=eb.slug,
                           source_path=b_path)
        store.content.put(ea.entity_id, ea.body)
        store.content.put(eb.entity_id, eb.body)
        builder = WordIndexGraphBuilder()
        changes = ChangeSet(added={ea.entity_id, eb.entity_id})
        builder.build(changes, store, entities)
        self.assertGreater(store.graph.get_edge_count(), 0)

    def test_second_run_no_changes(self):
        from compiler import ChangeSet
        from extractor import extract_entity
        from graph import WordIndexGraphBuilder
        from store import MemoryStore
        raw = os.path.join(self.tmp, "raw")
        os.makedirs(raw, exist_ok=True)
        a_path = os.path.join(raw, "a.txt")
        with open(a_path, "w") as f:
            f.write("# Alpha\n\nHello from [[Beta]].")
        b_path = os.path.join(raw, "b.txt")
        with open(b_path, "w") as f:
            f.write("# Beta\n\nBeta body.")
        ea = extract_entity(a_path)
        eb = extract_entity(b_path)
        entities = {ea.entity_id: ea, eb.entity_id: eb}
        store = MemoryStore()
        store.entities.put(ea.entity_id, name=ea.name, slug=ea.slug,
                           source_path=a_path)
        store.entities.put(eb.entity_id, name=eb.name, slug=eb.slug,
                           source_path=b_path)
        store.content.put(ea.entity_id, ea.body)
        store.content.put(eb.entity_id, eb.body)
        builder = WordIndexGraphBuilder()
        changes = ChangeSet(added={ea.entity_id, eb.entity_id})
        first = builder.build(changes, store, entities)
        # Second run: no changes → no added/modified
        second = builder.build(ChangeSet(added=set(), modified=set()),
                               store, entities)
        # Edge count should be the same since nothing changed
        self.assertEqual(second.edge_count, first.edge_count)

    def test_builder_not_used_when_no_store(self):
        from compiler import CompilePlanner, CompilerConfig
        from extractor import extract_entity
        from graph import build_graph
        planner = CompilePlanner(CompilerConfig(), store=None)
        raw = os.path.join(self.tmp, "raw")
        os.makedirs(raw, exist_ok=True)
        a_path = os.path.join(raw, "a.txt")
        with open(a_path, "w") as f:
            f.write("# Alpha\n\nBody.")
        ea = extract_entity(a_path)
        g = planner.graph({ea.entity_id: ea})
        expected = build_graph({ea.entity_id: ea})
        self.assertEqual(g, expected)

    def test_builder_creates_alias_edges(self):
        from compiler import ChangeSet
        from extractor import extract_entity
        from graph import WordIndexGraphBuilder
        from store import MemoryStore
        raw = os.path.join(self.tmp, "raw")
        os.makedirs(raw, exist_ok=True)
        a_path = os.path.join(raw, "a.txt")
        with open(a_path, "w") as f:
            f.write("# Alpha\naliases: Apex, The Prime\n\nmentions Apex in body.")
        b_path = os.path.join(raw, "b.txt")
        with open(b_path, "w") as f:
            f.write("# Beta\n\nBody.")
        ea = extract_entity(a_path)
        eb = extract_entity(b_path)
        entities = {ea.entity_id: ea, eb.entity_id: eb}
        store = MemoryStore()
        store.entities.put(ea.entity_id, name=ea.name, slug=ea.slug,
                           aliases=", ".join(ea.aliases),
                           source_path=a_path)
        store.entities.put(eb.entity_id, name=eb.name, slug=eb.slug,
                           source_path=b_path)
        store.content.put(ea.entity_id, ea.body)
        store.content.put(eb.entity_id, eb.body)
        builder = WordIndexGraphBuilder()
        changes = ChangeSet(added={ea.entity_id, eb.entity_id})
        result = builder.build(changes, store, entities)
        # Alpha's body mentions "Apex" which is an alias of ... itself,
        # so no ALIAS edge should be created to Beta.
        self.assertEqual(result.edge_count, 0)

    def test_builder_alias_creates_edge_to_other_entity(self):
        from compiler import ChangeSet
        from extractor import extract_entity
        from graph import WordIndexGraphBuilder
        from store import MemoryStore
        raw = os.path.join(self.tmp, "raw")
        os.makedirs(raw, exist_ok=True)
        a_path = os.path.join(raw, "a.txt")
        with open(a_path, "w") as f:
            f.write("# Alpha\n\nmentions Apex in body.")
        b_path = os.path.join(raw, "b.txt")
        with open(b_path, "w") as f:
            f.write("# Beta\naliases: Apex\n\nBody text.")
        ea = extract_entity(a_path)
        eb = extract_entity(b_path)
        entities = {ea.entity_id: ea, eb.entity_id: eb}
        store = MemoryStore()
        store.entities.put(ea.entity_id, name=ea.name, slug=ea.slug,
                           source_path=a_path)
        store.entities.put(eb.entity_id, name=eb.name, slug=eb.slug,
                           aliases=", ".join(eb.aliases),
                           source_path=b_path)
        store.content.put(ea.entity_id, ea.body)
        store.content.put(eb.entity_id, eb.body)
        builder = WordIndexGraphBuilder()
        changes = ChangeSet(added={ea.entity_id, eb.entity_id})
        result = builder.build(changes, store, entities)
        self.assertGreater(result.edge_count, 0)
        # Alpha's body mentions "Apex" which is Beta's alias
        self.assertIn(ea.entity_id, result.graph)
        self.assertIn(eb.entity_id, result.graph)
        self.assertIn(eb.entity_id, result.graph[ea.entity_id]["outgoing"])
        self.assertIn(ea.entity_id, result.graph[eb.entity_id]["incoming"])

    def test_builder_navigation_hubs_add_edges(self):
        from compiler import ChangeSet
        from extractor import extract_entity
        from graph import WordIndexGraphBuilder
        from store import MemoryStore
        raw = os.path.join(self.tmp, "raw")
        os.makedirs(raw, exist_ok=True)
        a_path = os.path.join(raw, "a.txt")
        with open(a_path, "w") as f:
            f.write("# Alpha\n\nmentions Beta.")
        b_path = os.path.join(raw, "b.txt")
        with open(b_path, "w") as f:
            f.write("# Beta\n\nmentions nothing.")
        c_path = os.path.join(raw, "c.txt")
        with open(c_path, "w") as f:
            f.write("# Gamma\n\nmentions Alpha.")
        ea = extract_entity(a_path)
        eb = extract_entity(b_path)
        ec = extract_entity(c_path)
        entities = {ea.entity_id: ea, eb.entity_id: eb, ec.entity_id: ec}
        store = MemoryStore()
        for e, p in [(ea, a_path), (eb, b_path), (ec, c_path)]:
            store.entities.put(e.entity_id, name=e.name, slug=e.slug,
                               source_path=p)
            store.content.put(e.entity_id, e.body)
        builder = WordIndexGraphBuilder(navigation_hubs=1)
        changes = ChangeSet(added={e.entity_id for e in (ea, eb, ec)})
        result = builder.build(changes, store, entities)
        # Beta is mentioned by Alpha → 1 incoming → hub (most linked)
        # Alpha is mentioned by Gamma → 1 incoming
        # At least one NAVIGATION edge was created on top of EXPLICIT
        self.assertGreater(result.edge_count, 1)


class TestParallelExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _corpus(self, n=5):
        raw = os.path.join(self.tmp, "raw")
        os.makedirs(raw, exist_ok=True)
        from generator import generate_corpus
        generate_corpus(raw, num_files=n, seed=42)
        return raw

    def test_sequential_extracts_all_entities(self):
        from compiler import _extract_sequential
        from source import FilesystemProvider
        raw = self._corpus(5)
        docs = list(FilesystemProvider().iter_documents(raw))
        entities = _extract_sequential(docs)
        self.assertEqual(len(entities), 5)
        for eid, ent in entities.items():
            self.assertTrue(ent.name)
            self.assertTrue(ent.body)

    def test_parallel_extracts_all_entities(self):
        from compiler import _extract_parallel
        from source import FilesystemProvider
        raw = self._corpus(5)
        docs = list(FilesystemProvider().iter_documents(raw))
        entities = _extract_parallel(docs, workers=2)
        self.assertEqual(len(entities), 5)
        for eid, ent in entities.items():
            self.assertTrue(ent.name)
            self.assertTrue(ent.body)

    def test_parallel_produces_same_output_as_sequential(self):
        from compiler import _extract_parallel, _extract_sequential
        from source import FilesystemProvider
        raw = self._corpus(5)
        docs = list(FilesystemProvider().iter_documents(raw))
        seq = _extract_sequential(docs)
        par = _extract_parallel(docs, workers=2)
        self.assertEqual(set(seq.keys()), set(par.keys()))
        for eid in seq:
            self.assertEqual(seq[eid].name, par[eid].name)
            self.assertEqual(seq[eid].body, par[eid].body)
            self.assertEqual(seq[eid].slug, par[eid].slug)

    def test_parallel_preserves_order(self):
        from compiler import _extract_parallel, _extract_sequential
        from source import FilesystemProvider
        raw = self._corpus(10)
        docs = list(FilesystemProvider().iter_documents(raw))
        seq = _extract_sequential(docs)
        par = _extract_parallel(docs, workers=3)
        seq_ids = list(seq.keys())
        par_ids = list(par.keys())
        self.assertEqual(seq_ids, par_ids)

    def test_compiler_workers1_uses_sequential(self):
        from compiler import Compiler, CompilerConfig
        raw = self._corpus(5)
        out = os.path.join(self.tmp, "out")
        compiler = Compiler(config=CompilerConfig(workers=1))
        result = compiler.compile(raw, out)
        self.assertEqual(result.pages_written, 6)

    def test_compiler_workers2_produces_same_output(self):
        from compiler import Compiler, CompilerConfig
        raw1 = self._corpus(5)
        out1 = os.path.join(self.tmp, "out1")
        raw2 = os.path.join(self.tmp, "raw2")
        out2 = os.path.join(self.tmp, "out2")
        import shutil
        shutil.copytree(raw1, raw2)
        c1 = Compiler(config=CompilerConfig(workers=1))
        c2 = Compiler(config=CompilerConfig(workers=2))
        r1 = c1.compile(raw1, out1)
        r2 = c2.compile(raw2, out2)
        self.assertEqual(r1.pages_written, r2.pages_written)


class TestPlugin(unittest.TestCase):
    def test_plugin_noop_lifecycle(self):
        from plugin import Plugin
        p = Plugin()
        p.initialize(None)
        p.shutdown()

    def test_txt_extractor_extracts(self):
        from plugin import TxtExtractor
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "a.txt")
        with open(path, "w") as f:
            f.write("# Alpha\n\nhello world")
        ext = TxtExtractor()
        entity = ext.extract(path)
        self.assertEqual(entity.name, "Alpha")
        self.assertEqual(entity.body, "hello world")

    def test_markdown_renderer_renders(self):
        from extractor import extract_entity
        from graph import build_graph
        from plugin import MarkdownRenderer
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "a.txt")
        with open(path, "w") as f:
            f.write("# Alpha\n\nhello")
        entity = extract_entity(path)
        entities = {entity.entity_id: entity}
        graph = build_graph(entities)
        renderer = MarkdownRenderer()
        result = renderer.render(entity, graph[entity.entity_id], entities)
        self.assertIn("# Alpha", result)
        self.assertIn("hello", result)

    def test_wiki_linter_validates(self):
        from plugin import WikiLinter
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "page.md")
        with open(path, "w") as f:
            f.write("# Test\n\nbody")
        report = WikiLinter().validate(tmp)
        self.assertEqual(report.total_pages, 1)

    def test_wiki_link_resolver(self):
        from plugin import WikiLinkResolver
        r = WikiLinkResolver()
        self.assertEqual(r.slugify("Hello World"), "hello_world")
        self.assertEqual(r.slugify("Foo-Bar"), "foo_bar")
        known = {"hello_world", "test"}
        self.assertEqual(r.resolve("Hello World", known), "hello_world")
        self.assertIsNone(r.resolve("Unknown", known))

    def test_graph_builder_is_plugin(self):
        from graph import GraphBuilder
        from plugin import Plugin
        self.assertTrue(issubclass(GraphBuilder, Plugin))

    def test_compiler_initializes_plugins(self):
        from compiler import Compiler, CompilerConfig
        from plugin import Plugin
        class TrackingPlugin(Plugin):
            def __init__(self):
                self.initialized = False
                self.shutdown_called = False
            def initialize(self, config):
                self.initialized = True
            def shutdown(self):
                self.shutdown_called = True

        tp = TrackingPlugin()
        cfg = CompilerConfig(extractors=[tp])
        compiler = Compiler(config=cfg)
        self.assertIn(tp, compiler._plugins)

    def test_compiler_lifecycle_on_compile(self):
        from compiler import Compiler, CompilerConfig
        from plugin import Plugin
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        raw = os.path.join(tmp, "raw")
        out = os.path.join(tmp, "out")
        os.makedirs(raw, exist_ok=True)
        from generator import generate_corpus
        generate_corpus(raw, num_files=3, seed=1)

        class LifecyclePlugin(Plugin):
            def __init__(self):
                self.initialized = False
                self.shutdown_called = False
            def initialize(self, config):
                self.initialized = True
            def shutdown(self):
                self.shutdown_called = True

        tp = LifecyclePlugin()
        compiler = Compiler(config=CompilerConfig(extractors=[tp], lint=False))
        compiler.compile(raw, out)
        self.assertTrue(tp.initialized)
        self.assertTrue(tp.shutdown_called)


class TestSourceProvider(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, content=""):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_filesystem_provider_iterates_supported_formats(self):
        self._write("a.txt", "hello")
        self._write("b.md", "markdown")
        self._write("c.txt", "world")
        self._write("d.xyz", "ignored")
        from source import FilesystemProvider
        provider = FilesystemProvider()
        docs = list(provider.iter_documents(self.tmp))
        self.assertEqual(len(docs), 3)
        paths = {d.path for d in docs}
        self.assertIn(os.path.abspath(os.path.join(self.tmp, "a.txt")), paths)
        self.assertIn(os.path.abspath(os.path.join(self.tmp, "b.md")), paths)
        self.assertIn(os.path.abspath(os.path.join(self.tmp, "c.txt")), paths)

    def test_filesystem_document_properties(self):
        path = self._write("doc.txt", "test content\nline2\n")
        from source import FilesystemDocument
        doc = FilesystemDocument(path)
        self.assertEqual(doc.id, os.path.abspath(path))
        self.assertGreater(doc.size, 0)
        self.assertGreater(doc.mtime, 0)
        self.assertEqual(doc.read_bytes(), b"test content\nline2\n")

    def test_filesystem_provider_empty_dir(self):
        from source import FilesystemProvider
        provider = FilesystemProvider()
        docs = list(provider.iter_documents(self.tmp))
        self.assertEqual(docs, [])


class TestConverter(unittest.TestCase):
    def test_is_supported_txt(self):
        from converter import is_supported
        self.assertTrue(is_supported("foo.txt"))

    def test_is_supported_md(self):
        from converter import is_supported
        self.assertTrue(is_supported("foo.md"))

    def test_is_supported_docx(self):
        from converter import is_supported
        self.assertTrue(is_supported("foo.docx"))

    def test_is_supported_pdf(self):
        from converter import is_supported
        self.assertTrue(is_supported("foo.pdf"))

    def test_is_supported_html(self):
        from converter import is_supported
        self.assertTrue(is_supported("foo.html"))

    def test_is_supported_unknown(self):
        from converter import is_supported
        self.assertFalse(is_supported("foo.xyz"))

    def test_is_supported_no_ext(self):
        from converter import is_supported
        self.assertFalse(is_supported("foo"))

    def test_needs_conversion_txt(self):
        from converter import needs_conversion
        self.assertFalse(needs_conversion("foo.txt"))

    def test_needs_conversion_md(self):
        from converter import needs_conversion
        self.assertFalse(needs_conversion("foo.md"))

    def test_needs_conversion_docx(self):
        from converter import needs_conversion
        self.assertTrue(needs_conversion("foo.docx"))

    def test_needs_conversion_pdf(self):
        from converter import needs_conversion
        self.assertTrue(needs_conversion("foo.pdf"))

    def test_convert_to_text_txt(self):
        from converter import convert_to_text
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "test.txt")
            with open(path, "w") as f:
                f.write("# Hello\nThis is a test.\n## Related\n")
            result = convert_to_text(path)
            self.assertIn("Hello", result)
            self.assertIn("Related", result)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestSourceProviderMultiFormat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_txt_files_yielded(self):
        self._write("a.txt", "# A\nbody\n")
        self._write("b.txt", "# B\nbody\n")
        from source import FilesystemProvider
        docs = list(FilesystemProvider().iter_documents(self.tmp))
        self.assertEqual(len(docs), 2)
        exts = {os.path.splitext(d.path)[1] for d in docs}
        self.assertEqual(exts, {".txt"})

    def test_md_files_yielded(self):
        self._write("a.md", "# A\nbody\n")
        from source import FilesystemProvider
        docs = list(FilesystemProvider().iter_documents(self.tmp))
        self.assertEqual(len(docs), 1)
        self.assertTrue(docs[0].path.endswith(".md"))

    def test_convertible_files_yielded(self):
        self._write("a.docx", "dummy")
        self._write("b.pdf", "dummy")
        from source import FilesystemProvider
        docs = list(FilesystemProvider().iter_documents(self.tmp))
        self.assertEqual(len(docs), 2)
        for d in docs:
            self.assertIn(type(d).__name__,
                          {"FilesystemDocument", "ConvertingDocument"})

    def test_mixed_formats(self):
        self._write("a.txt", "# A\nbody\n")
        self._write("b.docx", "dummy")
        self._write("c.md", "# C\nbody\n")
        self._write("d.pdf", "dummy")
        self._write("e.xyz", "ignored")
        from source import FilesystemProvider
        docs = list(FilesystemProvider().iter_documents(self.tmp))
        self.assertEqual(len(docs), 4)
        exts = {os.path.splitext(d.path)[1] for d in docs}
        self.assertEqual(exts, {".txt", ".docx", ".md", ".pdf"})


class TestExtractorWithContent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_extract_with_content_param(self):
        from extractor import extract_entity
        path = os.path.join(self.tmp, "test.txt")
        with open(path, "w") as f:
            f.write("some initial content")
        content = "# MyEntity\nCreated: 2024-01-01\nBody text here.\n## Related\n[[Other]]"
        entity = extract_entity(path, content=content)
        self.assertEqual(entity.name, "MyEntity")
        self.assertEqual(entity.created, "2024-01-01")
        self.assertIn("Body text here", entity.body)

    def test_extract_without_content_fallback(self):
        from extractor import extract_entity
        path = os.path.join(self.tmp, "note.txt")
        with open(path, "w") as f:
            f.write("# FileNote\nCreated: 2024-05-05\nRead from file.\n")
        entity = extract_entity(path)
        self.assertEqual(entity.name, "FileNote")
        self.assertEqual(entity.created, "2024-05-05")
        self.assertIn("Read from file", entity.body)

    def test_extract_content_with_title_from_filename(self):
        from extractor import extract_entity
        path = os.path.join(self.tmp, "my_test_doc.txt")
        with open(path, "w") as f:
            f.write("some data")
        content = "Body only\n## Related\n"
        entity = extract_entity(path, content=content)
        self.assertEqual(entity.name, "My Test Doc")





if __name__ == "__main__":
    unittest.main(verbosity=2)
