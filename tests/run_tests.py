#!/usr/bin/env python3
"""
Test runner for Plantae MicroPython ESP32 project
"""

import sys
import os
import subprocess
import argparse


def run_unit_tests():
    """Run unit tests"""
    print("Running unit tests...")
    print("=" * 50)
    
    unit_tests = [
        "tests/unit/test_wamp_bridge.py",
        "tests/unit/test_dosing_controller.py", 
        "tests/unit/test_scheduler.py"
    ]
    
    passed = 0
    failed = 0
    
    for test_file in unit_tests:
        if os.path.exists(test_file):
            print(f"\n🧪 Running {test_file}...")
            try:
                result = subprocess.run([sys.executable, test_file], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"✅ {test_file} PASSED")
                    passed += 1
                else:
                    print(f"❌ {test_file} FAILED")
                    print(result.stdout)
                    print(result.stderr)
                    failed += 1
            except Exception as e:
                print(f"❌ {test_file} ERROR: {e}")
                failed += 1
        else:
            print(f"⚠️  {test_file} not found")
    
    print(f"\n📊 Unit test results: {passed} passed, {failed} failed")
    return failed == 0


def run_integration_tests():
    """Run integration tests"""
    print("\nRunning integration tests...")
    print("=" * 50)
    
    integration_tests = [
        "tests/integration/test_wamp_subscriptions.py"
    ]
    
    passed = 0
    failed = 0
    
    for test_file in integration_tests:
        if os.path.exists(test_file):
            print(f"\n🔗 Running {test_file}...")
            try:
                result = subprocess.run([sys.executable, test_file], 
                                      capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    print(f"✅ {test_file} PASSED")
                    passed += 1
                else:
                    print(f"❌ {test_file} FAILED")
                    print(result.stdout)
                    print(result.stderr)
                    failed += 1
            except subprocess.TimeoutExpired:
                print(f"⏰ {test_file} TIMEOUT")
                failed += 1
            except Exception as e:
                print(f"❌ {test_file} ERROR: {e}")
                failed += 1
        else:
            print(f"⚠️  {test_file} not found")
    
    print(f"\n📊 Integration test results: {passed} passed, {failed} failed")
    return failed == 0


def list_manual_tests():
    """List available manual tests"""
    print("\nAvailable manual tests:")
    print("=" * 50)
    
    manual_dir = "tests/manual"
    if os.path.exists(manual_dir):
        for file in os.listdir(manual_dir):
            if file.endswith('.py'):
                print(f"📋 python {os.path.join(manual_dir, file)}")
    else:
        print("⚠️  Manual tests directory not found")


def main():
    parser = argparse.ArgumentParser(description="Run Plantae project tests")
    parser.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("--integration", action="store_true", help="Run integration tests only")
    parser.add_argument("--manual", action="store_true", help="List manual tests")
    parser.add_argument("--all", action="store_true", help="Run all automated tests")
    
    args = parser.parse_args()
    
    if not any([args.unit, args.integration, args.manual, args.all]):
        args.all = True  # Default to all tests
    
    success = True
    
    if args.unit or args.all:
        success &= run_unit_tests()
    
    if args.integration or args.all:
        success &= run_integration_tests()
    
    if args.manual:
        list_manual_tests()
    
    if args.all or args.unit or args.integration:
        print("\n" + "=" * 50)
        if success:
            print("🎉 All tests PASSED!")
            sys.exit(0)
        else:
            print("💥 Some tests FAILED!")
            sys.exit(1)


if __name__ == "__main__":
    main()