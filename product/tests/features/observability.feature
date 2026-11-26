Feature: Observability of every request
  As a support engineer
  I want each request to carry an id, a log trail and metrics
  So that I can tell what happened to any request

  Scenario: A request id is generated when the client sends none
    Given the observed assistant with a clock that advances 1 milliseconds per reading
    When the user asks "¿Quién es EMP-0004?"
    Then the X-Request-ID header is a UUID
    And the body request_id equals the header

  Scenario: The request id sent by the client is kept
    Given the observed assistant with a clock that advances 1 milliseconds per reading
    When the user sends "¿Quién es EMP-0004?" with the request id "demo-123"
    Then the X-Request-ID header is "demo-123"
    And the body request_id equals the header

  Scenario: A validation error still carries the request id and is logged
    Given the observed assistant with a clock that advances 1 milliseconds per reading
    When the user sends an empty question
    Then the response status is 422
    And the X-Request-ID header is present
    And the log has a request event with status 422

  Scenario: One question leaves a trail of events with the same request id
    Given the observed assistant with a clock that advances 1 milliseconds per reading
    When the user asks "¿Quién es EMP-0004?"
    Then the log has the events request, agent_run and audit
    And every log line has the request id of the response
    And the audit event names the tool "get_employee"

  Scenario: The log never contains the question or the answer
    Given the observed assistant with a clock that advances 1 milliseconds per reading
    When the user asks "¿Quién es EMP-0004?"
    Then the log does not contain the question nor the answer

  Scenario: An internal failure gives a safe 500 and an error event
    Given the observed assistant with a broken model
    When the user asks "¿Quién es EMP-0004?"
    Then the response status is 500
    And the body detail is "internal error" with a request id
    And the log has an error event of type "RuntimeError"
    And neither the response nor the log contain "boom-secret"

  Scenario: Metrics count the requests and meet the SLO when the service is fast
    Given the observed assistant with a clock that advances 1 milliseconds per reading
    When the user asks "¿Quién es EMP-0004?"
    And the user asks "Hola"
    Then the metrics show at least 2 requests and positive input tokens
    And the metrics say the SLO is met

  Scenario: Metrics say the SLO is not met when the service is slow
    Given the observed assistant with a clock that advances 5000 milliseconds per reading
    When the user asks "¿Quién es EMP-0004?"
    Then the metrics say the SLO is not met
