#!/usr/bin/env python3
"""
Test runner for the Phoenix VAPI project.

This script runs all the unit tests in the tests/unit directory.
"""

import unittest
import asyncio
import sys
import os
import importlib.util
from pathlib import Path

def load_test_modules():
    """Discover and load all test modules in tests/unit directory."""
    test_dir = Path(__file__).parent / 'unit'
    test_modules = []
    
    # Find all test files
    for file in test_dir.glob('test_*.py'):
        # Import the module
        module_name = file.stem
        spec = importlib.util.spec_from_file_location(module_name, file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        test_modules.append(module)
    
    return test_modules

def run_async_tests(test_modules):
    """Run async tests that aren't compatible with unittest's standard runner."""
    async def run_all_async():
        for module in test_modules:
            # If the module has a run_tests function, call it
            if hasattr(module, 'run_tests'):
                print(f"\nRunning async tests in {module.__name__}...")
                module.run_tests()
                
    # Run async tests
    asyncio.run(run_all_async())

def run_standard_tests(test_modules):
    """Run tests using unittest's standard TestCase framework."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add tests from each module to the test suite
    for module in test_modules:
        tests = loader.loadTestsFromModule(module)
        suite.addTests(tests)
    
    # Run the tests
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)

def main():
    """Main function to run all tests."""
    # Add the src directory to the Python path
    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../src'))
    sys.path.append(src_dir)
    
    # Load test modules
    test_modules = load_test_modules()
    
    print(f"Found {len(test_modules)} test modules")
    
    # Run standard unittest tests
    print("\nRunning standard tests...")
    result = run_standard_tests(test_modules)
    
    # Run async tests that need special handling
    print("\nRunning async tests...")
    run_async_tests(test_modules)
    
    # Return appropriate exit code
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    sys.exit(main()) 