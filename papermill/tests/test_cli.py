#!/usr/bin/env python
""" Test the command line interface """

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import nbclient
import nbformat
import pytest
from click.testing import CliRunner

from .. import cli
from ..cli import _is_float, _is_int, _resolve_type, papermill
from . import get_notebook_path, kernel_name


@pytest.mark.parametrize(
    "test_input,expected",
    [
        ("True", True),
        ("False", False),
        ("None", None),
        ("12.51", 12.51),
        ("10", 10),
        ("hello world", "hello world"),
        ("😍", "😍"),
    ],
)
def test_resolve_type(test_input, expected):
    assert _resolve_type(test_input) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (13.71, True),
        ("False", False),
        ("None", False),
        (-8.2, True),
        (10, True),
        ("10", True),
        ("12.31", True),
        ("hello world", False),
        ("😍", False),
    ],
)
def test_is_float(value, expected):
    assert (_is_float(value)) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (13.71, True),
        ("False", False),
        ("None", False),
        (-8.2, True),
        ("-23.2", False),
        (10, True),
        ("13", True),
        ("hello world", False),
        ("😍", False),
    ],
)
def test_is_int(value, expected):
    assert (_is_int(value)) == expected


class TestCLI(unittest.TestCase):
    default_execute_kwargs = dict(
        input_path='input.ipynb',
        output_path='output.ipynb',
        parameters={},
        engine_name=None,
        request_save_on_cell_execute=True,
        autosave_cell_every=30,
        prepare_only=False,
        kernel_name=None,
        language=None,
        log_output=False,
        progress_bar=True,
        start_timeout=60,
        execution_timeout=None,
        report_mode=False,
        cwd=None,
        obfuscate_sensitive_parameters=True,
        sensitive_parameter_patterns=None,
        stdout_file=None,
        stderr_file=None,
    )

    def setUp(self):
        self.runner = CliRunner()
        self.default_args = [
            self.default_execute_kwargs['input_path'],
            self.default_execute_kwargs['output_path'],
        ]
        self.sample_yaml_file = os.path.join(os.path.dirname(__file__), 'parameters', 'example.yaml')
        self.sample_json_file = os.path.join(os.path.dirname(__file__), 'parameters', 'example.json')

    def augment_execute_kwargs(self, **new_kwargs):
        kwargs = self.default_execute_kwargs.copy()
        kwargs.update(new_kwargs)
        return kwargs

    @patch(f"{cli.__name__}.execute_notebook")
    def test_parameters(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['-p', 'foo', 'bar', '--parameters', 'baz', '42'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(parameters={'foo': 'bar', 'baz': 42}))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_parameters_raw(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['-r', 'foo', 'bar', '--parameters_raw', 'baz', '42'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(parameters={'foo': 'bar', 'baz': '42'}))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_parameters_file(self, execute_patch):
        extra_args = ['-f', self.sample_yaml_file, '--parameters_file', self.sample_json_file]
        self.runner.invoke(papermill, self.default_args + extra_args)
        execute_patch.assert_called_with(
            **self.augment_execute_kwargs(
                # Last input wins dict update
                parameters={
                    'foo': 54321,
                    'bar': 'value',
                    'baz': {'k2': 'v2', 'k1': 'v1'},
                    'a_date': '2019-01-01',
                }
            )
        )

    @patch(f"{cli.__name__}.execute_notebook")
    def test_parameters_yaml(self, execute_patch):
        self.runner.invoke(
            papermill,
            self.default_args + ['-y', '{"foo": "bar"}', '--parameters_yaml', '{"foo2": ["baz"]}'],
        )
        execute_patch.assert_called_with(**self.augment_execute_kwargs(parameters={'foo': 'bar', 'foo2': ['baz']}))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_parameters_yaml_date(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['-y', 'a_date: 2019-01-01'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(parameters={'a_date': '2019-01-01'}))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_parameters_empty(self, execute_patch):
        # "#empty" ---base64--> "I2VtcHR5"
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_yaml = Path(tmpdir) / 'empty.yaml'
            empty_yaml.write_text('#empty')
            extra_args = [
                '--parameters_file',
                str(empty_yaml),
                '--parameters_yaml',
                '#empty',
                '--parameters_base64',
                'I2VtcHR5',
            ]
            self.runner.invoke(
                papermill,
                self.default_args + extra_args,
            )
            execute_patch.assert_called_with(
                **self.augment_execute_kwargs(
                    # should be empty
                    parameters={}
                )
            )

    @patch(f"{cli.__name__}.execute_notebook")
    def test_parameters_yaml_override(self, execute_patch):
        self.runner.invoke(
            papermill,
            self.default_args + ['--parameters_yaml', '{"foo": "bar"}', '-y', '{"foo": ["baz"]}'],
        )
        execute_patch.assert_called_with(
            **self.augment_execute_kwargs(
                # Last input wins dict update
                parameters={'foo': ['baz']}
            )
        )

    @patch(f"{cli.__name__}.execute_notebook", side_effect=nbclient.exceptions.DeadKernelError("Fake"))
    def test_parameters_dead_kernel(self, execute_patch):
        result = self.runner.invoke(
            papermill,
            self.default_args + ['--parameters_yaml', '{"foo": "bar"}', '-y', '{"foo": ["baz"]}'],
        )
        assert result.exit_code == 138

    @patch(f"{cli.__name__}.execute_notebook")
    def test_parameters_base64(self, execute_patch):
        extra_args = [
            '--parameters_base64',
            'eyJmb28iOiAicmVwbGFjZWQiLCAiYmFyIjogMn0=',
            '-b',
            'eydmb28nOiAxfQ==',
        ]
        self.runner.invoke(papermill, self.default_args + extra_args)
        execute_patch.assert_called_with(**self.augment_execute_kwargs(parameters={'foo': 1, 'bar': 2}))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_parameters_base64_date(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--parameters_base64', 'YV9kYXRlOiAyMDE5LTAxLTAx'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(parameters={'a_date': '2019-01-01'}))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_inject_input_path(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--inject-input-path'])
        execute_patch.assert_called_with(
            **self.augment_execute_kwargs(parameters={'PAPERMILL_INPUT_PATH': 'input.ipynb'})
        )

    @patch(f"{cli.__name__}.execute_notebook")
    def test_inject_output_path(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--inject-output-path'])
        execute_patch.assert_called_with(
            **self.augment_execute_kwargs(parameters={'PAPERMILL_OUTPUT_PATH': 'output.ipynb'})
        )

    @patch(f"{cli.__name__}.execute_notebook")
    def test_inject_paths(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--inject-paths'])
        execute_patch.assert_called_with(
            **self.augment_execute_kwargs(
                parameters={
                    'PAPERMILL_INPUT_PATH': 'input.ipynb',
                    'PAPERMILL_OUTPUT_PATH': 'output.ipynb',
                }
            )
        )

    @patch(f"{cli.__name__}.execute_notebook")
    def test_engine(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--engine', 'engine-that-could'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(engine_name='engine-that-could'))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_prepare_only(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--prepare-only'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(prepare_only=True))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_kernel(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['-k', 'python3'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(kernel_name='python3'))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_language(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['-l', 'python'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(language='python'))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_set_cwd(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--cwd', 'a/path/here'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(cwd='a/path/here'))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_progress_bar(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--progress-bar'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(progress_bar=True))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_no_progress_bar(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--no-progress-bar'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(progress_bar=False))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_log_output(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--log-output'])
        execute_patch.assert_called_with(
            **self.augment_execute_kwargs(
                log_output=True,
                progress_bar=False,  # Setting log-output should disable progress bar by default
            )
        )

    @patch(f"{cli.__name__}.execute_notebook")
    def test_log_output_plus_progress(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--log-output', '--progress-bar'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(log_output=True, progress_bar=True))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_no_log_output(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--no-log-output'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(log_output=False))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_log_level(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--log-level', 'WARNING'])
        # TODO: this does not actually test log-level being set
        execute_patch.assert_called_with(**self.augment_execute_kwargs())

    @patch(f"{cli.__name__}.execute_notebook")
    def test_start_timeout(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--start-timeout', '123'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(start_timeout=123))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_start_timeout_backwards_compatibility(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--start_timeout', '123'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(start_timeout=123))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_execution_timeout(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--execution-timeout', '123'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(execution_timeout=123))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_report_mode(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--report-mode'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(report_mode=True))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_no_report_mode(self, execute_patch):
        self.runner.invoke(papermill, self.default_args + ['--no-report-mode'])
        execute_patch.assert_called_with(**self.augment_execute_kwargs(report_mode=False))

    @patch(f"{cli.__name__}.execute_notebook")
    def test_version(self, execute_patch):
        self.runner.invoke(papermill, ['--version'])
        execute_patch.assert_not_called()

    @patch(f"{cli.__name__}.execute_notebook")
    @patch(f"{cli.__name__}.display_notebook_help")
    def test_help_notebook(self, display_notebook_help, execute_path):
        self.runner.invoke(papermill, ['--help-notebook', 'input_path.ipynb'])
        execute_path.assert_not_called()
        assert display_notebook_help.call_count == 1
        assert display_notebook_help.call_args[0][1] == 'input_path.ipynb'

    @patch(f"{cli.__name__}.execute_notebook")
    def test_many_args(self, execute_patch):
        extra_args = [
            '-f',
            self.sample_yaml_file,
            '-y',
            '{"yaml_foo": {"yaml_bar": "yaml_baz"}}',
            '-b',
            'eyJiYXNlNjRfZm9vIjogImJhc2U2NF9iYXIifQ==',
            '-p',
            'baz',
            'replace',
            '-r',
            'foo',
            '54321',
            '--kernel',
            'R',
            '--engine',
            'engine-that-could',
            '--prepare-only',
            '--log-output',
            '--autosave-cell-every',
            '17',
            '--no-progress-bar',
            '--start-timeout',
            '321',
            '--execution-timeout',
            '654',
            '--report-mode',
        ]
        self.runner.invoke(
            papermill,
            self.default_args + extra_args,
        )
        execute_patch.assert_called_with(
            **self.augment_execute_kwargs(
                parameters={
                    'foo': '54321',
                    'bar': 'value',
                    'baz': 'replace',
                    'yaml_foo': {'yaml_bar': 'yaml_baz'},
                    "base64_foo": "base64_bar",
                    'a_date': '2019-01-01',
                },
                engine_name='engine-that-could',
                request_save_on_cell_execute=True,
                autosave_cell_every=17,
                prepare_only=True,
                kernel_name='R',
                log_output=True,
                progress_bar=False,
                start_timeout=321,
                execution_timeout=654,
                report_mode=True,
                cwd=None,
            )
        )


def papermill_cli(papermill_args=None, **kwargs):
    cmd = [sys.executable, '-m', 'papermill']
    if papermill_args:
        cmd.extend(papermill_args)
    return subprocess.Popen(cmd, **kwargs)


def papermill_version():
    try:
        proc = papermill_cli(['--version'], stdout=subprocess.PIPE)
        out, _ = proc.communicate()
        if proc.returncode:
            return None
        return out.decode('utf-8')
    except (OSError, SystemExit):  # pragma: no cover
        return None


@pytest.fixture()
def notebook():
    metadata = {'kernelspec': {'name': 'python3', 'language': 'python', 'display_name': 'python3'}}
    return nbformat.v4.new_notebook(
        metadata=metadata,
        cells=[nbformat.v4.new_markdown_cell('This is a notebook with kernel: python3')],
    )


require_papermill_installed = pytest.mark.skipif(not papermill_version(), reason='papermill is not installed')


@require_papermill_installed
def test_pipe_in_out_auto(notebook):
    process = papermill_cli(stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    text = nbformat.writes(notebook)
    out, err = process.communicate(input=text.encode('utf-8'))

    # Test no message on std error
    assert not err

    # Test that output is a valid notebook
    nbformat.reads(out.decode('utf-8'), as_version=4)


@require_papermill_installed
def test_pipe_in_out_explicit(notebook):
    process = papermill_cli(['-', '-'], stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    text = nbformat.writes(notebook)
    out, err = process.communicate(input=text.encode('utf-8'))

    # Test no message on std error
    assert not err

    # Test that output is a valid notebook
    nbformat.reads(out.decode('utf-8'), as_version=4)


@require_papermill_installed
def test_pipe_out_auto(tmpdir, notebook):
    nb_file = tmpdir.join('notebook.ipynb')
    nb_file.write(nbformat.writes(notebook))

    process = papermill_cli([str(nb_file)], stdout=subprocess.PIPE)
    out, err = process.communicate()

    # Test no message on std error
    assert not err

    # Test that output is a valid notebook
    nbformat.reads(out.decode('utf-8'), as_version=4)


@require_papermill_installed
def test_pipe_out_explicit(tmpdir, notebook):
    nb_file = tmpdir.join('notebook.ipynb')
    nb_file.write(nbformat.writes(notebook))

    process = papermill_cli([str(nb_file), '-'], stdout=subprocess.PIPE)
    out, err = process.communicate()

    # Test no message on std error
    assert not err

    # Test that output is a valid notebook
    nbformat.reads(out.decode('utf-8'), as_version=4)


@require_papermill_installed
def test_pipe_in_auto(tmpdir, notebook):
    nb_file = tmpdir.join('notebook.ipynb')

    process = papermill_cli([str(nb_file)], stdin=subprocess.PIPE)
    text = nbformat.writes(notebook)
    out, _ = process.communicate(input=text.encode('utf-8'))

    # Nothing on stdout
    assert not out

    # Test that output is a valid notebook
    with open(str(nb_file)) as fp:
        nbformat.reads(fp.read(), as_version=4)


@require_papermill_installed
def test_pipe_in_explicit(tmpdir, notebook):
    nb_file = tmpdir.join('notebook.ipynb')

    process = papermill_cli(['-', str(nb_file)], stdin=subprocess.PIPE)
    text = nbformat.writes(notebook)
    out, _ = process.communicate(input=text.encode('utf-8'))

    # Nothing on stdout
    assert not out

    # Test that output is a valid notebook
    with open(str(nb_file)) as fp:
        nbformat.reads(fp.read(), as_version=4)


@require_papermill_installed
def test_stdout_file(tmpdir):
    nb_file = tmpdir.join('notebook.ipynb')
    stdout_file = tmpdir.join('notebook.stdout')
    secret = str(uuid.uuid4())

    process = papermill_cli(
        [
            get_notebook_path('simple_execute.ipynb'),
            str(nb_file),
            '-k',
            kernel_name,
            '-p',
            'msg',
            secret,
            '--stdout-file',
            str(stdout_file),
        ]
    )
    out, err = process.communicate()

    assert not out
    assert not err

    with open(str(stdout_file)) as fp:
        assert fp.read() == f"{secret}\n"


@require_papermill_installed
def test_obfuscated_output():
    metadata = {'kernelspec': {'name': 'python3', 'language': 'python', 'display_name': 'python3'}}
    secret = str(uuid.uuid4())
    notebook = nbformat.v4.new_notebook(
        metadata=metadata,
        cells=[
            nbformat.v4.new_code_cell('print(safe_text, "=", token)'),
        ],
    )
    process = papermill_cli(
        [
            '-',
            '-',
            '-p',
            'token',
            secret,
            '-p',
            'safe_text',
            'Test',
        ],
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
    )
    text = nbformat.writes(notebook)
    out, err = process.communicate(input=text.encode('utf-8'))

    # Test no message on std error
    assert not err

    # Test that secrets in the output are obfuscated
    output_notebook = nbformat.reads(out.decode('utf-8'), as_version=4)

    # secret in the notebook metadata should be obfuscated
    assert output_notebook.metadata['papermill']['parameters'] == {
        'safe_text': 'Test',
        'token': '********',
    }

    assert len(output_notebook.cells) == 2

    # secret in the injected parameters cell should be obfuscated
    assert output_notebook.cells[0].cell_type == 'code'
    assert output_notebook.cells[0].source == '# Parameters\ntoken = "********"\nsafe_text = "Test"\n'

    # secret in the output cell will be printed as is
    assert output_notebook.cells[1].cell_type == 'code'
    assert len(output_notebook.cells[1].outputs) == 1
    assert output_notebook.cells[1].outputs[0].output_type == 'stream'
    assert output_notebook.cells[1].outputs[0].text == f'Test = {secret}\n'

@require_papermill_installed
def test_disable_output_obfuscation():
    metadata = {'kernelspec': {'name': 'python3', 'language': 'python', 'display_name': 'python3'}}
    secret = str(uuid.uuid4())
    notebook = nbformat.v4.new_notebook(
        metadata=metadata,
        cells=[
            nbformat.v4.new_code_cell('print(safe_text, "=", token)'),
        ],
    )
    process = papermill_cli(
        [
            '-',
            '-',
            '-p',
            'token',
            secret,
            '-p',
            'safe_text',
            'Test',
            '--no-obfuscate-sensitive-parameters',
        ],
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
    )
    text = nbformat.writes(notebook)
    out, err = process.communicate(input=text.encode('utf-8'))

    # Test no message on std error
    assert not err

    # Test that secrets in the output are not obfuscated
    output_notebook = nbformat.reads(out.decode('utf-8'), as_version=4)

    # secret in the notebook metadata should not be obfuscated
    assert output_notebook.metadata['papermill']['parameters'] == {
        'safe_text': 'Test',
        'token': secret,
    }

    assert len(output_notebook.cells) == 2

    # secret in the injected parameters cell should be obfuscated
    assert output_notebook.cells[0].cell_type == 'code'
    assert output_notebook.cells[0].source == f'# Parameters\ntoken = "{secret}"\nsafe_text = "Test"\n'

    # secret in the output cell will be printed as is
    assert output_notebook.cells[1].cell_type == 'code'
    assert len(output_notebook.cells[1].outputs) == 1
    assert output_notebook.cells[1].outputs[0].output_type == 'stream'
    assert output_notebook.cells[1].outputs[0].text == f'Test = {secret}\n'

@require_papermill_installed
def test_custom_output_obfuscation():
    metadata = {'kernelspec': {'name': 'python3', 'language': 'python', 'display_name': 'python3'}}
    secret = str(uuid.uuid4())
    notebook = nbformat.v4.new_notebook(
        metadata=metadata,
        cells=[
            nbformat.v4.new_code_cell('print(safe_text, "=", token)'),
        ],
    )
    process = papermill_cli(
        [
            '-',
            '-',
            '-p',
            'token',
            secret,
            '-p',
            'safe_text',
            'Test',
            '--sensitive-parameter-patterns',
            'safe_text',
        ],
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
    )
    text = nbformat.writes(notebook)
    out, err = process.communicate(input=text.encode('utf-8'))

    # Test no message on std error
    assert not err

    # Test that secrets in the output are obfuscated
    output_notebook = nbformat.reads(out.decode('utf-8'), as_version=4)

    # secret in the notebook metadata should be obfuscated
    # --sensitive-parameter-patterns should be set to obfuscate 'safe_text' and not 'token'
    assert output_notebook.metadata['papermill']['parameters'] == {
        'safe_text': '********',
        'token': secret,
    }

    assert len(output_notebook.cells) == 2

    # secret in the injected parameters cell should be obfuscated
    assert output_notebook.cells[0].cell_type == 'code'
    assert output_notebook.cells[0].source == f'# Parameters\ntoken = "{secret}"\nsafe_text = "********"\n'

    # secret in the output cell will be printed as is
    assert output_notebook.cells[1].cell_type == 'code'
    assert len(output_notebook.cells[1].outputs) == 1
    assert output_notebook.cells[1].outputs[0].output_type == 'stream'
    assert output_notebook.cells[1].outputs[0].text == f'Test = {secret}\n'
