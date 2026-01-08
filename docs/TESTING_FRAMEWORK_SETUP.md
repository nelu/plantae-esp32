# Testing Framework Setup

## Overview
This document describes the testing framework that has been set up for the Plantae MicroPython ESP32 project.

## What Was Created

### Test Directory Structure
```
tests/
├── README.md                           # Test documentation
├── run_tests.py                        # Test runner script
├── unit/                              # Unit tests
│   ├── test_wamp_bridge.py            # WampBridge class tests
│   ├── test_dosing_controller.py      # DosingController class tests
│   └── test_scheduler.py              # Scheduler function tests
├── integration/                       # Integration tests
│   └── test_wamp_subscriptions.py     # WAMP integration tests
└── manual/                            # Manual test scripts
    ├── debug_wamp_subscriptions.py    # MicroPython WAMP debug
    ├── debug_wamp_regular_python.py   # Python WAMP debug
    └── test_wamp_simple.py            # Simple WAMP test
```

### Documentation Improvements
- Moved test documentation from Python print statements to proper Markdown files
- Created comprehensive project guidelines in `PROJECT_GUIDELINES.md`
- Added specific testing documentation for WAMP functionality
- Organized all documentation in the `docs/` directory

### Test Categories

#### Unit Tests
- **test_wamp_bridge.py**: Tests for WampBridge class methods
  - Topic generation and addressing
  - RPC handlers (control, calibrate, dose, status, etc.)
  - Master announcement handling
  - Configuration management

- **test_dosing_controller.py**: Tests for DosingController class
  - Dose start/stop functionality
  - Progress tracking and status reporting
  - Update cycle handling
  - Error conditions

- **test_scheduler.py**: Tests for scheduler functions
  - Time string parsing
  - Schedule duty calculation
  - Interval timing logic
  - Edge cases and error handling

#### Integration Tests
- **test_wamp_subscriptions.py**: Full WAMP protocol testing
  - Uses standard autobahn library for comparison
  - Tests subscriptions, RPC calls, and publishing
  - Verifies WAMP router connectivity
  - Can test against actual device

#### Manual Tests
- **debug_wamp_subscriptions.py**: MicroPython debug script
  - Comprehensive WAMP debugging with detailed logging
  - Tests subscriptions and RPC functionality
  - Designed to run on ESP32 device

- **debug_wamp_regular_python.py**: Regular Python debug script
  - Uses autobahn library for reference implementation
  - Can run on development machine
  - Helps verify WAMP router functionality

- **test_wamp_simple.py**: Simple MicroPython test
  - Minimal test for basic subscription functionality
  - Quick verification of WAMP fix

### Test Runner
The `tests/run_tests.py` script provides:
- Automated execution of unit and integration tests
- Test result reporting with pass/fail counts
- Timeout handling for integration tests
- Manual test listing
- Command-line options for selective test execution

## Usage

### Running Tests
```bash
# Run all automated tests
python tests/run_tests.py

# Run only unit tests
python tests/run_tests.py --unit

# Run only integration tests  
python tests/run_tests.py --integration

# List manual tests
python tests/run_tests.py --manual

# Run individual test
python tests/unit/test_wamp_bridge.py
```

### Manual Testing
```bash
# Debug WAMP on development machine
python tests/manual/debug_wamp_regular_python.py

# Debug WAMP on ESP32 (upload and run)
python tests/manual/debug_wamp_subscriptions.py

# Simple WAMP test on ESP32
python tests/manual/test_wamp_simple.py
```

## Benefits

### Code Quality
- Comprehensive test coverage for critical components
- Automated regression testing
- Clear separation of test types and purposes

### Documentation
- Proper markdown documentation instead of code comments
- Centralized project guidelines
- Clear testing procedures and expectations

### Debugging
- Multiple levels of debugging tools
- Both MicroPython and regular Python test options
- Detailed logging and error reporting

### Maintainability
- Organized test structure following best practices
- Easy to add new tests and extend coverage
- Clear patterns for different types of testing

## Future Enhancements

### Additional Tests Needed
- Hardware driver tests (PWM, flow sensor, I2C)
- WiFi connection and recovery tests
- Configuration management tests
- Scheduler integration tests
- Error recovery and resilience tests

### Test Infrastructure
- Continuous integration setup
- Automated hardware-in-the-loop testing
- Performance and memory usage tests
- Mock hardware for unit testing

### Documentation
- API documentation generation
- Test coverage reporting
- Performance benchmarking results