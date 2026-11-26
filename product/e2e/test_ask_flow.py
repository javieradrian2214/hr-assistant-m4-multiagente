"""Pruebas de punta a punta de la pagina del HR Assistant (modelo simulado)."""
import os
import re

import pytest
from playwright.sync_api import Page, expect

REQUEST_ID_PATTERN = re.compile(r"request_id: \S+")
WRONG_KEY = "this-key-is-not-registered"


def ask(page: Page, text: str) -> None:
    """Escribe una pregunta y la envia con el boton."""
    page.get_by_test_id("question").fill(text)
    page.get_by_test_id("send").click()


@pytest.fixture(name="keyed_page")
def keyed_page_fixture(page: Page) -> Page:
    """Abre la pagina y escribe la clave de la verificacion."""
    page.goto("/")
    page.get_by_test_id("api-key").fill(os.environ["E2E_API_KEY"])
    return page


def test_page_shows_empty_conversation_and_password_key_field(keyed_page: Page):
    expect(keyed_page.get_by_test_id("question")).to_be_visible()
    expect(keyed_page.get_by_test_id("send")).to_be_enabled()
    expect(keyed_page.get_by_test_id("api-key")).to_have_attribute("type", "password")
    expect(keyed_page.get_by_test_id("answer")).to_have_text("")


def test_asking_a_question_shows_it_in_the_conversation_and_clears_the_input(
    keyed_page: Page,
):
    ask(keyed_page, "How many vacation days does Ana have?")
    expect(keyed_page.get_by_test_id("answer")).to_contain_text(
        "How many vacation days does Ana have?"
    )
    expect(keyed_page.get_by_test_id("question")).to_have_value("")


def test_asking_a_question_shows_an_answer_with_its_request_id(keyed_page: Page):
    ask(keyed_page, "How many vacation days does Ana have?")
    expect(keyed_page.get_by_test_id("answer")).to_contain_text(REQUEST_ID_PATTERN)


def test_empty_question_shows_an_error_message_in_spanish(keyed_page: Page):
    ask(keyed_page, "   ")
    expect(keyed_page.get_by_test_id("answer")).to_contain_text("Escribe una pregunta.")
    expect(keyed_page.get_by_test_id("answer")).not_to_contain_text("request_id")


def test_second_question_keeps_the_previous_conversation_on_screen(keyed_page: Page):
    answer = keyed_page.get_by_test_id("answer")
    ask(keyed_page, "First question about vacations")
    expect(answer).to_contain_text(REQUEST_ID_PATTERN)
    ask(keyed_page, "Second question about salaries")
    expect(answer).to_contain_text("Second question about salaries")
    expect(answer).to_contain_text("First question about vacations")
    expect(answer).to_contain_text(
        re.compile(r"request_id: \S+[\s\S]*request_id: \S+")
    )


def test_wrong_api_key_shows_invalid_key_message(page: Page):
    page.goto("/")
    page.get_by_test_id("api-key").fill(WRONG_KEY)
    ask(page, "How many vacation days does Ana have?")
    expect(page.get_by_test_id("answer")).to_contain_text("Clave inválida")
    expect(page.get_by_test_id("answer")).not_to_contain_text(REQUEST_ID_PATTERN)
