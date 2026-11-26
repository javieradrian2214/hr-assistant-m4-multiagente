Feature: HR Assistant answers questions about employees

  Scenario: Asking for an employee by id uses get_employee
    Given the assistant is running with a step cap of 3
    When the user asks "Who is EMP-0004?"
    Then the response status is 200
    And the answer contains "Jorge Díaz"
    And the tools used are "get_employee"
    And the number of steps is 2

  Scenario: An unknown employee is reported
    Given the assistant is running with a step cap of 3
    When the user asks "Who is EMP-9999?"
    Then the response status is 200
    And the answer contains "no existe"

  Scenario: Asking for a department uses search_by_department
    Given the assistant is running with a step cap of 3
    When the user asks "Who works in Finanzas?"
    Then the answer contains "Sofía Gómez"
    And the tools used are "search_by_department"

  Scenario: A question without id or department gets a help message
    Given the assistant is running with a step cap of 3
    When the user asks "Hello there"
    Then the answer contains "Pregúntame por un empleado (EMP-0001) o un departamento."
    And the tools used are empty

  Scenario: Reaching the step cap returns the fixed message
    Given the assistant is running with a step cap of 1
    When the user asks "Who is EMP-0004?"
    Then the answer is "No pude completar la respuesta. Intenta con una pregunta más concreta."
    And the number of steps is 1

  Scenario Outline: Invalid questions are rejected
    Given the assistant is running with a step cap of 3
    When the user asks a question of <length> characters
    Then the response status is 422

    Examples:
      | length |
      | 0      |
      | 2001   |

  Scenario: The health endpoint reports the process
    Given the assistant is running with a step cap of 3
    When the client requests "/health"
    Then the response status is 200
    And the health status is ok and has a pid

  Scenario: The home page has the form and is safe
    Given the assistant is running with a step cap of 3
    When the client requests "/"
    Then the response status is 200
    And the page has the test ids question, send and answer
    And the page never uses innerHTML

  Scenario: The history comes from the client and is not stored
    Given the assistant is running with a step cap of 3
    When the user asks "Who is EMP-0004?" with a one message history
    Then the response status is 200
    When the user asks "Hello there"
    Then the answer contains "Pregúntame por un empleado"
