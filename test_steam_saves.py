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
        data["items"]["123"][app.SYSTEM] = str(self.shared)
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

    def file_item(self):
        a = self.write(self.root / "single-a", "save avulso", "windows-slot.sav")
        b = self.root / "single-b" / "linux-slot.dat"
        b.parent.mkdir()
        app.add_item(self.ca, "avulso", kind="file", name="Meu jogo — slot 1",
                     **{app.SYSTEM: str(a)})
        app.add_item(self.cb, "avulso", kind="file", **{app.SYSTEM: str(b)})
        return a, b

    def test_individual_file_round_trip_different_names_and_backup(self):
        a, b = self.file_item()
        neighbor = self.write(b.parent, "não incluir", "outro-slot.sav")
        self.sync(game="avulso")
        self.sync("b", "receber", game="avulso")
        self.assertEqual(self.text(b), "save avulso")
        self.assertEqual(self.text(neighbor), "não incluir")
        b.write_text("progresso outro sistema", encoding="utf-8")
        self.sync("b", game="avulso")
        self.sync("a", game="avulso")
        self.assertEqual(self.text(a), "progresso outro sistema")
        shared = self.vault / "games" / "avulso"
        self.assertEqual([p.name for p in shared.iterdir()], ["save"])
        backups = [self.text(p) for p in (self.vault / "backups" / "avulso").rglob("save")]
        self.assertIn("save avulso", backups)

    def test_individual_file_dry_run_does_not_write_anything(self):
        self.file_item()
        before = sorted(str(p) for p in self.root.rglob("*"))
        self.sync(game="avulso", dry_run=True)
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob("*")))

    def test_file_with_changes_on_both_sides_requires_direction(self):
        a, b = self.file_item()
        self.sync(game="avulso")
        self.sync("b", "receber", game="avulso")
        a.write_text("local A", encoding="utf-8")
        b.write_text("local B", encoding="utf-8")
        self.sync("b", game="avulso")
        with self.assertRaisesRegex(app.SaveError, "Conflito"):
            self.sync("a", game="avulso")
        self.assertEqual(self.text(a), "local A")
        self.sync("a", "receber", game="avulso")
        self.assertEqual(self.text(a), "local B")
        self.assertIn("local A", [self.text(p) for p in (self.vault / "backups" / "avulso").rglob("save")])

    def test_arbitrary_name_optional_platform_and_editable_path(self):
        original = self.write(self.root / "gog", "GOG save")
        updated = self.write(self.root / "emulador", "save diferente")
        app.add_item(self.ca, "livre", name="Ação / aventura — perfil de teste", platform="GOG",
                     **{app.SYSTEM: str(original.parent)})
        app.add_item(self.ca, "livre", name="Meu emulador", platform="", must_exist=True,
                     **{app.SYSTEM: str(updated.parent)})
        entry = app.read_config(self.ca)["items"]["livre"]
        self.assertEqual(entry["name"], "Meu emulador")
        self.assertEqual(entry["platform"], "")
        self.assertEqual(entry[app.SYSTEM], str(updated.parent))
        self.sync(game="livre")
        self.assertEqual(self.text(self.vault / "games" / "livre" / "slot.sav"), "save diferente")
        self.assertEqual(self.text(original), "GOG save")

    def test_multiple_selected_items_exclude_unselected_conflict(self):
        self.write(self.a, "local conflitante")
        self.write(self.save.parent, "compartilhado conflitante")
        a, _ = self.file_item()
        independent = self.write(self.root / "epic", "epic save")
        app.add_item(self.ca, "epic", platform="Epic Games", **{app.SYSTEM: str(independent.parent)})
        self.sync(game=["avulso", "epic"])
        self.assertEqual(self.text(self.save), "compartilhado conflitante")
        self.assertEqual(self.text(self.vault / "games" / "avulso" / "save"), self.text(a))
        self.assertEqual(self.text(self.vault / "games" / "epic" / "slot.sav"), "epic save")

    def test_unconfigured_other_system_does_not_block_current_items(self):
        other = "linux" if app.SYSTEM == "windows" else "windows"
        app.add_item(self.ca, "outro-sistema", **{other: "/example/not-local"})
        self.write(self.a, "local")
        self.sync()
        self.assertTrue(self.save.exists())
        self.assertFalse((self.vault / "games" / "outro-sistema").exists())
        with self.assertRaisesRegex(app.SaveError, "Configure o caminho"):
            self.sync(game="outro-sistema")

    def test_unselected_missing_folder_does_not_block_chosen_item(self):
        self.a.rmdir()
        self.file_item()
        self.sync(game="avulso")
        self.assertTrue((self.vault / "games" / "avulso" / "save").exists())

    def test_legacy_config_read_and_dry_run_preserve_original_bytes(self):
        config = app.read_config(self.ca)
        legacy = {"version": 1, "shared": config["shared"], "games": {"123": {app.SYSTEM: str(self.a)}}}
        app.write_json(self.ca, legacy)
        self.write(self.a, "antigo")
        before = self.ca.read_bytes()
        self.sync(dry_run=True)
        self.assertEqual(self.ca.read_bytes(), before)
        self.sync()
        self.assertEqual(self.text(self.save), "antigo")
        app.add_item(self.ca, "123", name="Nome novo", platform="GOG")
        result = app.read_json(self.ca)
        self.assertEqual(result["version"], 2)
        self.assertNotIn("games", result)
        self.assertEqual(result["items"]["123"][app.SYSTEM], str(self.a))
        self.assertEqual(self.text(self.save), "antigo")

    def test_type_cannot_be_changed_for_an_existing_id(self):
        with self.assertRaisesRegex(app.SaveError, "outro ID"):
            app.add_item(self.ca, "123", kind="file")

    def test_separate_configs_cannot_use_conflicting_storage_types(self):
        self.write(self.a, "folder save")
        self.sync()
        file = self.write(self.root / "standalone", "single save")
        config = app.read_config(self.cb)
        config["items"]["123"] = {"kind": "file", app.SYSTEM: str(file)}
        app.write_json(self.cb, config)
        with self.assertRaisesRegex(app.SaveError, "Tipo diferente"):
            self.sync("b", "enviar")
        self.assertEqual(self.text(self.save), "folder save")

    def test_file_cannot_take_over_legacy_folder_without_marker(self):
        file = self.write(self.root / "standalone", "single save")
        app.add_item(self.ca, "single", kind="file", **{app.SYSTEM: str(file)})
        self.write(self.vault / "games" / "single", "legacy folder", "save")
        with self.assertRaisesRegex(app.SaveError, "pasta de saves anterior"):
            self.sync(game="single")

    def test_file_item_rejects_folder_and_folder_rejects_file(self):
        file = self.write(self.root / "standalone", "single")
        with self.assertRaisesRegex(app.SaveError, "um arquivo"):
            app.add_item(self.ca, "bad-file", kind="file", **{app.SYSTEM: str(self.a)})
        with self.assertRaisesRegex(app.SaveError, "uma pasta"):
            app.add_item(self.ca, "bad-folder", kind="folder", **{app.SYSTEM: str(file)})

    def test_parse_multiple_selection_duplicates_cancel_and_invalid_input(self):
        ids = ["gog", "epic", "livre"]
        self.assertEqual(app.parse_selection("3,1,3", ids), ["livre", "gog"])
        self.assertEqual(app.parse_selection("", ids), ids)
        self.assertEqual(app.parse_selection("0", ids), [])
        for value in ["4", "1,0", "-1", "id", "1.5"]:
            with self.subTest(value=value), self.assertRaises(app.SaveError):
                app.parse_selection(value, ids)

    def test_native_picker_choice_and_cancellation(self):
        with patch("builtins.input", return_value="?"), patch.object(app, "pick_path", return_value=str(self.a)):
            self.assertEqual(app.prompt_path("folder"), str(self.a))
        with patch("builtins.input", return_value="?"), patch.object(app, "pick_path", return_value=""):
            with self.assertRaisesRegex(app.SaveError, "cancelado"):
                app.prompt_path("file")

    def test_graphical_picker_missing_tk_has_manual_fallback_message(self):
        with patch.dict("sys.modules", {"tkinter": None}):
            with self.assertRaisesRegex(app.SaveError, "Digite ou cole"):
                app.pick_path("file")

    def test_menu_edit_changes_name_platform_and_local_path(self):
        updated = self.root / "novo caminho"
        updated.mkdir()
        answers = ["8", "1", "Meu jogo independente", "-", str(updated), "7", "0"]
        with patch("builtins.input", side_effect=answers):
            app.menu(self.ca, self.sa)
        entry = app.read_config(self.ca)["items"]["123"]
        self.assertEqual(entry["name"], "Meu jogo independente")
        self.assertEqual(entry["platform"], "")
        self.assertEqual(entry[app.SYSTEM], str(updated))
        self.assertFalse(self.save.exists())

    def test_menu_default_selection_ignores_other_system_only(self):
        other = "linux" if app.SYSTEM == "windows" else "windows"
        app.add_item(self.ca, "outro-sistema", **{other: "example"})
        with patch("builtins.input", return_value=""):
            self.assertEqual(app.choose_items(self.ca, available_only=True), ["123"])

    def test_cli_metadata_and_multi_item_sync(self):
        file = self.write(self.root / "standalone", "single")
        code = app.main(["--config", str(self.ca), "adicionar", "cli", "--nome", "Jogo sem loja",
                         "--plataforma", "", "--tipo", "arquivo", "--" + app.SYSTEM, str(file)])
        self.assertEqual(code, 0)
        self.write(self.a, "folder")
        code = app.main(["--config", str(self.ca), "--state-dir", str(self.sa), "sync", "123", "cli"])
        self.assertEqual(code, 0)
        self.assertEqual(self.text(self.vault / "games" / "cli" / "save"), "single")
        self.assertEqual(self.text(self.save), "folder")

    def test_menu_new_file_item_with_generated_id_and_no_platform(self):
        file = self.write(self.root / "standalone", "single")
        answers = ["Minha aventura — slot 1", "", "", "2", "?"]
        with patch("builtins.input", side_effect=answers), patch.object(app, "pick_path", return_value=str(file)):
            app.edit_item_menu(self.ca)
        item = app.read_config(self.ca)["items"]["minha-aventura-slot-1"]
        self.assertEqual(item["kind"], "file")
        self.assertEqual(item["platform"], "")
        self.assertEqual(item[app.SYSTEM], str(file))

    def test_edit_preserves_path_of_other_system_and_shared_id(self):
        other = "linux" if app.SYSTEM == "windows" else "windows"
        app.add_item(self.ca, "123", **{other: "other-system-path"})
        before = app.read_config(self.ca)["items"]["123"]
        app.add_item(self.ca, "123", name="Novo nome", **{app.SYSTEM: str(self.b)})
        after = app.read_config(self.ca)["items"]["123"]
        self.assertEqual(after[other], before[other])
        self.assertIn("123", app.read_config(self.ca)["items"])
        self.assertEqual(after[app.SYSTEM], str(self.b))

    def test_cancelled_selection_does_not_start_synchronization(self):
        with patch("builtins.input", side_effect=["4", "0", "0"]), patch.object(app, "synchronize") as sync:
            app.menu(self.ca, self.sa)
        sync.assert_not_called()

    def test_menu_multiple_selection_is_passed_to_sync(self):
        self.file_item()
        with patch("builtins.input", side_effect=["4", "1,2", "0"]), patch.object(app, "synchronize") as sync:
            app.menu(self.ca, self.sa)
        self.assertEqual(sync.call_args.args[3], ["123", "avulso"])

    def test_missing_item_edit_and_unknown_selection_fail_without_changes(self):
        before = self.ca.read_bytes()
        with self.assertRaisesRegex(app.SaveError, "não cadastrado"):
            app.add_item(self.ca, "missing", name="Nome", must_exist=True)
        with self.assertRaisesRegex(app.SaveError, "não cadastrado"):
            self.sync(game=["123", "missing"])
        self.assertEqual(self.ca.read_bytes(), before)
        self.assertFalse(self.save.exists())


if __name__ == "__main__":
    unittest.main()
