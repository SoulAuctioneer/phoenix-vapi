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

async def run_module_async_tests(module):
    """Run a module's async tests directly without using its run_tests function."""
    print(f"\nRunning async tests in {module.__name__}...")
    
    # Get test class
    test_classes = [obj for name, obj in module.__dict__.items() 
                  if isinstance(obj, type) and issubclass(obj, unittest.TestCase)]
    
    for test_class in test_classes:
        # Get all test methods
        test_methods = [m for m in dir(test_class) if m.startswith('test_')]
        
        # Create an instance of the test class
        test_instance = test_class()
        
        # Run setUp, test, and tearDown for each test method
        for method_name in test_methods:
            try:
                test_instance.setUp()
                test_method = getattr(test_instance, method_name)
                if asyncio.iscoroutinefunction(test_method):
                    await test_method()
                    print(f"✅ {test_class.__name__}.{method_name} passed")
            except Exception as e:
                print(f"❌ {test_class.__name__}.{method_name} failed: {e}")
            finally:
                test_instance.tearDown()

async def run_all_async_tests(test_modules):
    """Run all async tests from all modules."""
    for module in test_modules:
        await run_module_async_tests(module)

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

async def main_async():
    """Main async function to run all tests."""
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
    await run_all_async_tests(test_modules)
    
    # Return appropriate exit code
    return 0 if result.wasSuccessful() else 1

def main():
    """Main entry point that runs the async main function."""
    return asyncio.run(main_async())

if __name__ == "__main__":
    sys.exit(main()) 