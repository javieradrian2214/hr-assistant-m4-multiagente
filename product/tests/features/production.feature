Feature: Safe access in production
  As the owner of the service
  I want each client to use its own key, a request limit and startup rules
  So that only known clients spend the model quota and a bad setup never starts

  Scenario: Asking without a key is rejected
    Given the secured assistant allowing 3 requests per minute
    When the user asks without a key
    Then the response status is 401
    And the body detail is "invalid or missing API key"

  Scenario: Metrics with a wrong key are rejected
    Given the secured assistant allowing 3 requests per minute
    When the user requests "/metrics" with the key "not-a-real-key-000000"
    Then the response status is 401
    And the body detail is "invalid or missing API key"

  Scenario: A valid key gets an answer
    Given the secured assistant allowing 3 requests per minute
    When the client "alice" asks "¿Quién es EMP-0004?"
    Then the response status is 200

  Scenario: The page, the health check and the docs need no key
    Given the secured assistant allowing 3 requests per minute
    When the user requests the public paths without a key
    Then all the public responses have status 200

  Scenario: Exceeding the limit gives 429 with Retry-After
    Given the secured assistant allowing 3 requests per minute
    When the client "alice" asks 4 times
    Then the first 3 responses were accepted
    And the response status is 429
    And the body detail is "rate limit exceeded"
    And the Retry-After header is "60"

  Scenario: One client over the limit does not affect another
    Given the secured assistant allowing 3 requests per minute
    When the client "alice" asks 4 times
    And the client "bob" asks "Hola"
    Then the response status is 200

  Scenario: The client can ask again after a minute
    Given the secured assistant allowing 3 requests per minute
    When the client "alice" asks 4 times
    And the clock advances 61 seconds
    And the client "alice" asks "Hola"
    Then the response status is 200

  Scenario: Production refuses to start with the simulated model
    Given production settings with a strong key and the provider "fake"
    When the service starts
    Then startup is refused naming "MODEL_PROVIDER"

  Scenario: A key is never written in the log nor in an error
    Given the secured assistant allowing 3 requests per minute
    When the client "alice" asks "¿Quién es EMP-0004?"
    And the user asks with the key "wrong-key-secret-0001"
    Then the log marks the client "alice"
    And nothing written contains the key of "alice" nor "wrong-key-secret-0001"
