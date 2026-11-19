"""Higiene del repositorio antes de publicar: versiones, lanzadores y ningún dato personal."""
import os
import re
import subprocess
import unittest

from comun import RAIZ


def lee(ruta, modo="r"):
    with open(os.path.join(RAIZ, ruta), modo, **({} if "b" in modo else {"encoding": "utf-8"})) as f:
        return f.read()


def archivos_git():
    try:
        salida = subprocess.run(["git", "ls-files", "-s"], cwd=RAIZ, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    filas = [l.split(None, 3) for l in salida.stdout.splitlines()]
    return {f[3]: f[0] for f in filas}


class Versiones(unittest.TestCase):
    def test_la_misma_version_en_todas_partes(self):
        v = lee("app/VERSION").strip()
        self.assertRegex(v, r"^\d+\.\d+\.\d+$")
        self.assertIn(f'version = "{v}"', lee("pyproject.toml"))
        self.assertRegex(lee("uv.lock"), rf'name = "finappgo"\s+version = "{re.escape(v)}"')


class Lanzadores(unittest.TestCase):
    def test_scripts_de_la_web_existen(self):
        html = lee("app/web/index.html")
        for js in re.findall(r'"([a-z]+\.js)"', html):
            with self.subTest(js=js):
                self.assertTrue(js == "datos.js" or os.path.exists(os.path.join(RAIZ, "app", "web", js)))


USUARIO = "danidm" + "98"


class Privacidad(unittest.TestCase):
    def test_mis_datos_fuera_de_git(self):
        self.assertIn("mis_datos/", lee(".gitignore").split())
        modos = archivos_git()
        if modos is None:
            self.skipTest("git no disponible")
        self.assertEqual([a for a in modos if a.startswith("mis_datos")], [])

    def test_ningun_iban_dni_ni_usuario(self):
        modos = archivos_git()
        if modos is None:
            self.skipTest("git no disponible")
        iban = re.compile(r"\bES\d{2}[ ]?(\d{4}[ ]?){5}\b")
        dni = re.compile(r"\b\d{8}[A-HJ-NP-TV-Z]\b")
        for ruta in modos:
            if not ruta.endswith((".py", ".js", ".html", ".json", ".md", ".txt", ".bat", ".command", ".toml", ".yml")):
                continue
            texto = lee(ruta)
            with self.subTest(ruta=ruta):
                self.assertIsNone(iban.search(texto), "parece un IBAN")
                self.assertIsNone(dni.search(texto), "parece un DNI")
                # el usuario va partido para que esta prueba no se encuentre a sí misma
                sin_enlaces = re.sub(r"(github\.com|githubusercontent\.com|ghcr\.io)/" + USUARIO, "", texto)
                self.assertNotIn(USUARIO, sin_enlaces, "el usuario solo puede salir en enlaces al repo")

    def test_prompt_avisa_de_borrar_datos(self):
        self.assertIn("BORRA", lee("app/prompt_ia.txt"))


if __name__ == "__main__":
    unittest.main()
