Feature: Cheaper answers without worse answers
  Each cost lever is observable in the response: the model, the route,
  the cached calls and the cost in dollars.

  Scenario: A simple question uses the small model
    Given the assistant is running with default levers
    When the user asks "Quien es EMP-0004?"
    Then the response status is 200
    And the model used is the small model
    And the route reason is not empty

  Scenario: A question with a keyword uses the large model
    Given the assistant is running with default levers
    When the user asks "Compara a los empleados de Finanzas"
    Then the model used is the large model

  Scenario: With routing off every question uses the large model
    Given the assistant is running with routing off
    When the user asks "Quien es EMP-0004?"
    Then the model used is the large model

  Scenario: Only the last messages of the history reach the model
    Given the assistant is running with a history window of 2
    When the user asks "Quien es EMP-0004?" with a history of 4 messages
    Then the model received the last 2 history messages and the question

  Scenario: A cache hit is counted and costs nothing
    Given the assistant is running with a cache that always hits
    When the user asks "Quien es EMP-0004?"
    Then the cached calls are 1
    And the cost is 0 dollars

  Scenario: A failing model returns a 502 with the request id
    Given the assistant is running with a model that is down
    When the user asks "Quien es EMP-0004?"
    Then the response status is 502
    And the detail is "model unavailable" and the request id is present

  Scenario: Metrics add up the cost of several questions
    Given the assistant is running with default levers
    When the user asks "Quien es EMP-0004?"
    And the user asks "Quien es EMP-0004?"
    Then the metrics cost is twice the cost of one answer
