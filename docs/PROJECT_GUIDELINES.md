# Plantae MicroPython ESP32 - Project Guidelines

## Project Structure

```
plantae-micropython-esp32/
├── src/                    # Main source code
│   ├── adapters/          # External interface adapters (WiFi, WAMP, HTTP, etc.)
│   ├── app/               # Application layer (supervisor, device ID)
│   ├── domain/            # Business logic (controllers, dosing, scheduler, state)
│   ├── drivers/           # Hardware drivers (PWM, flow sensor, PCA9685)
│   ├── lib/               # Utility libraries (logging)
│   ├── protocols/         # Communication protocols (WAMP client)
│   ├── config.json        # Device configuration
│   └── main.py            # Application entry point
├── tests/                 # Test suite
│   ├── unit/              # Unit tests for individual components
│   ├── integration/       # Integration tests (WAMP, hardware)
│   ├── manual/            # Manual test scripts for debugging
│   ├── run_tests.py       # Test runner script
│   └── README.md          # Test documentation
├── docs/                  # Documentation
│   ├── README.md          # Main project documentation
│   ├── DOSING.md          # Dosing system documentation
│   ├── FIXES_SUMMARY.md   # Summary of fixes and improvements
│   ├── WAMP_SUBSCRIPTION_FIX.md      # WAMP subscription fix details
│   └── WAMP_MASTER_ANNOUNCE_TEST.md  # Testing guide
├── web/                   # Web client implementations
├── legacy/                # Legacy Arduino code
└── PROJECT_GUIDELINES.md  # This file
```

## Development Guidelines

### Code Organization

1. **Separation of Concerns**: Follow the adapter/domain/driver pattern
   - `adapters/`: External interfaces (network, protocols)
   - `domain/`: Business logic and core functionality  
   - `drivers/`: Hardware abstraction layer

2. **Configuration**: All configuration in `src/config.json`
   - Environment-specific settings
   - Hardware pin assignments
   - Network and protocol settings
   - Logging configuration

3. **Error Handling**: Comprehensive error handling and logging
   - Use structured logging with appropriate levels
   - Graceful degradation on component failures
   - Clear error messages for debugging

### Testing Strategy

#### Unit Tests (`tests/unit/`)
- Test individual classes and functions in isolation
- Mock external dependencies
- Fast execution, no hardware required
- Run with: `python tests/run_tests.py --unit`

#### Integration Tests (`tests/integration/`)
- Test component interactions
- May require external services (WAMP router)
- Test real network protocols
- Run with: `python tests/run_tests.py --integration`

#### Manual Tests (`tests/manual/`)
- Debug scripts for troubleshooting
- Hardware-specific tests
- Interactive testing tools
- Run individually as needed

### Testing Best Practices

1. **Test Naming**: Use descriptive test names
   ```python
   def test_rpc_dose_start_valid_quantity(self):
   def test_subscription_callback_with_invalid_message(self):
   ```

2. **Test Structure**: Follow Arrange-Act-Assert pattern
   ```python
   def test_something(self):
       # Arrange
       setup_test_data()
       
       # Act  
       result = function_under_test()
       
       # Assert
       self.assertEqual(result, expected)
   ```

3. **Mocking**: Mock external dependencies in unit tests
   ```python
   @patch('src.adapters.wamp_bridge.AutobahnWS')
   def test_wamp_connection(self, mock_autobahn):
       # Test implementation
   ```

4. **Async Testing**: Handle async code properly
   ```python
   async def test_async_function(self):
       result = await async_function()
       self.assertTrue(result)
   ```

### Documentation Standards

1. **Code Documentation**: Use docstrings for classes and methods
   ```python
   async def rpc_dose(self, args, kwargs, details):
       """Handle dosing RPC calls
       
       Args:
           args: RPC arguments
           kwargs: RPC keyword arguments  
           details: WAMP call details
           
       Returns:
           dict: Dosing operation result
       """
   ```

2. **Markdown Documentation**: Use markdown for all documentation
   - Clear headings and structure
   - Code examples with syntax highlighting
   - Step-by-step procedures for testing

3. **Change Documentation**: Document significant changes
   - Add entries to `docs/FIXES_SUMMARY.md`
   - Create specific documentation for major fixes
   - Include before/after examples

### Code Quality

1. **Imports**: Organize imports clearly
   ```python
   # Standard library
   import time
   import uasyncio as asyncio
   
   # Local imports
   from domain.state import DeviceState
   ```

2. **Error Handling**: Use appropriate exception handling
   ```python
   try:
       await risky_operation()
   except SpecificException as e:
       LOG.error("Operation failed: %s", e)
       return {"error": "operation_failed"}
   ```

3. **Logging**: Use structured logging
   ```python
   LOG = getLogger("component_name")
   LOG.debug("Debug info: %s", variable)
   LOG.info("Important event occurred")
   LOG.error("Error occurred: %s", error)
   ```

### Running Tests

```bash
# Run all tests
python tests/run_tests.py

# Run specific test types
python tests/run_tests.py --unit
python tests/run_tests.py --integration

# List manual tests
python tests/run_tests.py --manual

# Run individual test
python tests/unit/test_wamp_bridge.py
```

### Adding New Features

1. **Create Tests First**: Write tests before implementation
2. **Update Documentation**: Add/update relevant documentation
3. **Test on Hardware**: Verify functionality on actual ESP32
4. **Update Configuration**: Add new config options if needed

### Debugging

1. **Enable Debug Logging**: Set logging level to DEBUG in config.json
2. **Use Manual Tests**: Run appropriate manual test scripts
3. **Check Hardware**: Verify physical connections and power
4. **Network Issues**: Test connectivity and protocol functionality

### MicroPython Considerations

1. **Memory Management**: Be mindful of memory usage
   - Use `gc.collect()` after large operations
   - Monitor memory with `gc.mem_free()`

2. **Async Programming**: Use `uasyncio` properly
   - Avoid blocking operations in async functions
   - Use `await asyncio.sleep_ms()` for delays

3. **Hardware Abstraction**: Keep hardware-specific code in drivers/
   - Use Pin, I2C, SPI classes appropriately
   - Handle hardware initialization gracefully

4. **Error Recovery**: Implement robust error recovery
   - Reconnect on network failures
   - Reset hardware on errors
   - Graceful degradation of functionality