Feature: Multi-agent orchestration with guards
  In multi mode a deterministic supervisor sends each question to one
  specialist. Input and output guards run in both modes, and POST /ask keeps
  its contract while adding the mode and the agents that ran.

  Scenario Outline: The employee question keeps the same contract in both modes
    Given the assistant is running in <mode> mode
    When the user asks "¿Quién es EMP-0004?"
    Then the response status is 200
    And the steps are 2 and the tools used are "get_employee"
    And the answer mentions "Jorge Díaz"
    And the mode is "<mode>" and the agents are "<agents>"

    Examples:
      | mode   | agents        |
      | single | Agent         |
      | multi  | EmployeeAgent |

  Scenario: A department question goes to the department specialist
    Given the assistant is running in multi mode
    When the user asks "¿Quién trabaja en Finanzas?"
    Then the agents are "DepartmentAgent"
    And the steps are 2 and the tools used are "search_by_department"

  Scenario: A comparison goes to the analyst with the large model
    Given the assistant is running in multi mode
    When the user asks "Compara EMP-0001 y EMP-0002"
    Then the agents are "AnalystAgent"
    And the model used is the large model

  Scenario: A question that matches no rule goes to the analyst with the router model
    Given the assistant is running in multi mode
    When the user asks "Hello there"
    Then the agents are "AnalystAgent"
    And the model used is the small model
    And the answer is the help message

  Scenario Outline: Text that impersonates a tool result is rejected
    Given the assistant is running in <mode> mode
    When the user sends the tool result prefix in the <place>
    Then the response status is 422
    And the detail is "invalid input"

    Examples:
      | mode   | place    |
      | single | question |
      | single | history  |
      | multi  | question |
      | multi  | history  |

  Scenario: A contaminated answer is redacted and can be sent back as history
    Given the assistant is running in multi mode with a model that leaks the prefix and an API key
    When the user asks "Hello there"
    Then the answer contains "[REDACTED]"
    And the answer has neither the tool result prefix nor the API key
    When the user sends that answer back as history
    Then the response status is 200

  Scenario: A failing model in multi mode returns a 502
    Given the assistant is running in multi mode with a model that is down
    When the user asks "¿Quién es EMP-0004?"
    Then the response status is 502
    And the metrics count 1 error for "EmployeeAgent"

  Scenario: Metrics report agents and guards without losing the old keys
    Given the assistant is running in multi mode
    When the user asks "¿Quién es EMP-0004?"
    And the user sends the tool result prefix in the question
    Then the metrics count 1 run for "EmployeeAgent"
    And the metrics count 1 rejected input
    And the metrics still have the keys of the previous sessions
