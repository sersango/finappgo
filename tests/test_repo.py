import os
import re
import subprocess
import unittest

from support import ROOT


def read(path, mode="r"):
    with open(os.path.join(ROOT, path), mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def archivos_git():
    try:
        output = subprocess.run(["git", "ls-files", "-s"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    rows = [l.split(None, 3) for l in output.stdout.splitlines()]
    return {f[3]: f[0] for f in rows}


class Versions(unittest.TestCase):
    def test_version_numbers_match(self):
        v = read("app/VERSION").strip()
        self.assertRegex(v, r"^\d+\.\d+\.\d+$")
        self.assertIn(f'version = "{v}"', read("pyproject.toml"))
        self.assertRegex(read("uv.lock"), rf'name = "finappgo"\s+version = "{re.escape(v)}"')


class DashboardAssets(unittest.TestCase):
    def test_dashboard_scripts_exist(self):
        html = read("app/web/index.html")
        for js in re.findall(r'"([a-z]+\.js)"', html):
            with self.subTest(js=js):
                self.assertTrue(js == "datos.js" or os.path.exists(os.path.join(ROOT, "app", "web", js)))


USUARIO = "danidm" + "98"


class Privacy(unittest.TestCase):
    def test_excludes_portfolio_data_from_git(self):
        self.assertIn("mis_datos/", read(".gitignore").split())
        modos = archivos_git()
        if modos is None:
            self.skipTest("Git is unavailable")
        self.assertEqual([a for a in modos if a.startswith("mis_datos")], [])

    def test_excludes_personal_identifiers(self):
        modos = archivos_git()
        if modos is None:
            self.skipTest("Git is unavailable")
        iban = re.compile(r"\bES\d{2}[ ]?(\d{4}[ ]?){5}\b")
        dni = re.compile(r"\b\d{8}[A-HJ-NP-TV-Z]\b")
        for path in modos:
            if not path.endswith((".py", ".js", ".html", ".json", ".md", ".txt", ".bat", ".command", ".toml", ".yml")):
                continue
            text = read(path)
            with self.subTest(path=path):
                self.assertIsNone(iban.search(text), "parece un IBAN")
                self.assertIsNone(dni.search(text), "parece un DNI")
                sin_enlaces = re.sub(r"(github\.com|githubusercontent\.com|ghcr\.io)/" + USUARIO, "", text)
                self.assertNotIn(USUARIO, sin_enlaces, "el usuario solo puede salir en enlaces al repo")

    def test_import_prompt_warns_about_personal_data(self):
        self.assertIn("BORRA", read("app/import-prompt.es.txt"))


if __name__ == "__main__":
    unittest.main()
