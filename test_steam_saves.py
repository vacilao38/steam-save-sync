"""Testes isolados: nunca acessam saves reais ou o estado pessoal do usuário."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import steam_saves as app


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.shared = self.root / "partição compartilhada"
        self.shared.mkdir()
        self.a = self.root / "Windows Saves"
        self.b = self.root / "Linux Saves"
        self.a.mkdir()
        self.b.mkdir()
        self.ca, self.cb = self.root / "a.json", self.root / "b.json"
        self.sa, self.sb = self.root / "state-a", self.root / "state-b"
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        for config, folder in ((self.ca, self.a), (self.cb, self.b)):
            app.configure(config, str(self.shared))
            app.add_game(config, "123", **{app.SYSTEM: str(folder)})
        self.vault = self.shared / "SteamSavesSync"
        self.save = self.vault / "games" / "123" / "slot.sav"

    def sync(self, side="a", mode="sync", dry_run=False, game=None):
        return app.synchronize(getattr(self, "c" + side), getattr(self, "s" + side), mode, game, dry_run)

    def write(self, folder, text, name="slot.sav"):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def text(self, path):
        return path.read_text(encoding="utf-8")

    def backup_texts(self):
        return [self.text(p) for p in (self.vault / "backups").rglob("*.sav")]

    def seed_both(self):
        self.write(self.a, "início")
        self.sync()
        self.sync("b")

    def test_round_trip_between_two_clients_with_backups(self):
        self.seed_both()
        self.assertEqual(self.text(self.b / "slot.sav"), "início")
        self.write(self.b, "progresso Linux")
        self.sync("b")
        self.sync("a")
        self.assertEqual(self.text(self.a / "slot.sav"), "progresso Linux")
        self.assertIn("início", self.backup_texts())
        self.write(self.a, "progresso Windows")
        self.sync("a")
        self.sync("b")
        self.assertEqual(self.text(self.b / "slot.sav"), "progresso Windows")
        self.assertIn("progresso Linux", self.backup_texts())

    def test_initial_differing_saves_require_explicit_direction(self):
        self.write(self.a, "local")
        self.sync()
        self.write(self.b, "outro")
        with self.assertRaisesRegex(app.SaveError, "Conflito"):
            self.sync("b")
        self.assertEqual(self.text(self.save), "local")
        self.sync("b", "receber")
        self.assertEqual(self.text(self.b / "slot.sav"), "local")
        self.assertIn("outro", self.backup_texts())

    def test_both_changed_blocks_whole_save_even_different_files(self):
        self.seed_both()
        self.write(self.a, "mudança A", "first.sav")
        self.write(self.b, "mudança B", "second.sav")
        self.sync("b")
        with self.assertRaisesRegex(app.SaveError, "Conflito"):
            self.sync("a")
        self.assertFalse((self.a / "second.sav").exists())
        self.assertFalse((self.save.parent / "first.sav").exists())
        self.sync("a", "enviar")
        self.assertIn("mudança B", self.backup_texts())

    def test_deletions_are_not_propagated(self):
        self.seed_both()
        (self.b / "slot.sav").unlink()
        with self.assertRaisesRegex(app.SaveError, "exclusões"):
            self.sync("b")
        self.assertTrue(self.save.exists())
        self.sync("b", "receber")
        self.assertTrue((self.b / "slot.sav").exists())

    def test_destination_only_files_preserved_without_sync_loop(self):
        self.seed_both()
        self.write(self.b, "exclusivo", "extra.sav")
        self.sync("b", "receber")
        self.assertTrue((self.b / "extra.sav").exists())
        self.sync("b")
        self.assertFalse((self.save.parent / "extra.sav").exists())

    def test_dry_run_changes_nothing_including_state_and_locks(self):
        self.write(self.a, "save novo")
        before = sorted(str(p) for p in self.root.rglob("*"))
        self.sync(dry_run=True)
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob("*")))
        self.assertFalse(self.save.exists())
        self.assertFalse(self.sa.exists())

    def test_missing_shared_mount_does_not_create_it(self):
        data = app.read_json(self.ca)
        data["shared"][app.SYSTEM] = str(self.root / "não montado" / "SteamSavesSync")
        app.write_json(self.ca, data)
        with self.assertRaises(OSError):
            self.sync()
        self.assertFalse((self.root / "não montado").exists())

    def test_empty_export_refused(self):
        with self.assertRaisesRegex(app.SaveError, "vazia"):
            self.sync(mode="enviar")
        self.assertFalse(self.save.exists())

    def test_missing_local_directory_requires_explicit_import(self):
        self.write(self.a, "importar")
        self.sync()
        self.b.rmdir()
        with self.assertRaisesRegex(app.SaveError, "não encontrada"):
            self.sync("b")
        self.sync("b", "receber")
        self.assertEqual(self.text(self.b / "slot.sav"), "importar")

    def test_overlap_rejected(self):
        data = app.read_json(self.ca)
        data["games"]["123"][app.SYSTEM] = str(self.shared)
        app.write_json(self.ca, data)
        with self.assertRaisesRegex(app.SaveError, "sobrepostas"):
            self.sync()

    def test_cross_tree_case_collision_rejected(self):
        self.write(self.a, "A", "Save.sav")
        self.write(self.save.parent, "B", "save.sav")
        with self.assertRaisesRegex(app.SaveError, "Colisão"):
            self.sync(mode="enviar")

    def test_file_directory_collision_rejected(self):
        self.write(self.a, "A", "folder")
        self.write(self.save.parent, "B", "folder/slot.sav")
        with self.assertRaisesRegex(app.SaveError, "arquivo e pasta"):
            self.sync(mode="enviar")

    def test_portable_names(self):
        for name in ["CON", "aux.txt", "a:b", "trail.", "a\\b", "LPT1.sav", "foo "]:
            with self.subTest(name=name), self.assertRaises(app.SaveError):
                app.portable_name(name)
        app.portable_name("progresso ação.sav")

    def test_game_path_traversal_rejected(self):
        with self.assertRaises(app.SaveError):
            app.add_game(self.ca, "../escape", **{app.SYSTEM: str(self.a)})

    def test_lock_blocks_execution_and_is_preserved(self):
        (self.vault / ".sync-lock").mkdir()
        self.write(self.a, "save")
        with self.assertRaisesRegex(app.SaveError, "bloqueada"):
            self.sync()
        self.assertTrue((self.vault / ".sync-lock").is_dir())
        self.assertFalse(self.save.exists())

    def test_mutation_during_staging_aborts_before_overwrite(self):
        self.seed_both()
        self.write(self.a, "novo")
        original = app.atomic_copy
        def mutate(source, target, expected):
            original(source, target, expected)
            if ".stage-" in str(target):
                self.write(self.a, "mudou de novo")
        with patch.object(app, "atomic_copy", side_effect=mutate):
            with self.assertRaisesRegex(app.SaveError, "alterados"):
                self.sync()
        self.assertEqual(self.text(self.save), "início")
        self.assertFalse((self.vault / ".sync-lock").exists())

    def test_failure_mid_copy_keeps_full_backup_and_old_state(self):
        self.seed_both()
        self.write(self.a, "novo")
        self.write(self.a, "novo extra", "extra.sav")
        before = next(self.sa.glob("*.json")).read_bytes()
        original = app.atomic_copy
        def fail(source, target, expected):
            if target == self.save.parent / "extra.sav":
                raise OSError("Falha de disco simulada")
            return original(source, target, expected)
        with patch.object(app, "atomic_copy", side_effect=fail):
            with self.assertRaises(OSError):
                self.sync()
        self.assertIn("início", self.backup_texts())
        self.assertEqual(before, next(self.sa.glob("*.json")).read_bytes())

    def test_different_timestamps_do_not_decide_winner(self):
        self.seed_both()
        os.utime(self.a / "slot.sav", (100, 100))
        self.sync()
        self.assertEqual(self.text(self.save), "início")
        self.assertFalse((self.vault / "backups").exists())

    def test_all_games_preflight_before_any_transfer_on_conflict(self):
        self.seed_both()
        self.write(self.a, "novo A")
        other = self.root / "other"
        other.mkdir()
        self.write(other, "save local")
        app.add_game(self.ca, "456", **{app.SYSTEM: str(other)})
        self.write(self.vault / "games" / "456", "save compartilhado")
        with self.assertRaisesRegex(app.SaveError, "Conflito"):
            self.sync()
        self.assertEqual(self.text(self.save), "início")

    def test_cli_reports_invalid_json_without_traceback(self):
        self.ca.write_text("{invalid", encoding="utf-8")
        with redirect_stdout(self.output), patch("sys.stderr", self.output):
            code = app.main(["--config", str(self.ca), "sync"])
        self.assertEqual(code, 2)

    def test_symlink_refused_when_supported(self):
        link = self.a / "link.sav"
        target = self.write(self.root, "não copiar")
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Criação de symlink indisponível nesta conta")
        with self.assertRaisesRegex(app.SaveError, "Link/junction"):
            self.sync()


if __name__ == "__main__":
    unittest.main()
