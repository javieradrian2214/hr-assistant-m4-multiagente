"""Guardas de entrada y salida con detección de PII en código (ADR 0015).

Solo usa ``re`` y la biblioteca estándar. Nunca devuelve ni registra los
valores detectados: solo sus tipos (``email``, ``phone``, ``card`` y
``official_id``).
"""

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List, Optional, Tuple

REDACTED = "[REDACTED]"
ALLOWED = "allowed"
REJECTED = "rejected"
REDACTED_ACTION = "redacted"
PII_TYPES = ("email", "phone", "card", "official_id")

# Prefijo reservado de los resultados de herramienta. Se busca sobre una
# representación auxiliar (ver ``_normalize``) que solo sirve para detectar:
# NFKC, sin marcas combinantes, con los confusables mapeados a ASCII, en
# ``casefold`` y con cada invisible convertido en el separador ``_SEP``. La
# entrada se rechaza y la salida se enmascara con el mismo patrón, así una
# respuesta enmascarada nunca vuelve a provocar un rechazo al reenviarse como
# historial. El texto original no se modifica fuera de la detección.
_TOOL_PREFIX_WORDS = ("resultado", "de", "la", "herramienta")
# Marca interna que reemplaza a cada carácter invisible o de formato. El
# patrón la acepta dentro de una palabra (el invisible se ignora) y entre
# palabras (el invisible cuenta como espacio): así cubre a la vez las dos
# lecturas, "eliminado" y "convertido en espacio".
_SEP = "\x00"
_SEP_RE = r"\x00"
# Letras latinas que se confunden entre sí a la vista (``I`` mayúscula y
# ``l``, ``1``, ``|``; ``o`` y ``0``). Se aceptan solo en el prefijo.
_LATIN_LOOKALIKES = {"i": "[il1|]", "l": "[il1|]", "o": "[o0]"}


def _word_pattern(word: str) -> str:
    """Arma la expresión de una palabra del prefijo con sus parecidos latinos.

    Entre dos letras admite cualquier cantidad de invisibles (``_SEP``).

    :param word: Palabra en minúsculas ASCII.
    :return: Expresión regular de la palabra.
    """
    return (_SEP_RE + "*").join(
        _LATIN_LOOKALIKES.get(char, re.escape(char)) for char in word
    )


# Exige el prefijo completo seguido de dos puntos; entre palabras acepta
# espacios Unicode o invisibles, pero al menos uno.
_TOOL_PREFIX = re.compile(
    rf"[\s{_SEP_RE}]+".join(_word_pattern(word) for word in _TOOL_PREFIX_WORDS)
    + rf"[\s{_SEP_RE}]*:"
)

# Caracteres invisibles que no son de categoría ``Cf`` pero tampoco se ven:
# el combining grapheme joiner, los selectores de variación y los de variante
# libre mongoles. Los de categoría ``Cf`` (U+200B, U+200C, U+200D, U+2060,
# U+00AD, U+FEFF, U+180E, marcas de dirección, etc.) se reconocen por
# categoría.
_EXTRA_INVISIBLE = frozenset(
    [0x034F, *range(0x180B, 0x1810), *range(0xFE00, 0xFE10),
     *range(0xE0100, 0xE01F0)]
)
# Rellenos que se ven como un espacio en blanco: se tratan como espacio.
_SPACE_LIKE = frozenset("ᅟᅠ⠀ㅤﾠ")
# Categorías de marcas combinantes que se quitan en la detección.
_MARK_CATEGORIES = frozenset(("Mn", "Me"))

# Mapeo explícito y acotado de confusables hacia las letras del prefijo
# reservado y sus dos puntos: cirílico, griego, armenio, cherokee, lisu,
# versalitas y letras latinas raras, y signos parecidos a los dos puntos.
# NFKC ya resuelve el ancho completo, los alfanuméricos matemáticos, los
# números romanos y las formas pequeñas (U+FE13, U+FE55, U+FF1A). No es una
# cobertura completa de UTS #39.
_CONFUSABLES = {
    # a
    "а": "a", "А": "a", "α": "a", "Α": "a",
    "ɑ": "a", "ᴀ": "a", "Ꭺ": "a", "ꓮ": "a",
    # d
    "ԁ": "d", "ᴅ": "d", "Ꭰ": "d", "ꓓ": "d",
    # e
    "е": "e", "Е": "e", "ε": "e", "Ε": "e",
    "ҽ": "e", "ᴇ": "e", "Ꭼ": "e", "ꓰ": "e",
    # h
    "һ": "h", "Һ": "h", "Н": "h", "н": "h",
    "Η": "h", "ʜ": "h", "Ꮋ": "h", "ꓧ": "h",
    # i
    "і": "i", "І": "i", "ι": "i", "Ι": "i",
    "ı": "i", "İ": "i", "ɪ": "i", "ɩ": "i",
    "ꓲ": "i",
    # l
    "ӏ": "l", "Ӏ": "l", "ʟ": "l", "ǀ": "l",
    "Ꮮ": "l", "ꓡ": "l",
    # m
    "м": "m", "М": "m", "Μ": "m", "ᴍ": "m",
    "Ꮇ": "m", "ꓟ": "m",
    # n
    "η": "n", "п": "n", "ո": "n", "Ν": "n",
    "ɴ": "n", "ꓠ": "n",
    # o
    "о": "o", "О": "o", "ο": "o", "Ο": "o",
    "օ": "o", "ᴏ": "o", "ꓳ": "o",
    # r
    "г": "r", "ʀ": "r", "ɾ": "r", "Ꭱ": "r",
    "ꓣ": "r",
    # s
    "ѕ": "s", "Ѕ": "s", "ꜱ": "s", "Ꮪ": "s",
    "ꓢ": "s",
    # t
    "т": "t", "Т": "t", "τ": "t", "Τ": "t",
    "ᴛ": "t", "Ꭲ": "t", "ꓔ": "t",
    # u
    "υ": "u", "ս": "u", "ᴜ": "u", "ꓴ": "u",
    # dos puntos
    "ː": ":", "˸": ":", "։": ":", "׃": ":",
    "܃": ":", "܄": ":", "፡": ":", "⁚": ":",
    "∶": ":", "ꓽ": ":", "꞉": ":",
}
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"(?<!\w)(?:\d[ -]?){12,18}\d(?!\w)")
_CURP = re.compile(r"\b[A-Z]{4}\d{6}[HMX][A-Z]{5}[A-Z\d]\d\b", re.IGNORECASE)
_RFC = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z\d]{3}\b", re.IGNORECASE)
_NSS = re.compile(r"(?<!\d)\d{11}(?!\d)")
_PHONE = re.compile(
    r"(?<![\w+])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,3}\)|\d{2,3})[ .-]?"
    r"\d{3,4}[ .-]?\d{4}(?!\w)"
)
_TOKEN = re.compile(r"(?<![\w-])[\w-]{32,}(?![\w-])", re.ASCII)
_PHONE_MIN_DIGITS = 10
_CARD_DIGITS = range(13, 20)


@dataclass(frozen=True)
class GuardReport:
    """Resultado de una guarda, sin valores detectados.

    :param action: ``allowed``, ``rejected`` (entrada) o ``redacted`` (salida).
    :param pii_types: Tipos de PII encontrados, en el orden de ``PII_TYPES``.
    """

    action: str
    pii_types: Tuple[str, ...] = ()


def _digits(text: str) -> str:
    """Deja solo los dígitos del texto.

    :param text: Texto original.
    :return: Los dígitos, en orden.
    """
    return "".join(char for char in text if char.isdigit())


def _luhn(digits: str) -> bool:
    """Comprueba el dígito verificador de Luhn.

    :param digits: Número de tarjeta, solo dígitos.
    :return: ``True`` si el número es válido.
    """
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def _is_card(value: str) -> bool:
    """Indica si el texto es un número de tarjeta válido.

    :param value: Texto que coincidió con el patrón de tarjeta.
    :return: ``True`` si tiene de 13 a 19 dígitos, pasa Luhn y no es una fecha.
    """
    digits = _digits(value)
    return (len(digits) in _CARD_DIGITS and not _ISO_DATE.search(value)
            and _luhn(digits))


def _is_phone(value: str) -> bool:
    """Indica si el texto es un teléfono.

    :param value: Texto que coincidió con el patrón de teléfono.
    :return: ``True`` si tiene 10 dígitos o más y no contiene una fecha.
    """
    return (len(_digits(value)) >= _PHONE_MIN_DIGITS
            and not _ISO_DATE.search(value))


def _always(_value: str) -> bool:
    """Validador que acepta toda coincidencia.

    :param _value: Texto que coincidió (no se usa).
    :return: Siempre ``True``.
    """
    return True


def _has_letter_and_digit(value: str) -> bool:
    """Indica si el texto mezcla letras y dígitos (forma de token).

    :param value: Texto que coincidió con el patrón de token.
    :return: ``True`` si tiene al menos una letra y un dígito.
    """
    return (any(char.isalpha() for char in value)
            and any(char.isdigit() for char in value))


# Orden de aplicación: los identificadores oficiales antes que el teléfono,
# para que un NSS de 11 dígitos se informe como ``official_id``.
_PII_RULES = (
    ("email", _EMAIL, _always),
    ("card", _CARD, _is_card),
    ("official_id", _CURP, _always),
    ("official_id", _RFC, _always),
    ("official_id", _NSS, _always),
    ("phone", _PHONE, _is_phone),
)


def _mask_pii(text: str) -> Tuple[str, Tuple[str, ...]]:
    """Reemplaza la PII por ``[REDACTED]`` y devuelve sus tipos.

    :param text: Texto original.
    :return: Tupla ``(texto_enmascarado, tipos_encontrados)``.
    """
    found = set()
    for pii_type, pattern, is_valid in _PII_RULES:

        def replace(match, pii_type=pii_type, is_valid=is_valid):
            if not is_valid(match.group()):
                return match.group()
            found.add(pii_type)
            return REDACTED

        text = pattern.sub(replace, text)
    return text, tuple(name for name in PII_TYPES if name in found)


def _content(message) -> str:
    """Extrae el texto de un mensaje del historial.

    :param message: Diccionario ``{"role", "content"}`` u objeto con
        ``content``.
    :return: El contenido, o una cadena vacía si no es texto.
    """
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    return content if isinstance(content, str) else ""


def _is_invisible(char: str) -> bool:
    """Indica si el carácter es de formato o de ancho cero.

    :param char: Un carácter.
    :return: ``True`` si es de categoría ``Cf`` o un invisible conocido.
    """
    return (unicodedata.category(char) == "Cf"
            or ord(char) in _EXTRA_INVISIBLE)


def _confusable(char: str) -> str:
    """Traduce un carácter confusable o de relleno a su forma ASCII.

    :param char: Un carácter.
    :return: El carácter equivalente, o el mismo si no está mapeado.
    """
    if char in _SPACE_LIKE:
        return " "
    return _CONFUSABLES.get(char, char)


def _strip_marks(text: str) -> str:
    """Descompone con NFD y quita las marcas combinantes (``Mn`` y ``Me``).

    :param text: Texto auxiliar de detección.
    :return: Texto sin marcas combinantes.
    """
    return "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) not in _MARK_CATEGORIES
    )


@lru_cache(maxsize=4096)
def _fold_char(char: str) -> str:
    """Normaliza un carácter para buscar el prefijo reservado.

    Aplica NFKC; convierte cada invisible en ``_SEP``; quita las marcas
    combinantes (NFD); mapea confusables; aplica ``casefold``; vuelve a
    quitar marcas y a mapear (por si ``casefold`` deja un confusable en
    minúscula o una marca).

    :param char: Un carácter del texto original.
    :return: Cero o más caracteres normalizados.
    """
    out = []
    for piece in unicodedata.normalize("NFKC", char):
        if _is_invisible(piece):
            out.append(_SEP)
            continue
        mapped = "".join(_confusable(base) for base in _strip_marks(piece))
        for folded in _strip_marks(mapped.casefold()):
            out.append(_SEP if _is_invisible(folded) else _confusable(folded))
    return "".join(out)


def _normalize(text: str) -> Tuple[str, Tuple[int, ...]]:
    """Normaliza el texto y guarda de qué carácter original viene cada uno.

    :param text: Texto original.
    :return: Tupla ``(texto_normalizado, posiciones_originales)``.
    """
    chars: List[str] = []
    positions: List[int] = []
    for position, char in enumerate(text):
        for piece in _fold_char(char):
            chars.append(piece)
            positions.append(position)
    return "".join(chars), tuple(positions)


def has_tool_prefix(text: str) -> bool:
    """Indica si el texto contiene el prefijo reservado de herramienta.

    Busca sobre la representación auxiliar de ``_normalize`` del texto y,
    además, del texto con NFKC aplicado completo, para que ni los invisibles
    (eliminados o como separadores), ni las marcas combinantes, ni las
    variantes Unicode, ni los homoglifos mapeados lo oculten. Sigue exigiendo
    el prefijo completo seguido de dos puntos.

    :param text: Texto a revisar.
    :return: ``True`` si aparece el prefijo.
    """
    candidates = (text, unicodedata.normalize("NFKC", text))
    return any(_TOOL_PREFIX.search(_normalize(candidate)[0])
               for candidate in candidates)


def _mask_tool_prefix(text: str) -> str:
    """Reemplaza el prefijo reservado (aunque esté ofuscado) por ``[REDACTED]``.

    Busca con la misma representación auxiliar que ``has_tool_prefix`` y
    reemplaza el tramo original equivalente, incluidos los invisibles, las
    marcas combinantes y los confusables que contenga.

    :param text: Texto original.
    :return: Texto enmascarado.
    """
    normalized, positions = _normalize(text)
    spans: List[List[int]] = []
    for match in _TOOL_PREFIX.finditer(normalized):
        start = positions[match.start()]
        end = positions[match.end() - 1] + 1
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    for start, end in reversed(spans):
        text = text[:start] + REDACTED + text[end:]
    return text


def check_input(question: str, history: Optional[Iterable] = None) -> GuardReport:
    """Guarda de entrada: rechaza el prefijo de herramienta y detecta PII.

    El prefijo en la pregunta o en cualquier mensaje del historial deja
    ``action="rejected"`` (la API responde 422 ``invalid input``). Si no, la
    PII de la pregunta se informa solo por tipos.

    :param question: Pregunta de la persona.
    :param history: Mensajes previos (``{"role", "content"}``) o ``None``.
    :return: ``GuardReport`` con ``allowed`` o ``rejected``.
    """
    texts = [question, *(_content(message) for message in history or [])]
    if any(has_tool_prefix(text) for text in texts):
        return GuardReport(REJECTED)
    _, pii_types = _mask_pii(question)
    return GuardReport(ALLOWED, pii_types)


def _mask_secrets(text: str, secrets: Iterable[str]) -> str:
    """Reemplaza los valores exactos de las claves por ``[REDACTED]``.

    :param text: Texto original.
    :param secrets: Claves configuradas (``API_KEYS``).
    :return: Texto enmascarado.
    """
    values = sorted({s for s in secrets or [] if s and s.strip()},
                    key=len, reverse=True)
    for value in values:
        text = text.replace(value, REDACTED)
    return text


def _mask_tokens(text: str) -> str:
    """Reemplaza los textos con forma de token por ``[REDACTED]``.

    :param text: Texto original.
    :return: Texto enmascarado.
    """
    return _TOKEN.sub(
        lambda match: REDACTED if _has_letter_and_digit(match.group())
        else match.group(),
        text,
    )


def check_output(answer: str, secrets: Iterable[str],
                 max_chars: int) -> Tuple[str, GuardReport]:
    """Guarda de salida: enmascara y después corta.

    Enmascara claves, el prefijo de herramienta, PII y textos con forma de
    token con ``[REDACTED]``; luego corta a ``max_chars`` caracteres.

    :param answer: Respuesta del agente.
    :param secrets: Valores de ``API_KEYS``.
    :param max_chars: Largo máximo de la respuesta (``MAX_ANSWER_CHARS``).
    :return: Tupla ``(texto, GuardReport)`` con ``allowed`` o ``redacted``;
        ``pii_types`` solo lista tipos de PII.
    """
    text = _mask_secrets(answer, secrets)
    text = _mask_tool_prefix(text)
    text, pii_types = _mask_pii(text)
    text = _mask_tokens(text)
    action = REDACTED_ACTION if text != answer else ALLOWED
    return text[:max(max_chars, 0)], GuardReport(action, pii_types)
