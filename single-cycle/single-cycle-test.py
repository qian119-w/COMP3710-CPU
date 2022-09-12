"""
Testing script for COMP3710 uArch CPU assignment. Tests single cycle cpu using tests in a .dig file and shows errors
Author: Nicholas Miehlbradt
"""
import dataclasses
import sys
from argparse import ArgumentParser
import subprocess
import os
import xml.etree.ElementTree as xml
import re

DIGITAL_DEFAULT_PATH = './Digital.jar'
TESTS_DEFAULT_NAME = 'cpu-tests.dig'
TESTS_DEFAULT_LOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), TESTS_DEFAULT_NAME)


@dataclasses.dataclass
class TestResult:
    """
    Class for a test result
    """
    test_name: str  # Name of test
    test_success: bool  # Whether test passed
    test_msg: str = ''  # Additional message, usually the failure message

    def show_test(self, verbose=True):
        """
        Pretty printer for test result
        :param verbose: Whether to show the test message as well
        :return: Formatted string
        """
        return f'Test name: {self.test_name}, Result: {"passed" if self.test_success else "failed"}' \
               f'{chr(10) + self.test_msg if self.test_msg != "" and verbose else ""}'


def run_digital_tests(cpu_path, digital_path, tests_path):
    """
    Runs digital tests using the CLI interface
    :param cpu_path: Path to the digital file containing the cpu to be tested
    :param digital_path: Path to directory containing Digital.jar
    :param tests_path: Path to digital file containing tests
    :return: return code, stdout, stderr of running tests
    """
    output = subprocess.run(
        ['java', '-cp',
         digital_path,  # Path to digital jar file
         'CLI', 'test',  # digital CLI parameters, see section C in digital manual
         cpu_path,  # Specify cpu to test
         '-tests', tests_path,  # Specify file containing tests
         '-verbose'  # Show full test results rather than just success/fail messages
         ], capture_output=True)

    ret_code = output.returncode
    return ret_code, output.stdout.decode('utf-8'), output.stderr.decode('utf-8')


def parse_tests_output(test_output):
    """
    Parses the testing output from running CLI digital tests
    :param test_output: Output from running digital tests using CLI
    :return: A list of test results
    """
    result_lines = iter(test_output.splitlines())
    test_results = []
    for line in result_lines:
        # Ignore tests have failed notification
        if ':' not in line:
            continue

        # Split line to get test name and results
        print(line)
        test_name, test_result = line.split(':', maxsplit=1)
        test_result = test_result.strip()

        # If test has passed
        if test_result == 'passed':
            test_results.append(TestResult(test_name, True))
        # If test has failed due to incorrect output
        elif test_result[:6] == 'failed':
            # Consume test output until the next test is reached
            test_header = next(result_lines)
            test_lines = []
            while (l := next(result_lines)) != '':
                test_lines.append(l)
            info = parse_failing_test(test_name, test_header, test_lines)
            test_results.append(TestResult(test_name, False, info))
        # If test has failed for some other reason e.g. misnamed outputs
        else:
            test_results.append(TestResult(test_name, False, test_result))

    return test_results


def show_state(labels, fields):
    """
    Pretty printer for a test line
    :param labels: List of test column labels
    :param fields: Test output data
    :return: Pretty printed string of CPU state
    """
    return ' '.join((f'{la}: {"0x{:04x}".format(da)}' for la, da in zip(labels, fields) if la != 'CLK'))


def parse_failing_test(test_name, header, test_lines):
    """
    Parses the data of a failing test to identify where the failure occurred
    :param test_name: Name of the test, used to lookup program from testing file
    :param header: Column headers for test data table
    :param test_lines: Test output lines, list of one line per element
    :return: Error message explaining where error occurred
    """
    labels = header.split(' ')  # Get labels for each column in test output
    for i, line in enumerate(test_lines):
        # Parse a test line and see if there are any errors
        correct, expected, found = parse_test_line(line)
        # Find the first failing line
        if not correct:
            # First line is an initialisation line before any instructions have been executed
            # This really is just checking that PC initialises to zero
            if i == 0:
                return f'CPU failed initialisation\n' \
                       f'Expected: {show_state(labels, expected)}\n' \
                       f'Found:    {show_state(labels, found)}\n'
            else:
                # Get the test line immediately before the failed line to get the state before executing instruction
                _, _, prior = parse_test_line(test_lines[i - 1])
                # Find PC of failed instruction
                pc = {la: da for la, da in zip(labels, prior)}['PC']
                # Fetch instruction from test in .dig testing file
                instruction = get_instruction(test_name, pc)
                return f'Instruction failed: {"0x{:04x}".format(instruction) if instruction else ""}\n' \
                       f'Prior State: {show_state(labels, prior)}\n' \
                       f'Expected:    {show_state(labels, expected)}\n' \
                       f'Found:       {show_state(labels, found)}\n'

    return ''


def parse_test_line(test_line):
    """
    Takes a test line and parses it to determine if the line contains errors.
    If there are no errors the expected and found values will be the same
    :param test_line: Line from digital test
    :return: Whether the line contains failures, the expected output, the found output
    """
    parts = iter(test_line.split(' '))
    expected = []
    found = []
    correct_line = True
    for part in parts:
        # Check if result is reporting an error, they have the format E: <expected value> / F: <found value>
        if part == 'E:':
            expected.append(int(next(parts), base=16))  # Expected value
            next(parts)  # / part
            next(parts)  # F: part
            found.append(int(next(parts), base=16))  # Found value
            correct_line = False
        else:  # Add the value to both the expected and found states
            expected.append(int(part, base=16))
            found.append(int(part, base=16))
    return correct_line, expected, found


def get_instruction(test_name, pc):
    """
    Gets the instruction at a specific address from a test
    :param test_name: The name of the test
    :param pc: The address of the instruction
    :return: The instruction or None if invalid
    """
    # Tests is a dictionary created in when running the script
    # Links the name of the test to the test text
    # Probably shouldn't use a global variable for this but whatever I'm tired
    global tests
    if test_name not in tests:
        print('missing', test_name)
        return None
    test_text = tests[test_name]
    # Regex for getting program from test
    # Program string is of the form 'program(<instrs>)' where <instrs> is a sequence of comma separated 4 digit hex
    # numbers. These values are loaded into program memory on test execution.
    regex = r'program\(((0x[0-9a-fA-F]{4})(\,(0x[0-9a-fA-F]{4}))*)?\)'
    program = re.search(regex, test_text)
    if program:  # Check program was found
        instructions = list(map(lambda x: int(x.strip(), base=16), program.group(1).split(',')))
        if pc < len(instructions):
            return instructions[pc]

    return None


def get_lab_config():
    """
    Finds the location of Digital.jar on CSIT lab computers. This is only really necessary because the path seems to
    change depending on how the environment is being accessed.
    :return: The path to Digital.jar
    """
    output = subprocess.run([
        'whereis', 'Digital'
    ], capture_output=True).stdout.decode('utf-8')
    parts = output.split(' ', 1)
    if len(parts) < 2:
        return ''
    else:
        return os.path.join(parts[1].strip(), 'Digital.jar')


if __name__ == '__main__':
    parser = ArgumentParser()

    parser.add_argument('cpu', help='Path to .dig file containing the CPU to test')
    digital_loc_group = parser.add_mutually_exclusive_group()
    digital_loc_group.add_argument('-d', '--digital', default=DIGITAL_DEFAULT_PATH,
                                   help='Path to Digital.jar file. Default assumes script is being run in the '
                                        'directory containing Digital.jar')
    digital_loc_group.add_argument('-l', '--lab', action='store_true',
                                   help='Use this flag when running in the ANU CSIT environment to find the path '
                                        'to Digital.jar. Using this flag outside of this environment will have '
                                        'unpredictable results')
    parser.add_argument('-t', '--tests', default=TESTS_DEFAULT_LOC, help=f'Path to .dig file containing tests. '
                                                                         f'Defaults to {TESTS_DEFAULT_NAME} '
                                                                         f'in the same location as this script')
    parser.add_argument('-v', '--verbose', action='store_true', help='Print detailed error messages on test failure.')

    args = parser.parse_args()

    # Fix to handle change in behaviour of argparse where constants are evaluated even if the argument is not used
    if args.lab:
        args.digital = get_lab_config()

    # Run tests using digital CLI interface, collect results
    return_code, data, err = run_digital_tests(args.cpu, args.digital, args.tests)

    # If running the tests produced an error (not an error in the test output, a real error)
    # print the error and exit
    if err != "":
        if return_code == 1:
            print(f'Could not find Digital\n{err}', file=sys.stderr)
        else:
            print(err, file=sys.stderr)
        exit(1)

    # Parse the tests out of the .dig testing file, putting them into a dict of the test name and test contents
    # Look for visualElements with the elementName child containing 'Testcase'
    # Then look for the elementAttributes child and look for all entry children
    # Each entry element will have the first child being the name of the attribute and the second will be the value
    # Put these all into a dict with the name as key and second element as value
    # Key 'Label' will be the name of the test
    # Key 'Testdata' will be a testData element which will contain a dataString element which will contain the string
    # contents of the test
    # This can then be used by the get_instruction function to parse the program out of this string and extract
    # individual instructions
    # Just have a look at the .dig file containing the tests in a text editor to see how it's organised
    tests = {}
    try:
        document = xml.parse(args.tests)
        for child in document.getroot().iter('visualElement'):
            if (name := child.find('elementName')) is not None and name.text == 'Testcase':
                attribs = {entry[0].text: entry[1] for entry in child.find('elementAttributes')}
                tests[attribs['Label'].text] = attribs['Testdata'] = attribs['Testdata'].find('dataString').text
    # All the things that could possibly go wrong if the XML in the file doesn't match
    # If this doesn't work then the only thing that can't happen is the display of the specific instruction that caused
    # the error. Notify user and carry on, rest of results could still be valuable
    except TypeError as e:
        print(f'Error parsing test case file {args.tests}', file=sys.stderr)
    except KeyError as e:
        print(f'Error parsing test case file {args.tests}', file=sys.stderr)
    except AttributeError as e:
        print(f'Error parsing test case file {args.tests}', file=sys.stderr)

    num_success = 0
    num_total = 0
    # Parse the test output and display
    for result in parse_tests_output(data):
        num_total += 1
        num_success += 1 if result.test_success else 0
        print(result.show_test(args.verbose))

    print(f'\n{num_success}/{num_total} Tests passed')
