"""
test_provisioner.py
===================
Pruebas unitarias para las reglas de negocio del provisioner (Fase 3).
Validan la lógica de mapeo y asignación SIN necesidad de una BD real
(se usan mocks y datos en memoria).

Ejecutar:
    cd tests
    python -m pytest test_provisioner.py -v

ISO/IEC 25010 — Dimensiones cubiertas:
  - Idoneidad funcional (las funciones hacen lo que se espera)
  - Fiabilidad (comportamiento ante datos límite y errores)
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call
from datetime import datetime

# Agregar el directorio provision al path para importar el módulo
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "provision"))
import provisioner


# ─────────────────────────────────────────────────────────────────
# Suite 1: Lógica de filtrado de agentes
# ─────────────────────────────────────────────────────────────────

class TestFiltradoAgentes(unittest.TestCase):
    """
    Valida la regla de negocio principal:
    'Solo los usuarios con rol AgenteCallCenter y activo=TRUE
    deben recibir una extensión SIP.'
    """

    def _mock_conn(self, rows):
        """Helper: construye un mock de conexión con datos fijos."""
        conn = MagicMock()
        cur  = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        cur.fetchall.return_value = rows
        return conn, cur

    def test_solo_agentes_activos_son_retornados(self):
        """Un supervisor no debe aparecer en la lista de agentes."""
        rows = [
            {"id": 1, "username": "agente1", "nombre": "Ana", "email": "ana@test.com"},
        ]
        conn, cur = self._mock_conn(rows)
        resultado = provisioner.get_agentes_activos(conn)
        # Verifica que la query filtra por rol y activo
        query_ejecutada = cur.execute.call_args[0][0]
        self.assertIn("rol    = 'AgenteCallCenter'", query_ejecutada)
        self.assertIn("activo = TRUE", query_ejecutada)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["username"], "agente1")

    def test_lista_vacia_cuando_no_hay_agentes(self):
        """Si no hay agentes activos, la función retorna lista vacía."""
        conn, _ = self._mock_conn([])
        resultado = provisioner.get_agentes_activos(conn)
        self.assertEqual(resultado, [])


# ─────────────────────────────────────────────────────────────────
# Suite 2: Asignación de extensiones
# ─────────────────────────────────────────────────────────────────

class TestAsignacionExtension(unittest.TestCase):
    """
    Valida la lógica de asignación de extensiones numéricas
    en el rango [EXTENSION_START, EXTENSION_END].
    """

    def test_asigna_primera_extension_libre(self):
        """Con ninguna extensión en uso, debe asignar la primera del rango."""
        ext = provisioner.siguiente_extension_libre(set())
        self.assertEqual(ext, str(provisioner.EXTENSION_START))

    def test_salta_extensiones_ocupadas(self):
        """Si 1001 y 1002 están ocupadas, debe asignar 1003."""
        en_uso = {"1001", "1002"}
        ext = provisioner.siguiente_extension_libre(en_uso)
        self.assertEqual(ext, "1003")

    def test_extensiones_en_orden_ascendente(self):
        """Las extensiones se asignan en orden numérico ascendente."""
        en_uso = set()
        asignadas = []
        for _ in range(5):
            ext = provisioner.siguiente_extension_libre(en_uso)
            asignadas.append(ext)
            en_uso.add(ext)
        esperadas = [str(provisioner.EXTENSION_START + i) for i in range(5)]
        self.assertEqual(asignadas, esperadas)

    def test_error_cuando_rango_lleno(self):
        """Si todas las extensiones están en uso, debe lanzar RuntimeError."""
        todas = {str(n) for n in range(
            provisioner.EXTENSION_START, provisioner.EXTENSION_END + 1
        )}
        with self.assertRaises(RuntimeError) as ctx:
            provisioner.siguiente_extension_libre(todas)
        self.assertIn("No hay extensiones libres", str(ctx.exception))

    def test_extension_unica_por_agente(self):
        """Dos agentes distintos no deben recibir la misma extensión."""
        en_uso = set()
        ext1 = provisioner.siguiente_extension_libre(en_uso)
        en_uso.add(ext1)
        ext2 = provisioner.siguiente_extension_libre(en_uso)
        self.assertNotEqual(ext1, ext2)


# ─────────────────────────────────────────────────────────────────
# Suite 3: Generación de credenciales SIP
# ─────────────────────────────────────────────────────────────────

class TestGeneracionSipSecret(unittest.TestCase):
    """
    Valida que las contraseñas SIP generadas cumplen con los
    requisitos de seguridad del sistema.
    """

    def test_longitud_minima_de_16(self):
        """La contraseña SIP debe tener al menos 16 caracteres."""
        secret = provisioner.generar_sip_secret("agente1")
        self.assertGreaterEqual(len(secret), 16)

    def test_solo_caracteres_alfanumericos(self):
        """La contraseña SIP solo debe contener letras y números."""
        secret = provisioner.generar_sip_secret("agente1")
        self.assertTrue(secret.isalnum(),
                        f"Contraseña contiene caracteres no alfanuméricos: {secret}")

    def test_determinista_para_mismo_username(self):
        """El mismo username debe siempre producir la misma contraseña (reproducibilidad)."""
        s1 = provisioner.generar_sip_secret("agente1")
        s2 = provisioner.generar_sip_secret("agente1")
        self.assertEqual(s1, s2)

    def test_diferente_para_distintos_usernames(self):
        """Usuarios distintos deben tener contraseñas distintas."""
        s1 = provisioner.generar_sip_secret("agente1")
        s2 = provisioner.generar_sip_secret("agente2")
        self.assertNotEqual(s1, s2)

    def test_no_contiene_username_en_claro(self):
        """La contraseña NO debe contener el username literalmente (seguridad básica)."""
        username = "agente99"
        secret   = provisioner.generar_sip_secret(username)
        self.assertNotIn(username, secret)


# ─────────────────────────────────────────────────────────────────
# Suite 4: Generación de sip_agents.conf
# ─────────────────────────────────────────────────────────────────

class TestGeneracionSipAgentsConf(unittest.TestCase):
    """
    Valida que el archivo sip_agents.conf generado
    tiene el formato correcto para ser leído por Asterisk.
    """

    AGENTES_PRUEBA = [
        {"username": "agente1", "nombre": "Ana Pérez",
         "extension": "1001", "sip_secret": "AbCdEfGhIjKlMnOp"},
        {"username": "agente2", "nombre": "Carlos Ruiz",
         "extension": "1002", "sip_secret": "QrStUvWxYz123456"},
    ]

    def test_contiene_secciones_para_cada_agente(self):
        """El conf generado debe tener una sección [extensión] por agente."""
        conf = provisioner.generar_sip_agents_conf(self.AGENTES_PRUEBA)
        self.assertIn("[1001]", conf)
        self.assertIn("[1002]", conf)

    def test_formato_sip_correcto(self):
        """Cada sección debe incluir type, secret, host, context."""
        conf = provisioner.generar_sip_agents_conf(self.AGENTES_PRUEBA)
        for campo in ["type=friend", "host=dynamic", "context=interno"]:
            self.assertIn(campo, conf, f"Campo requerido '{campo}' no encontrado")

    def test_secreto_correcto_por_extension(self):
        """La contraseña de cada agente debe aparecer junto a su extensión."""
        conf = provisioner.generar_sip_agents_conf(self.AGENTES_PRUEBA)
        # Verificar que el secret de agente1 está en el bloque [1001]
        bloque_1001 = conf.split("[1002]")[0]
        self.assertIn("AbCdEfGhIjKlMnOp", bloque_1001)

    def test_archivo_vacio_cuando_no_hay_agentes(self):
        """Si no hay agentes, el conf debe ser un comentario de cabecera, sin secciones."""
        conf = provisioner.generar_sip_agents_conf([])
        self.assertNotIn("[10", conf)  # No debe haber ninguna sección [10XX]
        self.assertIn("Generado automáticamente", conf)

    def test_agente_sin_nombre_usa_username(self):
        """Si el agente no tiene nombre, se debe usar el username como callerid."""
        agente_sin_nombre = [
            {"username": "agente3", "nombre": None,
             "extension": "1003", "sip_secret": "secret123456789A"},
        ]
        conf = provisioner.generar_sip_agents_conf(agente_sin_nombre)
        self.assertIn("agente3", conf)

    def test_encabezado_contiene_advertencia_no_editar(self):
        """El archivo generado debe tener aviso de que no se edite manualmente."""
        conf = provisioner.generar_sip_agents_conf(self.AGENTES_PRUEBA)
        self.assertIn("NO EDITAR MANUALMENTE", conf)

    def test_contiene_codecs_ulaw_alaw(self):
        """Cada extensión debe tener los codecs de audio configurados."""
        conf = provisioner.generar_sip_agents_conf(self.AGENTES_PRUEBA)
        self.assertIn("allow=ulaw", conf)
        self.assertIn("allow=alaw", conf)


# ─────────────────────────────────────────────────────────────────
# Suite 5: Lógica de sincronización (integración de unidades)
# ─────────────────────────────────────────────────────────────────

class TestLogicaSincronizacion(unittest.TestCase):
    """
    Valida el flujo completo de decisión del ciclo de sincronización
    usando mocks para la BD y el sistema de archivos.
    """

    def _agente(self, id, username):
        return {"id": id, "username": username,
                "nombre": username.title(), "email": f"{username}@test.com"}

    @patch("provisioner.escribir_sip_agents_conf")
    @patch("provisioner.ami_reload_sip", return_value=True)
    @patch("provisioner.registrar_auditoria")
    @patch("provisioner.crear_extension")
    @patch("provisioner.get_extension_existente", return_value=None)
    @patch("provisioner.get_extensiones_en_uso", return_value=set())
    @patch("provisioner.get_agentes_activos")
    def test_agente_nuevo_recibe_extension(
        self, mock_agentes, mock_en_uso, mock_ext_existente,
        mock_crear, mock_auditoria, mock_ami, mock_escribir
    ):
        """Un agente sin extensión previa debe recibir una nueva."""
        mock_agentes.return_value = [self._agente(1, "agente1")]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()

        total = provisioner.sincronizar(conn)

        self.assertEqual(total, 1)
        mock_crear.assert_called_once()
        mock_escribir.assert_called_once()
        mock_ami.assert_called_once()

    @patch("provisioner.escribir_sip_agents_conf")
    @patch("provisioner.ami_reload_sip", return_value=True)
    @patch("provisioner.registrar_auditoria")
    @patch("provisioner.crear_extension")
    @patch("provisioner.get_extension_existente")
    @patch("provisioner.get_extensiones_en_uso", return_value={"1001"})
    @patch("provisioner.get_agentes_activos")
    def test_agente_ya_aprovisionado_no_se_duplica(
        self, mock_agentes, mock_en_uso, mock_ext_existente,
        mock_crear, mock_auditoria, mock_ami, mock_escribir
    ):
        """Un agente ya aprovisionado NO debe generar una nueva extensión."""
        mock_agentes.return_value = [self._agente(1, "agente1")]
        mock_ext_existente.return_value = {
            "extension": "1001", "sip_secret": "existente123456A",
            "estado": "APROVISIONADO"
        }
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()

        provisioner.sincronizar(conn)

        mock_crear.assert_not_called()  # NO debe crear una nueva extensión

    @patch("provisioner.escribir_sip_agents_conf")
    @patch("provisioner.ami_reload_sip", return_value=True)
    @patch("provisioner.registrar_auditoria")
    @patch("provisioner.crear_extension")
    @patch("provisioner.get_extension_existente")
    @patch("provisioner.get_extensiones_en_uso", return_value={"1001"})
    @patch("provisioner.get_agentes_activos")
    def test_extension_desactivada_no_aparece_en_conf(
        self, mock_agentes, mock_en_uso, mock_ext_existente,
        mock_crear, mock_auditoria, mock_ami, mock_escribir
    ):
        """Una extensión en estado DESACTIVADO no debe aparecer en el conf generado."""
        mock_agentes.return_value = [self._agente(1, "agente1")]
        mock_ext_existente.return_value = {
            "extension": "1001", "sip_secret": "abc",
            "estado": "DESACTIVADO"
        }
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()

        total = provisioner.sincronizar(conn)

        # El agente desactivado no suma al total de aprovisionados
        self.assertEqual(total, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
